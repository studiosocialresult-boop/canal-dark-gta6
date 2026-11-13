"""Cerebro: le a transcricao e escolhe os melhores trechos para virar corte.

As instrucoes da IA ficam em prompts/cerebro.md. Este modulo monta o pedido,
confere a resposta e converte as frases escolhidas em tempos exatos de corte.

Rodar sozinho (gasta credito da API da Anthropic):
    python -m app.cerebro.escolher dados/transcricoes/1.json
"""
import sys
from pathlib import Path

from app import banco, config, ia
from app.contratos import MODOS, CorteProposto, Frase, Transcricao, VideoBaixado

log = config.criar_log("cerebro")

ESQUEMA = {
    "type": "object",
    "properties": {
        "cortes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frase_inicio": {"type": "integer"},
                    "frase_fim": {"type": "integer"},
                    "motivo": {"type": "string"},
                    "nota": {"type": "integer"},
                    "modo": {"type": "string", "enum": list(MODOS)},
                    "titulo": {"type": "string"},
                },
                "required": ["frase_inicio", "frase_fim", "motivo", "nota", "modo", "titulo"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["cortes"],
    "additionalProperties": False,
}

# Videos muito longos sao analisados em partes deste tamanho (cerca de 2 horas de fala).
MAX_CARACTERES_POR_PARTE = 150_000
TOLERANCIA_DURACAO_S = 3.0
TITULO_MAXIMO = 70          # o prompt pede 60; ate 70 passa sem gastar nova tentativa
FOLGA_INICIO_S = 0.15       # respiro antes da primeira palavra
FOLGA_FIM_S = 0.30          # respiro depois da ultima palavra


def escolher_cortes(transcricao: Transcricao, video: VideoBaixado, *,
                    usuario_id: int = config.USUARIO_PADRAO, video_id: int | None = None,
                    cliente=None) -> list[CorteProposto]:
    """Devolve os melhores cortes do video, do melhor para o pior."""
    cortes_min = banco.ler_config(usuario_id, "cortes_min")
    cortes_max = banco.ler_config(usuario_id, "cortes_max")
    duracao_min = banco.ler_config(usuario_id, "duracao_min_s")
    duracao_max = banco.ler_config(usuario_id, "duracao_max_s")

    if not transcricao.frases:
        log.info("O video nao tem fala; nenhum corte para escolher.")
        return []

    sistema = ia.carregar_prompt(
        "cerebro.md", cortes_min=cortes_min, cortes_max=cortes_max,
        duracao_min_s=duracao_min, duracao_max_s=duracao_max,
    )
    frases_por_id = {f.id: f for f in transcricao.frases}
    partes = dividir_em_partes(transcricao.frases)
    candidatos: list[dict] = []

    for numero, frases in enumerate(partes, start=1):
        log.info("Analisando parte %d de %d (%d frases)...", numero, len(partes), len(frases))
        ids_da_parte = {f.id: f for f in frases}
        dados = ia.pedir_json(
            modelo=config.MODELO_CEREBRO,
            esforco=config.ESFORCO_CEREBRO,
            sistema=sistema,
            mensagem=montar_mensagem(video, transcricao, frases, numero, len(partes)),
            esquema=ESQUEMA,
            validar=lambda d, ids=ids_da_parte: validar_cortes(d, ids, duracao_min, duracao_max),
            etapa="cerebro",
            usuario_id=usuario_id,
            video_id=video_id,
            cliente=cliente,
        )
        candidatos.extend(dados["cortes"])

    candidatos.sort(key=lambda c: c["nota"], reverse=True)
    escolhidos = candidatos[:cortes_max]
    cortes = [_converter(c, frases_por_id, transcricao.duracao_s) for c in escolhidos]
    log.info("Cerebro escolheu %d corte(s).", len(cortes))
    return cortes


def dividir_em_partes(frases: list[Frase]) -> list[list[Frase]]:
    """Divide a transcricao em partes de tamanho parecido, sem quebrar frases."""
    total = sum(len(f.texto) for f in frases)
    quantidade = max(1, -(-total // MAX_CARACTERES_POR_PARTE))
    alvo = total / quantidade
    partes: list[list[Frase]] = [[]]
    acumulado = 0
    for frase in frases:
        if acumulado >= alvo and len(partes) < quantidade:
            partes.append([])
            acumulado = 0
        partes[-1].append(frase)
        acumulado += len(frase.texto)
    return partes


def formatar_transcricao(frases: list[Frase]) -> str:
    return "\n".join(f"[{f.id}] ({f.inicio:.1f}-{f.fim:.1f}) {f.texto}" for f in frases)


def montar_mensagem(video: VideoBaixado, transcricao: Transcricao, frases: list[Frase],
                    parte: int, total_partes: int) -> str:
    linhas = [
        "<video>",
        f"Título: {video.titulo}",
        f"Canal: {video.canal}",
        f"Duração total: {transcricao.duracao_s:.0f} segundos",
        f"Idioma da fala: {transcricao.idioma}",
    ]
    if total_partes > 1:
        linhas.append(
            f"Esta é a parte {parte} de {total_partes} do vídeo. Escolha somente entre as frases abaixo."
        )
    linhas += [
        "</video>",
        "",
        "<transcricao>",
        formatar_transcricao(frases),
        "</transcricao>",
        "",
        "Escolha os melhores cortes.",
    ]
    return "\n".join(linhas)


def validar_cortes(dados: dict, frases_por_id: dict[int, Frase],
                   duracao_min: float, duracao_max: float) -> list[str]:
    """Confere a resposta do cerebro. Devolve a lista de problemas (vazia = tudo certo)."""
    problemas: list[str] = []
    validos: list[dict] = []

    for numero, corte in enumerate(dados.get("cortes", []), start=1):
        nome = f"Corte {numero}"
        inicio, fim = corte["frase_inicio"], corte["frase_fim"]
        if inicio not in frases_por_id or fim not in frases_por_id:
            problemas.append(f"{nome}: a frase {inicio} ou a frase {fim} não existe na transcrição.")
            continue
        if inicio > fim:
            problemas.append(f"{nome}: frase_inicio ({inicio}) vem depois de frase_fim ({fim}).")
            continue
        duracao = frases_por_id[fim].fim - frases_por_id[inicio].inicio
        if duracao < duracao_min - TOLERANCIA_DURACAO_S:
            problemas.append(
                f"{nome}: dura {duracao:.0f} s, menos que o mínimo de {duracao_min} s. "
                "Inclua mais frases ou troque de trecho."
            )
        elif duracao > duracao_max + TOLERANCIA_DURACAO_S:
            problemas.append(
                f"{nome}: dura {duracao:.0f} s, mais que o máximo de {duracao_max} s. "
                "Encurte mantendo gancho e desfecho."
            )
        if not 0 <= corte["nota"] <= 100:
            problemas.append(f"{nome}: a nota {corte['nota']} está fora da faixa de 0 a 100.")
        if not corte["titulo"].strip():
            problemas.append(f"{nome}: o título está vazio.")
        elif len(corte["titulo"]) > TITULO_MAXIMO:
            problemas.append(
                f"{nome}: o título tem {len(corte['titulo'])} caracteres; o limite é 60."
            )
        if not corte["motivo"].strip():
            problemas.append(f"{nome}: o motivo está vazio.")
        validos.append(corte)

    ordenados = sorted(validos, key=lambda c: c["frase_inicio"])
    for anterior, seguinte in zip(ordenados, ordenados[1:]):
        if seguinte["frase_inicio"] <= anterior["frase_fim"]:
            problemas.append(
                f"Os cortes das frases {anterior['frase_inicio']}-{anterior['frase_fim']} e "
                f"{seguinte['frase_inicio']}-{seguinte['frase_fim']} se sobrepõem."
            )
    return problemas


def _converter(corte: dict, frases_por_id: dict[int, Frase], duracao_video: float) -> CorteProposto:
    """Transforma as frases escolhidas em tempos exatos, com um pequeno respiro nas pontas."""
    primeira = frases_por_id[corte["frase_inicio"]]
    ultima = frases_por_id[corte["frase_fim"]]
    anterior = frases_por_id.get(primeira.id - 1)
    seguinte = frases_por_id.get(ultima.id + 1)

    inicio = max(primeira.inicio - FOLGA_INICIO_S, anterior.fim if anterior else 0.0)
    fim = min(ultima.fim + FOLGA_FIM_S, seguinte.inicio if seguinte else duracao_video)
    # Se as frases vizinhas encostam (ou os tempos se cruzam), fica o tempo da propria frase.
    inicio = min(inicio, primeira.inicio)
    fim = max(fim, ultima.fim)

    return CorteProposto(
        frase_inicio=primeira.id,
        frase_fim=ultima.id,
        inicio=round(inicio, 3),
        fim=round(fim, 3),
        nota=corte["nota"],
        motivo=corte["motivo"].strip(),
        titulo=corte["titulo"].strip(),
        modo=corte["modo"],
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python -m app.cerebro.escolher caminho/da/transcricao.json")
        sys.exit(1)
    banco.criar_tabelas()
    _transcricao = Transcricao.carregar(Path(sys.argv[1]))
    _video = VideoBaixado("teste", "teste", "", "Vídeo de teste", "Canal de teste",
                          _transcricao.duracao_s, Path(sys.argv[1]))
    try:
        _cortes = escolher_cortes(_transcricao, _video)
    except ia.ErroIA as _erro:
        print("Não deu certo:", _erro)
        sys.exit(1)
    for _corte in _cortes:
        print(f"\nNota {_corte.nota} | {_corte.modo} | {_corte.duracao_s:.0f} s "
              f"| {_corte.inicio:.1f}-{_corte.fim:.1f}")
        print("  Título:", _corte.titulo)
        print("  Motivo:", _corte.motivo)
