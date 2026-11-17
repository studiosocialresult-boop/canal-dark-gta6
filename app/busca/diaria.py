"""Busca diaria: acha os videos de GTA 6 que mais crescem e manda os melhores para a fila.

Criterio: muitas visualizacoes em pouco tempo. Entram so videos postados nas ultimas
`busca_janela_h` horas (padrao 48). Para cada um calcula a velocidade (views por hora) e,
se o video ja apareceu em uma busca anterior, a aceleracao (views ganhas por hora desde
entao). Ordena pela velocidade, descarta o que ja foi processado e enfileira os primeiros
ate a meta de cortes do dia. Nao precisa de chave de API: usa o yt-dlp.

Rodar sozinho (so mostra o ranking, nao enfileira nada):
    python -m app.busca.diaria
"""
import json
import math
import re
import sys
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import avisos, banco, config
from app.busca import perfil

log = config.criar_log("busca")

# Consultas em ingles e portugues. "semana" = enviados nesta semana, ordenados por visualizacoes.
# As CONSULTAS_HOJE primeiras tambem sao buscadas com o filtro "hoje" (no lancamento, o dia muda rapido).
CONSULTAS = ["GTA 6", "GTA VI", "GTA 6 gameplay", "GTA 6 notícias", "GTA 6 novidades", "GTA 6 trailer",
             # com o jogo lancado (19/11/2026), o assunto passa a ser o que se faz dentro dele
             "GTA 6 dicas", "GTA 6 segredos", "GTA 6 detalhes", "GTA 6 easter eggs", "GTA 6 análise", "GTA 6 review",
             "GTA 6 em português", "GTA 6 PT-BR"]
CONSULTAS_HOJE = 3
FILTRO_SEMANA = "CAMSBAgDEAE%253D"       # ordenar por visualizacoes + enviados esta semana + so videos
FILTRO_HOJE = "CAMSBAgCEAE%253D"         # ordenar por visualizacoes + enviados hoje + so videos
POR_CONSULTA = 15
MAX_COM_DATA = 60                        # a data de cada video e uma consulta; limita o trabalho
DURACAO_MAX_S = 45 * 60                  # videos mais longos custam caro para baixar e transcrever
DURACAO_MIN_S = 40
TITULO_GTA = re.compile(r"(gta|grand theft auto)\s*(6|vi)\b", re.IGNORECASE)    # GTA 6 / GTA VI (nao o GTA V)
# Titulos que anunciam o final ou as cenas da historia em sequencia. A Rockstar manda remover esse tipo
# de video (politica oficial de material protegido), entao ele nem vai para a fila: economiza IA e evita
# advertencia no canal.
TITULO_SPOILER = re.compile(
    r"\b(ending|final do jogo|final da hist[oó]ria|final explicado|all cutscenes|todas as cutscenes|"
    r"game movie|filme completo)\b", re.IGNORECASE)
# Videos de canais brasileiros vem primeiro na fila (o audio original ja sai em portugues).
# O YouTube nao diz o pais do canal na busca, entao o sinal e o titulo: letras e palavras que so o
# portugues usa (evita confundir com espanhol, que divide muitas palavras curtas).
LETRAS_PT = re.compile(r"[ãõçêôà]", re.IGNORECASE)
PALAVRAS_PT = re.compile(
    r"\b(é|pré|tem|t[aá]|galera|mano|vou|fui|pt-?br|ao vivo|brasil|baixando|dublado|n[aã]o|voc[eê]s?|s[aã]o|pra|tamb[eé]m|at[eé]|ningu[eé]m|muito|muita|mais|novo|nova|novos|novas|"
    r"jogo|jogando|jogar|coisas?|isso|isto|vazou|vazaram|vazamento|chegou|finalmente|primeira|primeiro|"
    r"melhores?|detalhes|segredos|dicas|not[ií]cias|novidades|an[aá]lise|olha|olhem|incr[ií]vel|"
    r"ningu[eé]m|ainda|agora|aqui|tudo|todos|ser[aá]|vai|vem|fiz|fizeram|achei|testei)\b", re.IGNORECASE)
REGIAO_BUSCA = "&hl=pt-BR&gl=BR"         # pede ao YouTube os resultados como se fosse do Brasil


def parece_brasileiro(titulo: str) -> bool:
    """Verdadeiro se o titulo parece estar em portugues."""
    titulo = titulo or ""
    return bool(LETRAS_PT.search(titulo) or PALAVRAS_PT.search(titulo))


MAX_TENTATIVAS_POR_DIA = 3
ESPERA_ENTRE_TENTATIVAS = timedelta(minutes=30)


def _fuso() -> ZoneInfo:
    return ZoneInfo(config.FUSO)


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _texto_utc(quando: datetime) -> str:
    return quando.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _de_texto_utc(texto: str) -> datetime:
    return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


# ---------- coleta ----------

def _buscar_no_youtube(consulta: str, filtro: str) -> list[dict]:
    """Resultados de uma pesquisa do YouTube (id, titulo, canal, views, duracao). Falha vira lista vazia."""
    endereco = f"https://www.youtube.com/results?search_query={consulta.replace(' ', '+')}&sp={filtro}{REGIAO_BUSCA}"
    try:
        saida = perfil._yt_dlp(["--flat-playlist", "--playlist-end", str(POR_CONSULTA), "-J", endereco])
        dados = json.loads(saida[saida.index("{"):])
    except (perfil.ErroPerfil, ValueError) as erro:
        log.warning("Busca '%s' falhou: %s", consulta, erro)
        return []
    achados = []
    for e in dados.get("entries", []):
        if not e or not e.get("id") or len(e["id"]) != 11:
            continue
        achados.append({"id_externo": e["id"], "titulo": e.get("title") or "", "canal": e.get("channel") or e.get("uploader") or "",
                        "views": e.get("view_count"), "duracao_s": e.get("duration"), "origem": "busca"})
    return achados


def coletar_busca() -> list[dict]:
    """Junta os resultados de todas as consultas, sem repetir, ja com a data de postagem."""
    unicos: dict[str, dict] = {}
    pedidos = [(c, FILTRO_SEMANA) for c in CONSULTAS] + [(c, FILTRO_HOJE) for c in CONSULTAS[:CONSULTAS_HOJE]]
    for consulta, filtro in pedidos:
        for item in _buscar_no_youtube(consulta, filtro):
            if TITULO_GTA.search(item["titulo"]):
                unicos.setdefault(item["id_externo"], item)
    ordenados = sorted(unicos.values(), key=lambda i: -(i["views"] or 0))[:MAX_COM_DATA]
    datas = perfil._datas([i["id_externo"] for i in ordenados])
    for item in ordenados:
        item["publicado"] = datas.get(item["id_externo"])
    return ordenados


def coletar_canais(usuario_id: int) -> list[dict]:
    """Os videos recentes dos canais acompanhados (tela Hoje)."""
    achados = []
    for canal in listar_canais(usuario_id):
        try:
            resposta = perfil.listar(canal["url"], "videos", limite=15)
        except perfil.ErroPerfil as erro:
            log.warning("Canal %s nao pode ser lido: %s", canal["nome"], erro)
            continue
        for p in resposta["posts"]:
            achados.append({"id_externo": p["id"], "titulo": p["titulo"], "canal": resposta["canal"]["nome"],
                            "views": p["views"], "duracao_s": p["duracao_s"], "publicado": p["publicado"],
                            "origem": "canal"})
    return achados


# ---------- ranking ----------

def montar_ranking(candidatos: list[dict], janela_h: float, agora: datetime | None = None) -> list[dict]:
    """Calcula horas e velocidade, tira os fora da janela e ordena: primeiro os brasileiros, depois
    os de fora, cada grupo dos que mais crescem para os que menos crescem."""
    agora = agora or _agora_utc()
    unicos: dict[str, dict] = {}
    for c in candidatos:
        if not c.get("publicado") or not c.get("views"):
            continue
        try:
            quando = datetime.fromisoformat(c["publicado"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if quando.tzinfo is None:
            quando = quando.replace(tzinfo=timezone.utc)
        horas = (agora - quando).total_seconds() / 3600
        if horas > janela_h or horas < 0:
            continue
        item = dict(c, horas=round(max(horas, 0), 1),
                    velocidade=perfil.velocidade(c["views"], c["publicado"], agora),
                    brasileiro=parece_brasileiro(c.get("titulo")))
        antigo = unicos.get(c["id_externo"])
        if antigo is None or (item["origem"] == "canal" and antigo["origem"] != "canal"):
            unicos[c["id_externo"]] = item
    return sorted(unicos.values(), key=lambda i: (not i["brasileiro"], -(i["velocidade"] or 0)))


def _aceleracao(usuario_id: int, item: dict, agora: datetime) -> float | None:
    """Views ganhas por hora desde a ultima vez que o video apareceu em uma busca anterior."""
    with closing(banco.conectar()) as conexao:
        antes = conexao.execute(
            "SELECT views, coletado_em FROM ranking WHERE usuario_id = ? AND id_externo = ? "
            "ORDER BY coletado_em DESC LIMIT 1", (usuario_id, item["id_externo"])).fetchone()
    if antes is None or antes["views"] is None:
        return None
    horas = (agora - _de_texto_utc(antes["coletado_em"])).total_seconds() / 3600
    if horas < 1:
        return None
    return round((item["views"] - antes["views"]) / horas, 1)


# ---------- canais acompanhados ----------

def listar_canais(usuario_id: int) -> list[dict]:
    with closing(banco.conectar()) as conexao:
        return [dict(l) for l in conexao.execute(
            "SELECT * FROM canais_monitorados WHERE usuario_id = ? ORDER BY id", (usuario_id,))]


def adicionar_canal(usuario_id: int, texto: str) -> dict:
    """Confere o canal (precisa existir no YouTube) e passa a acompanhar. Levanta ErroPerfil se nao der."""
    base = perfil.normalizar_alvo(texto)
    resposta = perfil.listar(base, "videos", limite=3)
    nome = resposta["canal"]["nome"]
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute("INSERT OR IGNORE INTO canais_monitorados (usuario_id, url, nome) VALUES (?, ?, ?)",
                        (usuario_id, base, nome))
        linha = conexao.execute("SELECT * FROM canais_monitorados WHERE usuario_id = ? AND url = ?",
                                (usuario_id, base)).fetchone()
    return dict(linha)


def remover_canal(usuario_id: int, canal_id: int) -> bool:
    with closing(banco.conectar()) as conexao, conexao:
        return conexao.execute("DELETE FROM canais_monitorados WHERE id = ? AND usuario_id = ?",
                               (canal_id, usuario_id)).rowcount > 0


# ---------- execucao ----------

def meta_de_cortes(usuario_id: int) -> int:
    """Quantos cortes novos por dia a busca tenta gerar.

    Com o modo automatico ligado, o dobro das vagas do dia nas contas (sobra para a escalacao escolher os
    melhores), sem passar de `meta_cortes_dia`. Produzir muito mais do que cabe nas contas so gasta IA e voz."""
    meta = banco.ler_config(usuario_id, "meta_cortes_dia")
    if banco.ler_config(usuario_id, "modo_automatico"):
        from app.postagem import escalacao          # aqui dentro: evita carregar a postagem so para a busca
        vagas = escalacao.vagas_por_dia(usuario_id)
        if vagas:
            meta = min(meta, 2 * vagas)
    return meta


def videos_para_a_meta(usuario_id: int, dia: str) -> int:
    """Quantos videos ainda faltam enfileirar hoje para chegar na meta de cortes."""
    meta_cortes = meta_de_cortes(usuario_id)
    media = (banco.ler_config(usuario_id, "cortes_min") + banco.ler_config(usuario_id, "cortes_max")) / 2
    total = math.ceil(meta_cortes / max(media, 1))
    with closing(banco.conectar()) as conexao:
        feitos = conexao.execute(
            "SELECT COUNT(DISTINCT id_externo) FROM ranking WHERE usuario_id = ? AND dia = ? AND destino = 'enfileirado'",
            (usuario_id, dia)).fetchone()[0]
    return max(total - feitos, 0)


def _motivo_de_descarte(item: dict, usuario_id: int) -> tuple[str, str] | None:
    """(destino, motivo) se o video nao deve ser processado; None se pode."""
    if banco.buscar_video(usuario_id, "youtube", item["id_externo"]) is not None:
        return "ja_processado", "Já foi processado antes"
    if TITULO_SPOILER.search(item.get("titulo") or ""):
        return "ignorado", "O título indica spoiler da história"
    duracao = item.get("duracao_s")
    if duracao and duracao > DURACAO_MAX_S:
        return "ignorado", f"Longo demais ({int(duracao // 60)} min)"
    if duracao and duracao < DURACAO_MIN_S:
        return "ignorado", "Curto demais para virar corte"
    return None


def rodar(usuario_id: int = config.USUARIO_PADRAO, enfileirar: bool = True,
          coletor=None, agora: datetime | None = None) -> dict:
    """Faz uma busca completa, grava o ranking e (se `enfileirar`) manda os melhores para a fila.

    `coletor` existe so para os testes: funcao que devolve a lista de candidatos."""
    agora = agora or _agora_utc()
    dia = agora.astimezone(_fuso()).strftime("%Y-%m-%d")
    with closing(banco.conectar()) as conexao, conexao:
        busca_id = conexao.execute("INSERT INTO buscas (usuario_id, dia, iniciada_em) VALUES (?, ?, ?)",
                                   (usuario_id, dia, _texto_utc(agora))).lastrowid
    try:
        janela = banco.ler_config(usuario_id, "busca_janela_h")
        candidatos = coletor() if coletor else coletar_busca() + coletar_canais(usuario_id)
        ranking = montar_ranking(candidatos, janela, agora)
        if not ranking:
            if candidatos and not any(c.get("publicado") for c in candidatos):
                raise RuntimeError(f"A busca achou {len(candidatos)} vídeos, mas o YouTube escondeu as datas de "
                                   "postagem (pediu login). O cookies.txt provavelmente venceu: exporte de novo e "
                                   "use o trocar_cookies_vps.bat.")
            raise RuntimeError("Não encontrei nenhum vídeo recente. O YouTube pode ter recusado a busca; "
                               "confira o cookies.txt e tente de novo.")
        faltam = videos_para_a_meta(usuario_id, dia) if enfileirar else 0
        enfileirados = 0
        linhas = []
        for posicao, item in enumerate(ranking, start=1):
            item["aceleracao"] = _aceleracao(usuario_id, item, agora)
            descarte = _motivo_de_descarte(item, usuario_id)
            url = f"https://www.youtube.com/watch?v={item['id_externo']}"
            if descarte:
                destino, motivo = descarte
            elif enfileirar and enfileirados < faltam and not banco.item_na_fila(usuario_id, "link", url):
                banco.enfileirar(usuario_id, "link", url, item["titulo"] or url)
                destino, motivo = "enfileirado", "Foi para a fila de cortes"
                enfileirados += 1
            else:
                destino, motivo = "fora_da_meta", "Ficou de fora da meta de hoje"
            linhas.append((usuario_id, busca_id, dia, "youtube", item["id_externo"], url, item["titulo"], item["canal"],
                           item.get("duracao_s"), item["views"], item["publicado"], item["horas"], item["velocidade"],
                           item["aceleracao"], item["origem"], posicao, destino, motivo, _texto_utc(agora)))
        with closing(banco.conectar()) as conexao, conexao:
            conexao.executemany(
                "INSERT INTO ranking (usuario_id, busca_id, dia, plataforma, id_externo, url, titulo, canal, duracao_s, views, "
                "publicado, horas, velocidade, aceleracao, origem, posicao, destino, motivo, coletado_em) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", linhas)
            resumo = f"{len(ranking)} vídeos no ranking, {enfileirados} enviados para a fila"
            conexao.execute("UPDATE buscas SET estado = 'pronta', terminada_em = ?, resumo = ? WHERE id = ?",
                            (_texto_utc(_agora_utc()), resumo, busca_id))
        log.info("Busca %d: %s.", busca_id, resumo)
    except Exception as erro:
        log.error("Busca %d falhou: %s", busca_id, erro)
        avisos.avisar(f"❌ A busca de vídeos falhou: {str(erro)[:300]}", chave=f"busca:{dia}")
        with closing(banco.conectar()) as conexao, conexao:
            conexao.execute("UPDATE buscas SET estado = 'falhou', terminada_em = ?, erro = ? WHERE id = ?",
                            (_texto_utc(_agora_utc()), str(erro)[:300], busca_id))
        raise
    return {"busca_id": busca_id, "ranking": len(ranking), "enfileirados": enfileirados}


# ---------- consulta (tela Hoje) ----------

def ultima_busca(usuario_id: int):
    with closing(banco.conectar()) as conexao:
        return conexao.execute("SELECT * FROM buscas WHERE usuario_id = ? ORDER BY id DESC LIMIT 1",
                               (usuario_id,)).fetchone()


def ranking_da_busca(busca_id: int) -> list[dict]:
    with closing(banco.conectar()) as conexao:
        return [dict(l) for l in conexao.execute(
            "SELECT * FROM ranking WHERE busca_id = ? ORDER BY posicao", (busca_id,))]


def ranking_atual(usuario_id: int) -> tuple[dict | None, list[dict]]:
    """A ultima busca que terminou bem e o ranking dela."""
    with closing(banco.conectar()) as conexao:
        busca = conexao.execute(
            "SELECT * FROM buscas WHERE usuario_id = ? AND estado = 'pronta' ORDER BY id DESC LIMIT 1",
            (usuario_id,)).fetchone()
    return (dict(busca), ranking_da_busca(busca["id"])) if busca else (None, [])


def historico(usuario_id: int, limite: int = 7) -> list[dict]:
    with closing(banco.conectar()) as conexao:
        return [dict(l) for l in conexao.execute(
            "SELECT * FROM buscas WHERE usuario_id = ? ORDER BY id DESC LIMIT ?", (usuario_id, limite))]


# ---------- limpeza do disco ----------

def limpar_brutos(usuario_id: int, agora: datetime | None = None) -> int:
    """Apaga os videos baixados mais velhos que `apagar_brutos_dias`. Cortes e registros ficam
    (se um corte precisar do original de novo, ele e baixado outra vez). Devolve quantos apagou."""
    limite = (agora or _agora_utc()) - timedelta(days=banco.ler_config(usuario_id, "apagar_brutos_dias"))
    apagados = 0
    with closing(banco.conectar()) as conexao:
        videos = conexao.execute(
            "SELECT id, caminho_arquivo FROM videos WHERE usuario_id = ? AND caminho_arquivo IS NOT NULL "
            "AND estado IN ('pronto', 'falhou')", (usuario_id,)).fetchall()
    for v in videos:
        arquivo = config.caminho_absoluto(v["caminho_arquivo"])
        if not arquivo.exists():
            continue
        if datetime.fromtimestamp(arquivo.stat().st_mtime, timezone.utc) > limite:
            continue
        try:
            arquivo.unlink()
        except OSError as erro:
            log.warning("Nao consegui apagar %s: %s", arquivo.name, erro)
            continue
        banco.atualizar_video(v["id"], caminho_arquivo=None)
        apagados += 1
    if apagados:
        log.info("Limpeza: %d video(s) bruto(s) apagado(s).", apagados)
    return apagados


# ---------- agendamento diario ----------

def deve_rodar(usuario_id: int, agora: datetime | None = None) -> bool:
    """Verdadeiro se a busca automatica esta ligada, ja passou da hora de hoje e ainda nao deu certo hoje."""
    if not banco.ler_config(usuario_id, "busca_ativa"):
        return False
    agora = agora or _agora_utc()
    local = agora.astimezone(_fuso())
    if local.hour < banco.ler_config(usuario_id, "busca_hora"):
        return False
    dia = local.strftime("%Y-%m-%d")
    with closing(banco.conectar()) as conexao:
        hoje = conexao.execute("SELECT estado, iniciada_em FROM buscas WHERE usuario_id = ? AND dia = ? "
                               "ORDER BY id DESC", (usuario_id, dia)).fetchall()
    if any(b["estado"] in ("pronta", "rodando") for b in hoje):
        return False
    if len(hoje) >= MAX_TENTATIVAS_POR_DIA:
        return False
    return not hoje or agora - _de_texto_utc(hoje[0]["iniciada_em"]) >= ESPERA_ENTRE_TENTATIVAS


def rodar_se_for_hora(usuario_id: int = config.USUARIO_PADRAO, agora: datetime | None = None, coletor=None) -> bool:
    """Chamado de minuto em minuto: roda a busca do dia e a limpeza, se for a hora. Devolve se rodou."""
    if not deve_rodar(usuario_id, agora):
        return False
    try:
        resultado = rodar(usuario_id, coletor=coletor, agora=agora)
    except Exception:
        return True            # ja registrado como "falhou"; tenta de novo depois de 30 minutos
    apagados = limpar_brutos(usuario_id, agora)
    avisos.avisar(f"🔎 Busca do dia pronta: {resultado['ranking']} vídeos no ranking, "
                  f"{resultado['enfileirados']} enviados para a fila de cortes."
                  + (f" {apagados} vídeo(s) antigo(s) apagado(s) do disco." if apagados else ""),
                  chave=f"resumo:{resultado['busca_id']}")
    return True


class Buscador(threading.Thread):
    """Thread do painel: de minuto em minuto confere se e hora da busca diaria."""

    def __init__(self, intervalo_s: float = 60):
        super().__init__(name="buscador", daemon=True)
        self._parar = threading.Event()
        self.intervalo_s = intervalo_s

    def run(self) -> None:
        with closing(banco.conectar()) as conexao, conexao:      # busca que ficou "rodando" quando o painel fechou
            conexao.execute("UPDATE buscas SET estado = 'falhou', erro = 'O painel foi fechado no meio da busca.' "
                            "WHERE estado = 'rodando'")
        while not self._parar.is_set():
            try:
                rodar_se_for_hora()
            except Exception as erro:            # nunca deixa a thread morrer
                log.error("Buscador: erro inesperado: %s", erro)
                avisos.avisar(f"⚠️ Erro inesperado na busca diária: {str(erro)[:300]}", chave="buscador-inesperado")
            self._parar.wait(self.intervalo_s)

    def parar(self) -> None:
        self._parar.set()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    banco.criar_tabelas()
    resultado = rodar(enfileirar="--enfileirar" in sys.argv)
    print(resultado)
    for r in ranking_da_busca(resultado["busca_id"])[:15]:
        print(f"{r['posicao']:>2}. {r['velocidade'] or 0:>9.0f}/h | {r['horas']:>5.1f}h | {r['views'] or 0:>9} | {r['destino']:<14} | {r['titulo'][:50]}")
