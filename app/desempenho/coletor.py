"""Coletor: de hora em hora, le nas redes os numeros dos posts publicados ha menos de 7 dias.

Regras:
- Guarda a leitura mais recente ('atual') e uma "foto" quando o post completa 24 h, 3 dias e 7 dias.
  A foto so e tirada dentro de 6 h depois da idade certa: se o painel ficou desligado e passou disso,
  o post fica sem aquela foto (melhor vazio do que um numero de 50 h chamado de "24 h").
- Post que a rede diz nao existir mais vira "removido": para de ser lido, o historico fica.
- Nunca mexe no estado, horario ou erro de um post. Rede fora do ar ou erro de permissao: so registra
  e tenta na proxima rodada. So o acesso vencido marca a conta para reconectar (como o publicador faz).
- Nao gasta creditos de IA.

Rodar uma vez, sozinho:
    python -m app.desempenho.coletor
"""
import threading
from collections import defaultdict
from datetime import datetime, timedelta

from app import avisos, config
from app.desempenho import repositorio
from app.postagem import agendador, contas, meta, youtube
from app.postagem.cofre import ErroCofre
from app.postagem.redes import REDES, ErroPostagem

log = config.criar_log("desempenho")

LEITORES = {"youtube": youtube.ler_numeros, "instagram": meta.ler_numeros_instagram,
            "facebook": meta.ler_numeros_facebook}           # TikTok: sem leitor nesta fase
MARCOS = (("24h", 24), ("3d", 72), ("7d", 168))              # (nome, horas de vida)
TOLERANCIA_H = 6
IDADE_MAXIMA_H = 170
INTERVALO_S = 3600

_trava = threading.Lock()


def rodar(momento_agora: datetime | None = None) -> dict:
    """Uma rodada. Devolve {"lidas", "removidas", "falhas", "ocupado"}."""
    resultado = {"lidas": 0, "removidas": 0, "falhas": 0, "ocupado": False}
    if not _trava.acquire(blocking=False):
        return resultado | {"ocupado": True}
    try:
        agora = momento_agora or agendador.agora()
        agora_texto = agendador.texto(agora)
        por_conta: dict[int, list[dict]] = defaultdict(list)
        for post in repositorio.publicacoes_para_ler(agora_texto, IDADE_MAXIMA_H):
            if post["rede"] in LEITORES:
                por_conta[post["conta_id"]].append(post)
        for conta_id, posts in por_conta.items():
            _ler_conta(conta_id, posts, agora, resultado)
        log.info("Desempenho: %d lidos, %d removidos, %d contas com falha.",
                 resultado["lidas"], resultado["removidas"], resultado["falhas"])
        return resultado
    finally:
        _trava.release()


def _ler_conta(conta_id: int, posts: list[dict], agora: datetime, resultado: dict) -> None:
    rede = posts[0]["rede"]
    try:
        credenciais = contas.credenciais_da_conta(conta_id)
        try:
            numeros = LEITORES[rede](credenciais, [p["id_externo"] for p in posts])
        finally:
            if credenciais.mudou:                     # token renovado no caminho: guarda o novo
                contas.regravar_credenciais(conta_id, credenciais)
    except (ErroCofre, ErroPostagem) as erro:
        resultado["falhas"] += 1
        log.warning("Desempenho: nao li a conta %d (%s): %s", conta_id, rede, erro)
        if isinstance(erro, ErroCofre) or erro.reconectar:
            conta = contas.ler_conta(conta_id)
            contas.atualizar_conta(conta_id, estado="expirada", erro=str(erro))
            avisos.avisar(f"🔌 A conta {conta['nome']} ({REDES[rede]['nome']}) precisa ser conectada de novo "
                          f"na tela Contas. Os posts dela ficam esperando.\n{str(erro)[:200]}",
                          chave=f"reconectar:{conta_id}")
        return
    except Exception:                                 # erro inesperado: nao derruba as outras contas
        resultado["falhas"] += 1
        log.exception("Desempenho: erro inesperado ao ler a conta %d (%s)", conta_id, rede)
        return

    agora_texto = agendador.texto(agora)
    gravados = repositorio.marcos_gravados([p["id"] for p in posts])
    for post in posts:
        lido = numeros.get(post["id_externo"])
        if lido is None:
            repositorio.marcar_removida(post["id"], agora_texto)
            resultado["removidas"] += 1
            log.info("Desempenho: post %d nao existe mais em %s.", post["id"], rede)
            continue
        repositorio.gravar_leitura(post["usuario_id"], post["id"], "atual", lido, agora_texto)
        idade_h = (agora - agendador.momento(post["publicado_em"])) / timedelta(hours=1)
        for nome, horas in MARCOS:
            if horas <= idade_h < horas + TOLERANCIA_H and nome not in gravados[post["id"]]:
                repositorio.gravar_leitura(post["usuario_id"], post["id"], nome, lido, agora_texto)
        resultado["lidas"] += 1


class Coletor(threading.Thread):
    """Thread do painel: le os numeros ao ligar e depois de hora em hora."""

    def __init__(self, intervalo_s: float = INTERVALO_S):
        super().__init__(name="coletor-desempenho", daemon=True)
        self._parar = threading.Event()
        self.intervalo_s = intervalo_s

    def run(self) -> None:
        while not self._parar.is_set():
            try:
                rodar()
            except Exception as erro:            # nunca deixa a thread morrer
                log.error("Coletor de desempenho: erro inesperado: %s", erro)
            self._parar.wait(self.intervalo_s)

    def parar(self) -> None:
        self._parar.set()


if __name__ == "__main__":
    from app import banco
    banco.criar_tabelas()
    r = rodar()
    if r["ocupado"]:
        print("Já existe uma leitura em andamento.")
    else:
        print(f"Posts lidos: {r['lidas']}. Removidos da rede: {r['removidas']}. Contas com falha: {r['falhas']}.")
