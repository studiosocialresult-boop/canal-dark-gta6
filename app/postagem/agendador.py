"""Agendador: decide quando e onde cada video vai, e publica na hora certa.

Regras:
- Por padrao so entra o que foi aprovado no painel (cortes) ou gerado pelo dono (videos de template).
  O modo automatico (desligado por padrao) aprova e agenda sozinho os cortes com nota alta.
- O mesmo conteudo nunca vai duas vezes para a mesma conta, mesmo com frase ou layout diferente
  (chave_video). Variacoes de um mesmo corte sao espalhadas entre contas diferentes.
- Cada conta posta no seu ritmo (posts por dia), dentro da janela de horario, espaçado por igual e
  nunca com menos que o intervalo minimo entre dois posts da mesma conta (o que nao couber vai para o dia seguinte).
- Falha temporaria (rede fora do ar, limite) tenta de novo mais tarde; acesso vencido marca a conta
  para conectar de novo; erro definitivo marca a publicacao como falha, com o motivo.
- TikTok nunca e agendado pelo modo automatico: as regras dele exigem escolha e confirmacao do dono.
"""
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app import avisos, banco, config, ia
from app.multiplicador import renderizar, repositorio
from app.postagem import contas, legenda, meta, tiktok, youtube
from app.postagem.cofre import ErroCofre
from app.postagem.redes import REDES, ErroPostagem

log = config.criar_log("agendador")

FORMATO = "%Y-%m-%d %H:%M:%S"
CONECTORES = {"youtube": youtube.publicar, "instagram": meta.publicar_instagram,
              "facebook": meta.publicar_facebook, "tiktok": tiktok.publicar}
ESPERAS_S = (300, 1200, 3600)        # novas tentativas: 5 min, 20 min, 1 h
MAX_TENTATIVAS = len(ESPERAS_S)
MARGEM_MIN = 10                      # o primeiro horario livre fica pelo menos 10 min no futuro
DIAS_A_FRENTE = 90


class ErroAgenda(Exception):
    """Pedido de agendamento invalido (a mensagem e para o dono)."""


# ---------- horario ----------

def agora() -> datetime:
    return datetime.now(timezone.utc)


def texto(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).strftime(FORMATO)


def momento(texto_utc: str) -> datetime:
    return datetime.strptime(texto_utc, FORMATO).replace(tzinfo=timezone.utc)


def _fuso() -> ZoneInfo:
    return ZoneInfo(config.FUSO)


def horarios_do_dia(dia: date, por_dia: int, inicio_h: int, fim_h: int) -> list[datetime]:
    """Horarios (UTC) de um dia, espacados por igual dentro da janela local."""
    por_dia = max(1, por_dia)
    abertura = datetime(dia.year, dia.month, dia.day, inicio_h, tzinfo=_fuso())
    passo = (fim_h - inicio_h) * 60 / por_dia
    # arredondado para multiplos de 5 minutos (fica mais natural: 10:35 em vez de 10:37)
    return [(abertura + timedelta(minutes=round(passo * (k + 0.5) / 5) * 5)).astimezone(timezone.utc)
            for k in range(por_dia)]


def proximos_horarios(conta: dict, quantidade: int, usuario_id: int, reservados: set[str] | None = None,
                      depois_de: datetime | None = None) -> list[datetime]:
    """Os proximos `quantidade` horarios livres da conta, no ritmo dela."""
    inicio_h, fim_h = banco.ler_config(usuario_id, "janela_inicio"), banco.ler_config(usuario_id, "janela_fim")
    if not 0 <= inicio_h < fim_h <= 24:
        inicio_h, fim_h = 9, 22
    passo = timedelta(minutes=(fim_h - inicio_h) * 60 / max(1, conta["posts_por_dia"]))
    # distancia minima de qualquer outro post da conta: meio passo ou o intervalo minimo, o que for maior
    folga = max(passo / 2, timedelta(minutes=banco.ler_config(usuario_id, "intervalo_minimo_min")))
    ocupados = [momento(t) for t in contas.horarios_ocupados(conta["id"])] + [momento(t) for t in (reservados or set())]
    minimo = (depois_de or agora()) + timedelta(minutes=MARGEM_MIN)
    livres = []
    dia = minimo.astimezone(_fuso()).date()
    for _ in range(DIAS_A_FRENTE):
        for horario in horarios_do_dia(dia, conta["posts_por_dia"], inicio_h, fim_h):
            if horario < minimo or any(abs(horario - o) < folga for o in ocupados):
                continue
            livres.append(horario)
            ocupados.append(horario)
            if len(livres) == quantidade:
                return livres
        dia += timedelta(days=1)
    return livres


# ---------- o que pode ser publicado ----------

def item_de_corte(corte_id: int, usuario_id: int, exigir_aprovado: bool = True) -> dict:
    corte = banco.ler_corte(corte_id)
    if corte is None or corte["usuario_id"] != usuario_id:
        raise ErroAgenda("Corte não encontrado.")
    if exigir_aprovado and corte["estado"] != "aprovado":
        raise ErroAgenda("Só cortes aprovados podem ser agendados. Aprove o corte na tela Cortes.")
    if not corte["caminho_arquivo"] or not config.caminho_absoluto(corte["caminho_arquivo"]).exists():
        raise ErroAgenda("O arquivo deste corte não existe mais.")
    video = banco.ler_video(corte["video_id"])
    return {"origem": "corte", "corte_id": corte_id, "saida_id": None, "arquivo": corte["caminho_arquivo"],
            "chave_video": f"corte:{corte_id}", "titulo": corte["titulo"], "motivo": corte["motivo"],
            "frase": "", "video_id": corte["video_id"],
            "credito": legenda.credito(video["titulo"] or "", video["canal"] or "", video["url"])}


def item_de_saida(saida_id: int, usuario_id: int) -> dict:
    saida = repositorio.ler_saida(saida_id)
    template = repositorio.ler_template(saida["template_id"]) if saida else None
    if saida is None or template is None or template["usuario_id"] != usuario_id:
        raise ErroAgenda("Vídeo não encontrado.")
    if saida["estado"] != "pronto" or not saida["arquivo"]:
        raise ErroAgenda("Este vídeo ainda não foi gerado.")
    midia = repositorio.ler_midia(saida["midia_id"])
    frase = repositorio.ler_frase(saida["frase_id"])["texto"]
    credito, chave, motivo, titulo, video_id = "", f"arquivo:{midia['arquivo']}", "", frase, None
    if midia["origem"] == "corte":
        base = item_de_corte(midia["corte_id"], usuario_id, exigir_aprovado=False)
        chave, credito, motivo, titulo, video_id = base["chave_video"], base["credito"], base["motivo"], base["titulo"], base["video_id"]
    elif midia["origem"] == "perfil":
        item = next((b for b in repositorio.listar_biblioteca(usuario_id) if b["arquivo"] == midia["arquivo"]), None)
        if item:
            chave = f"video:{item['plataforma']}:{item['id_externo']}"
            credito = legenda.credito(item["titulo"] or "", item["canal"] or "", item["url"])
    if frase == "-":
        frase = ""
    return {"origem": "template", "corte_id": midia.get("corte_id"), "saida_id": saida_id, "arquivo": saida["arquivo"],
            "chave_video": chave, "titulo": frase or titulo or template["nome"], "motivo": motivo, "frase": frase,
            "video_id": video_id, "credito": credito}


# ---------- agendar ----------

def _contas_validas(usuario_id: int, conta_ids: list[int]) -> list[dict]:
    escolhidas = []
    for conta_id in conta_ids:
        conta = contas.ler_conta(int(conta_id))
        if conta is None or conta["usuario_id"] != usuario_id:
            raise ErroAgenda("Conta não encontrada.")
        if not conta["ativa"] or conta["estado"] != "conectada":
            raise ErroAgenda(f"A conta {conta['nome']} está pausada ou precisa ser conectada de novo.")
        escolhidas.append(conta)
    if not escolhidas:
        raise ErroAgenda("Escolha pelo menos uma conta.")
    return escolhidas


def _textos(item: dict, usuario_id: int, cache: dict) -> dict:
    """Titulo, descricao e hashtags do item (uma chamada de IA por item; sem IA, uma versao simples)."""
    if item["chave_video"] + item.get("frase", "") not in cache:
        try:
            dados = legenda.escrever(titulo=item["titulo"], motivo=item["motivo"], frase_na_tela=item["frase"],
                                     usuario_id=usuario_id, video_id=item.get("video_id"))
        except ia.ErroIA as erro:
            log.warning("Legenda sem IA (%s): %s", item["titulo"], erro)
            dados = legenda.sem_ia(item["titulo"])
        cache[item["chave_video"] + item.get("frase", "")] = dados
    return cache[item["chave_video"] + item.get("frase", "")]


def agendar(usuario_id: int, itens: list[dict], conta_ids: list[int], *, horario: datetime | None = None,
            distribuir: bool = False, opcoes_por_rede: dict | None = None, textos_prontos: dict | None = None) -> dict:
    """Cria as publicacoes. Devolve {"criadas": [...], "puladas": [{"titulo", "conta", "motivo"}]}.

    horario: um horario fixo (UTC) para todas; sem ele, cada conta usa os proximos horarios livres.
    distribuir: cada item vai para UMA conta (a que ainda nao tem esse conteudo e esta mais livre).
    textos_prontos: {"titulo", "descricao", "hashtags"} editados pelo dono (vale para todos os itens).
    """
    contas_ok = _contas_validas(usuario_id, conta_ids)
    opcoes_por_rede = opcoes_por_rede or {}
    if any(c["rede"] == "tiktok" for c in contas_ok):
        tiktok_opcoes = opcoes_por_rede.get("tiktok") or {}
        if tiktok_opcoes.get("privacidade") not in tiktok.PRIVACIDADES or not tiktok_opcoes.get("confirmado"):
            raise ErroAgenda("Para o TikTok, escolha a privacidade e confirme o envio.")
    if horario is not None and horario < agora() + timedelta(minutes=1):
        raise ErroAgenda("Escolha um horário no futuro.")

    usadas = {c["id"]: contas.chaves_usadas(c["id"]) for c in contas_ok}
    carga = {c["id"]: 0 for c in contas_ok}
    destinos: dict[int, list[dict]] = {c["id"]: [] for c in contas_ok}
    puladas = []
    for item in itens:
        duracao = renderizar.duracao_do_arquivo(config.caminho_absoluto(item["arquivo"]))
        candidatas, motivos = [], []
        for conta in contas_ok:
            limites = REDES[conta["rede"]]
            if item["chave_video"] in usadas[conta["id"]]:
                motivos.append({"titulo": item["titulo"], "conta": conta["nome"],
                                "motivo": "esse conteúdo já foi (ou será) publicado nesta conta"})
            elif not limites["duracao_min_s"] <= duracao <= limites["duracao_max_s"] + 0.5:
                motivos.append({"titulo": item["titulo"], "conta": conta["nome"],
                                "motivo": f"{limites['nome']} aceita vídeos de {limites['duracao_min_s']} a "
                                          f"{limites['duracao_max_s']} s (este tem {duracao:.0f} s)"})
            else:
                candidatas.append(conta)
        if distribuir and candidatas:
            # espalhando: o video vai para UMA conta; as outras nao sao "puladas", so nao foram a escolhida
            candidatas = [min(candidatas, key=lambda c: (carga[c["id"]], c["id"]))]
        elif distribuir:
            # nao coube em nenhuma conta: um aviso so, com os motivos sem repetir
            puladas.append({"titulo": item["titulo"], "conta": "todas as contas escolhidas",
                            "motivo": "; ".join(dict.fromkeys(m["motivo"] for m in motivos))})
        else:
            puladas.extend(motivos)
        for conta in candidatas:
            destinos[conta["id"]].append(item)
            usadas[conta["id"]].add(item["chave_video"])
            carga[conta["id"]] += 1

    cache_textos: dict = {}
    criadas = []
    for conta in contas_ok:
        lista = destinos[conta["id"]]
        if not lista:
            continue
        horarios = [horario] * len(lista) if horario else proximos_horarios(conta, len(lista), usuario_id)
        for item, quando in zip(lista, horarios):
            dados = textos_prontos or _textos(item, usuario_id, cache_textos)
            titulo, texto_post = legenda.montar(dados, item["credito"], conta["rede"])
            try:
                publicacao_id = contas.criar_publicacao(
                    usuario_id, conta["id"], origem=item["origem"], corte_id=item["corte_id"], saida_id=item["saida_id"],
                    arquivo=item["arquivo"], chave_video=item["chave_video"], titulo=titulo, legenda=texto_post,
                    opcoes=opcoes_por_rede.get(conta["rede"], {}), agendada_para=texto(quando))
            except sqlite3.IntegrityError:
                puladas.append({"titulo": item["titulo"], "conta": conta["nome"], "motivo": "já estava agendado"})
                continue
            criadas.append({"id": publicacao_id, "conta": conta["nome"], "rede": conta["rede"], "quando": texto(quando)})
        if len(horarios) < len(lista):
            for item in lista[len(horarios):]:
                puladas.append({"titulo": item["titulo"], "conta": conta["nome"], "motivo": "sem horário livre nos próximos 90 dias"})
    log.info("Agendadas %d publicações (%d puladas).", len(criadas), len(puladas))
    return {"criadas": criadas, "puladas": puladas}


# ---------- publicar ----------

def publicar_uma(publicacao: dict, momento_agora: datetime | None = None) -> str:
    """Publica uma publicacao agora. Devolve o estado final."""
    agora_texto = texto(momento_agora or agora())
    conta = contas.ler_conta(publicacao["conta_id"])
    rede = conta["rede"]
    if contas.publicadas_nas_ultimas_24h(conta["id"], agora_texto) >= REDES[rede]["limite_diario"]:
        contas.atualizar_publicacao(publicacao["id"], proxima_tentativa=texto((momento_agora or agora()) + timedelta(hours=1)),
                                    erro=f"Limite diário de {REDES[rede]['nome']} atingido; tento de novo em 1 hora.")
        return "agendada"
    arquivo = config.caminho_absoluto(publicacao["arquivo"])
    if not arquivo.exists():
        contas.atualizar_publicacao(publicacao["id"], estado="falhou", erro="O arquivo do vídeo não existe mais.")
        return "falhou"
    contas.atualizar_publicacao(publicacao["id"], estado="publicando", erro=None)
    log.info("Publicando %d em %s (%s)...", publicacao["id"], conta["nome"], rede)
    try:
        credenciais = contas.credenciais_da_conta(conta["id"])
        try:
            resultado = CONECTORES[rede](credenciais, arquivo, publicacao["titulo"], publicacao["legenda"],
                                         publicacao["opcoes"])
        finally:
            if credenciais.mudou:                 # token renovado no caminho: guarda o novo
                contas.regravar_credenciais(conta["id"], credenciais)
    except ErroCofre as erro:
        contas.atualizar_conta(conta["id"], estado="expirada", erro=str(erro))
        contas.atualizar_publicacao(publicacao["id"], estado="agendada", erro=str(erro))
        return "agendada"
    except ErroPostagem as erro:
        return _tratar_falha(publicacao, conta, erro, momento_agora)
    except Exception as erro:                    # erro inesperado: trata como temporario
        log.exception("Erro inesperado ao publicar %d", publicacao["id"])
        return _tratar_falha(publicacao, conta, ErroPostagem(f"Erro inesperado: {erro}", temporario=True), momento_agora)
    contas.atualizar_publicacao(publicacao["id"], estado="publicada", id_externo=resultado.id_externo, url=resultado.url,
                                erro=resultado.observacao, publicado_em=agora_texto)
    log.info("Publicado %d: %s", publicacao["id"], resultado.url or resultado.id_externo)
    return "publicada"


def _tratar_falha(publicacao: dict, conta: dict, erro: ErroPostagem, momento_agora: datetime | None) -> str:
    log.warning("Falha ao publicar %d: %s", publicacao["id"], erro)
    if erro.reconectar:
        contas.atualizar_conta(conta["id"], estado="expirada", erro=str(erro))
        contas.atualizar_publicacao(publicacao["id"], estado="agendada", erro=str(erro))
        avisos.avisar(f"🔌 A conta {conta['nome']} ({REDES[conta['rede']]['nome']}) precisa ser conectada de novo "
                      f"na tela Contas. Os posts dela ficam esperando.\n{str(erro)[:200]}", chave=f"reconectar:{conta['id']}")
        return "agendada"
    tentativas = publicacao["tentativas"] + 1
    if erro.temporario and tentativas < MAX_TENTATIVAS + 1:
        espera = ESPERAS_S[min(tentativas - 1, len(ESPERAS_S) - 1)]
        contas.atualizar_publicacao(publicacao["id"], estado="agendada", tentativas=tentativas, erro=str(erro),
                                    proxima_tentativa=texto((momento_agora or agora()) + timedelta(seconds=espera)))
        return "agendada"
    contas.atualizar_publicacao(publicacao["id"], estado="falhou", tentativas=tentativas, erro=str(erro))
    avisos.avisar(f"❌ Um post não saiu em {conta['nome']} ({REDES[conta['rede']]['nome']}): "
                  f"{publicacao['titulo'][:100]}\n{str(erro)[:250]}\nVeja na tela Agenda.", chave=f"post:{publicacao['id']}")
    return "falhou"


def publicar_vencidas(momento_agora: datetime | None = None) -> int:
    """Publica tudo o que ja passou da hora. Devolve quantas tentou."""
    vencidas = contas.publicacoes_vencidas(texto(momento_agora or agora()))
    for publicacao in vencidas:
        publicar_uma(publicacao, momento_agora)
    return len(vencidas)


# ---------- modo automatico ----------

def rodar_modo_automatico(usuario_id: int) -> int:
    """Se ligado: aprova os cortes prontos com nota alta e agenda nas contas que aceitam automatico."""
    if not banco.ler_config(usuario_id, "modo_automatico"):
        return 0
    nota_minima = banco.ler_config(usuario_id, "nota_minima_automatico")
    contas_auto = [c["id"] for c in contas.listar_contas(usuario_id)
                   if c["ativa"] and c["estado"] == "conectada" and REDES[c["rede"]]["automatico"]]
    if not contas_auto:
        return 0
    agendados = 0
    for linha in banco.listar_cortes(usuario_id):
        if linha["estado"] != "renderizado" or linha["nota"] < nota_minima:
            continue
        banco.atualizar_corte(linha["id"], estado="aprovado")
        try:
            resultado = agendar(usuario_id, [item_de_corte(linha["id"], usuario_id)], contas_auto)
            agendados += len(resultado["criadas"])
        except (ErroAgenda, renderizar.ErroRender) as erro:
            log.warning("Modo automatico: corte %d nao agendado: %s", linha["id"], erro)
    return agendados


class Publicador(threading.Thread):
    """Thread do painel: a cada meio minuto publica o que venceu e roda o modo automatico."""

    def __init__(self, intervalo_s: float = 30):
        super().__init__(name="publicador", daemon=True)
        self._parar = threading.Event()
        self.intervalo_s = intervalo_s

    def run(self) -> None:
        contas.retomar_publicacoes_interrompidas()
        while not self._parar.is_set():
            try:
                rodar_modo_automatico(config.USUARIO_PADRAO)
                publicar_vencidas()
            except Exception as erro:            # nunca deixa a thread morrer
                log.error("Publicador: erro inesperado: %s", erro)
                avisos.avisar(f"⚠️ Erro inesperado no publicador: {str(erro)[:300]}", chave="publicador-inesperado")
            self._parar.wait(self.intervalo_s)

    def parar(self) -> None:
        self._parar.set()
