"""Escalacao do dia: o modo automatico escolhe os melhores cortes para os horarios livres das proximas 24 h.

Como funciona:
- Vagas: os horarios livres de cada conta (no ritmo dela) nas proximas 24 h. So contas de redes que aceitam
  o modo automatico (o TikTok nunca entra).
- Candidatos: cortes prontos, com nota igual ou acima da minima do automatico, criados ha no maximo
  `validade_automatico_dias`. Corte de modo "narrado" so entra com a narracao pronta. Um corte que o dono
  cancelou numa publicacao do automatico fica vetado.
- Cada candidato vale a nota menos PERDA_POR_DIA pontos por dia de idade (noticia envelhece).
- O horario nobre de cada conta (o mais perto das 20h30) e preenchido primeiro, com o melhor corte. Os outros
  horarios vem depois, em ordem.
- Regras de cada conta: o mesmo corte nunca duas vezes; nada de assunto parecido com o de outro post da conta em
  7 dias; nada de dois cortes do mesmo video de origem em 24 h; no maximo 1 corte de modo "original" a cada 3
  posts seguidos (o modo narrado e o que as redes contam como contribuicao propria).
- Entre contas: o mesmo corte nunca em duas contas da MESMA rede; em redes diferentes, pelo menos 2 h de
  distancia entre um post e outro.
- A escalacao e refeita a cada 5 minutos, mas cada vaga so e fechada (vira publicacao) 2 h antes: ate la, um
  corte melhor que ficou pronto depois ainda pode tomar o lugar. Corte que nao achou vaga continua na tela
  Cortes, para o dono revisar.

Rodar sozinho (so mostra a escalacao das proximas 24 h, nao agenda nada):
    python -m app.postagem.escalacao
"""
import re
import sys
import unicodedata
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app import banco, config
from app.multiplicador import renderizar
from app.postagem import agendador, contas
from app.postagem.redes import REDES

log = config.criar_log("escalacao")

HORIZONTE_H = 24              # a escalacao olha as vagas das proximas 24 h
ANTECEDENCIA_H = 2            # a vaga so e fechada 2 h antes do horario
CENTRO_NOBRE = (20, 30)       # pico do publico brasileiro: o melhor corte vai para o horario mais perto das 20h30
PERDA_POR_DIA = 10            # pontos que a nota perde por dia de idade
ESPACO_ENTRE_REDES = timedelta(hours=2)
DIAS_SEM_REPETIR_ASSUNTO = 7
HORAS_SEM_REPETIR_VIDEO = 24
ORIGINAIS_VIZINHOS = 2        # um corte "original" nao pode ter outro "original" entre os 2 posts antes e os 2 depois

# Palavras que nao dizem o assunto de um titulo (o canal inteiro e sobre GTA 6).
PALAVRAS_VAZIAS = set("""
gta grand theft auto rockstar jogo game games video novo nova novos novas que com para por pelo pela pelos pelas
dos das nos nas num numa uma uns umas mais menos como esta estao isso esse essa este esta seu sua seus suas ele ela
eles elas tem sao foi ser sem muito muita pode podem vai vao ainda agora quando onde qual quais todo toda todos todas
tudo sobre entre ate nao sim mas the and for you with this that your from are was has have will what how why who
voce voces aqui ali la isto aquilo ja ter sera cada outro outra
""".split())


@dataclass
class Candidato:
    corte_id: int
    titulo: str
    modo: str
    video_id: int
    nota: int
    estado: str
    duracao_s: float
    pontos: float
    palavras: frozenset


@dataclass
class Post:
    """Um post de uma conta: ja agendado/publicado, ou planejado nesta escalacao."""
    horario: datetime
    corte_id: int | None
    video_id: int | None
    modo: str
    palavras: frozenset


@dataclass
class Escala:
    conta: dict
    horario: datetime
    candidato: Candidato | None             # None: vaga sem corte que sirva
    nobre: bool = False


@dataclass
class _Estado:
    """O que ja esta ocupado em cada conta, somando o que foi agendado antes e o que esta sendo planejado."""
    posts: dict[int, list[Post]] = field(default_factory=dict)          # conta_id -> posts
    chaves: dict[int, set[str]] = field(default_factory=dict)           # conta_id -> chave_video usadas
    corte_em: dict[int, list[tuple[dict, datetime]]] = field(default_factory=dict)   # corte_id -> [(conta, horario)]


# ---------- assunto ----------

def palavras_do_titulo(titulo: str) -> frozenset:
    """As palavras que dizem o assunto: sem acento, sem palavras vazias, sem plural simples."""
    texto = unicodedata.normalize("NFKD", titulo or "").encode("ascii", "ignore").decode().lower()
    resultado = set()
    for palavra in re.findall(r"[a-z0-9]+", texto):
        if len(palavra) < 3 or palavra in PALAVRAS_VAZIAS:
            continue
        if len(palavra) > 4 and palavra.endswith("s") and not palavra.isdigit():
            palavra = palavra[:-1]
        resultado.add(palavra)
    return frozenset(resultado)


def mesmo_assunto(a: frozenset, b: frozenset) -> bool:
    """Dois titulos falam da mesma coisa se dividem pelo menos 2 palavras de assunto e metade das do mais curto."""
    comuns = len(a & b)
    return comuns >= 2 and comuns >= 0.5 * min(len(a), len(b))


# ---------- contas, vagas e candidatos ----------

def contas_do_automatico(usuario_id: int) -> list[dict]:
    return [c for c in contas.listar_contas(usuario_id)
            if c["ativa"] and c["estado"] == "conectada" and REDES[c["rede"]]["automatico"]]


def vagas_por_dia(usuario_id: int, dia: date | None = None) -> int:
    """Quantos posts por dia as contas do automatico fazem hoje (no ritmo de cada uma). Serve para a busca
    diaria nao produzir muito mais cortes do que cabem nas contas."""
    dia = dia or agendador.agora().astimezone(agendador._fuso()).date()
    return sum(agendador.ritmo_no_dia(conta, dia) for conta in contas_do_automatico(usuario_id))


def _horario_nobre(conta: dict, dia: date, usuario_id: int) -> datetime | None:
    """O horario da conta naquele dia que fica mais perto das 20h30 (dos horarios do ritmo dela)."""
    grade = agendador.grade_do_dia(dia, agendador.ritmo_no_dia(conta, dia), usuario_id,
                                   agendador.intervalo_da_conta(conta, usuario_id))
    centro = datetime(dia.year, dia.month, dia.day, *CENTRO_NOBRE, tzinfo=agendador._fuso())
    return min(grade, key=lambda h: abs(h - centro)) if grade else None


def _vagas(usuario_id: int, contas_auto: list[dict], agora: datetime) -> list[Escala]:
    """Os horarios livres das proximas 24 h, o horario nobre de cada conta primeiro."""
    limite = agora + timedelta(hours=HORIZONTE_H)
    vagas = []
    for conta in contas_auto:
        hoje = agora.astimezone(agendador._fuso()).date()
        ritmo = max(agendador.ritmo_no_dia(conta, hoje), agendador.ritmo_no_dia(conta, hoje + timedelta(days=1)))
        nobres = {_horario_nobre(conta, hoje + timedelta(days=d), usuario_id) for d in range(3)}
        for horario in agendador.proximos_horarios(conta, 2 * ritmo + 2, usuario_id, depois_de=agora):
            if horario <= limite:
                vagas.append(Escala(conta, horario, None, nobre=horario in nobres))
    return sorted(vagas, key=lambda v: (not v.nobre, v.horario, v.conta["id"]))


_duracoes: dict[tuple[str, float], float] = {}


def _duracao(arquivo) -> float:
    """Duracao do video (com o ffprobe), guardada enquanto o arquivo nao muda."""
    chave = (str(arquivo), arquivo.stat().st_mtime)
    if chave not in _duracoes:
        _duracoes[chave] = renderizar.duracao_do_arquivo(arquivo)
    return _duracoes[chave]


def candidatos(usuario_id: int, agora: datetime, fora: dict[str, int] | None = None) -> list[Candidato]:
    """Os cortes que podem entrar na escalacao, do mais forte para o mais fraco.
    `fora` (opcional) recebe a contagem de cortes deixados de fora, por motivo (para a previa)."""
    def deixar_de_fora(motivo: str) -> None:
        if fora is not None:
            fora[motivo] = fora.get(motivo, 0) + 1

    nota_minima = banco.ler_config(usuario_id, "nota_minima_automatico")
    validade = timedelta(days=banco.ler_config(usuario_id, "validade_automatico_dias"))
    with closing(banco.conectar()) as conexao:
        automaticas = conexao.execute(
            "SELECT corte_id, estado FROM publicacoes WHERE usuario_id = ? AND automatica = 1 AND corte_id IS NOT NULL",
            (usuario_id,)).fetchall()
    vetados = {l["corte_id"] for l in automaticas if l["estado"] == "cancelada"}
    do_automatico = {l["corte_id"] for l in automaticas if l["estado"] != "cancelada"}
    lista = []
    for linha in banco.listar_cortes(usuario_id):
        if linha["id"] in vetados:
            deixar_de_fora("vetado (post do automático cancelado)")
            continue
        if linha["estado"] == "renderizado":
            if linha["nota"] < nota_minima:
                deixar_de_fora(f"nota abaixo de {nota_minima}")
                continue
        elif not (linha["estado"] == "aprovado" and linha["id"] in do_automatico):
            # aprovado pelo dono: ele decide onde vai; descartado/falhou: nunca
            deixar_de_fora("aprovado por você" if linha["estado"] == "aprovado" else f"estado: {linha['estado']}")
            continue
        idade = agora - agendador.momento(linha["criado_em"])
        if idade > validade:
            deixar_de_fora(f"mais velho que {validade.days} dias")
            continue
        if linha["modo"] == "narrado" and linha["narracao_estado"] != "narrado":
            deixar_de_fora("narrado sem a voz pronta")  # sem a voz, viraria so trecho com legenda
            continue
        arquivo = config.caminho_absoluto(linha["caminho_arquivo"]) if linha["caminho_arquivo"] else None
        if arquivo is None or not arquivo.exists():
            deixar_de_fora("sem o arquivo do vídeo")
            continue
        try:
            duracao = _duracao(arquivo)
        except renderizar.ErroRender:
            deixar_de_fora("vídeo ilegível")
            continue
        pontos = linha["nota"] - PERDA_POR_DIA * max(idade.total_seconds(), 0) / 86400
        lista.append(Candidato(linha["id"], linha["titulo"], linha["modo"], linha["video_id"], linha["nota"],
                               linha["estado"], duracao, round(pontos, 1), palavras_do_titulo(linha["titulo"])))
    return sorted(lista, key=lambda c: (-c.pontos, -c.nota, -c.corte_id))


def _estado_atual(usuario_id: int, contas_auto: list[dict], agora: datetime) -> _Estado:
    """O que ja esta agendado ou publicado nas contas (os ultimos 7 dias e tudo o que vem pela frente)."""
    estado = _Estado()
    por_id = {c["id"]: c for c in contas.listar_contas(usuario_id)}
    for conta in contas_auto:
        estado.posts[conta["id"]] = []
        estado.chaves[conta["id"]] = contas.chaves_usadas(conta["id"])
    desde = agendador.texto(agora - timedelta(days=DIAS_SEM_REPETIR_ASSUNTO))
    with closing(banco.conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT p.conta_id, p.agendada_para, p.corte_id, p.titulo, c.titulo AS corte_titulo, c.modo, c.video_id "
            "FROM publicacoes p LEFT JOIN cortes c ON c.id = p.corte_id "
            "WHERE p.usuario_id = ? AND p.estado NOT IN ('cancelada', 'falhou') AND p.agendada_para >= ?",
            (usuario_id, desde)).fetchall()
    for l in linhas:
        horario = agendador.momento(l["agendada_para"])
        # post sem corte (video enviado ou baixado de outro perfil) conta como "original": nao tem narracao
        post = Post(horario, l["corte_id"], l["video_id"], l["modo"] or "original",
                    palavras_do_titulo(l["corte_titulo"] or l["titulo"]))
        if l["conta_id"] in estado.posts:
            estado.posts[l["conta_id"]].append(post)
        if l["corte_id"] is not None and l["conta_id"] in por_id:
            estado.corte_em.setdefault(l["corte_id"], []).append((por_id[l["conta_id"]], horario))
    return estado


# ---------- regras ----------

def _motivo_para_nao_caber(c: Candidato, conta: dict, horario: datetime, estado: _Estado) -> str | None:
    """None se o corte pode ir para esta conta neste horario; senao, o motivo (vai para o log)."""
    if f"corte:{c.corte_id}" in estado.chaves[conta["id"]]:
        return "já vai (ou foi) nesta conta"
    limites = REDES[conta["rede"]]
    if not limites["duracao_min_s"] <= c.duracao_s <= limites["duracao_max_s"] + 0.5:
        return f"duração fora do limite de {limites['nome']}"
    for outra, quando in estado.corte_em.get(c.corte_id, []):
        if outra["rede"] == conta["rede"]:
            return "já vai para outra conta da mesma rede"
        if abs(quando - horario) < ESPACO_ENTRE_REDES:
            return "perto demais do mesmo corte em outra rede"
    posts = estado.posts[conta["id"]]
    for post in posts:
        distancia = abs(post.horario - horario)
        if distancia <= timedelta(days=DIAS_SEM_REPETIR_ASSUNTO) and mesmo_assunto(post.palavras, c.palavras):
            return "assunto parecido com outro post da conta"
        if post.video_id is not None and post.video_id == c.video_id and distancia < timedelta(hours=HORAS_SEM_REPETIR_VIDEO):
            return "outro corte do mesmo vídeo de origem perto deste horário"
    if c.modo == "original":
        antes = sorted((p for p in posts if p.horario < horario), key=lambda p: p.horario)[-ORIGINAIS_VIZINHOS:]
        depois = sorted((p for p in posts if p.horario > horario), key=lambda p: p.horario)[:ORIGINAIS_VIZINHOS]
        if any(p.modo == "original" for p in antes + depois):
            return "muitos cortes de áudio original seguidos"
    return None


def _ocupar(c: Candidato, conta: dict, horario: datetime, estado: _Estado) -> None:
    estado.chaves[conta["id"]].add(f"corte:{c.corte_id}")
    estado.posts[conta["id"]].append(Post(horario, c.corte_id, c.video_id, c.modo, c.palavras))
    estado.corte_em.setdefault(c.corte_id, []).append((conta, horario))


# ---------- escalacao ----------

def montar(usuario_id: int, agora: datetime | None = None) -> list[Escala]:
    """A escalacao das proximas 24 h: cada vaga com o melhor corte que cabe nela (ou None). Nao grava nada."""
    agora = agora or agendador.agora()
    contas_auto = contas_do_automatico(usuario_id)
    if not contas_auto:
        return []
    lista = candidatos(usuario_id, agora)
    estado = _estado_atual(usuario_id, contas_auto, agora)
    vagas = _vagas(usuario_id, contas_auto, agora)
    for vaga in vagas:
        for c in lista:
            if _motivo_para_nao_caber(c, vaga.conta, vaga.horario, estado) is None:
                vaga.candidato = c
                _ocupar(c, vaga.conta, vaga.horario, estado)
                break
    return sorted(vagas, key=lambda v: (v.horario, v.conta["id"]))


def rodar(usuario_id: int, agora: datetime | None = None, antecedencia_h: float = ANTECEDENCIA_H) -> int:
    """Se o modo automatico esta ligado, fecha as vagas que estao chegando. Devolve quantas publicacoes criou."""
    if not banco.ler_config(usuario_id, "modo_automatico"):
        return 0
    agora = agora or agendador.agora()
    limite = agora + timedelta(hours=antecedencia_h)
    criadas = 0
    for vaga in montar(usuario_id, agora):
        if vaga.candidato is None or vaga.horario > limite:
            continue
        c = vaga.candidato
        try:
            item = agendador.item_de_corte(c.corte_id, usuario_id, exigir_aprovado=False)
            resultado = agendador.agendar(usuario_id, [item], [vaga.conta["id"]], horario=vaga.horario, automatica=True)
        except (agendador.ErroAgenda, renderizar.ErroRender) as erro:
            log.warning("Automático: corte %d não foi para %s: %s", c.corte_id, vaga.conta["nome"], erro)
            continue
        if not resultado["criadas"]:
            log.warning("Automático: corte %d não foi para %s: %s", c.corte_id, vaga.conta["nome"],
                        "; ".join(p["motivo"] for p in resultado["puladas"]))
            continue
        if c.estado == "renderizado":
            banco.atualizar_corte(c.corte_id, estado="aprovado")
            c.estado = "aprovado"
        criadas += 1
        log.info("Automático: corte %d (nota %d) agendado em %s para %s.", c.corte_id, c.nota, vaga.conta["nome"],
                 vaga.horario.astimezone(agendador._fuso()).strftime("%d/%m %H:%M"))
    return criadas


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    banco.criar_tabelas()
    usuario = config.USUARIO_PADRAO
    momento_agora = agendador.agora()
    print("Modo automático:", "LIGADO" if banco.ler_config(usuario, "modo_automatico") else "desligado (só a prévia)")
    print(f"Vagas por dia nas contas do automático: {vagas_por_dia(usuario)}")
    de_fora: dict[str, int] = {}
    print(f"Cortes que podem entrar: {len(candidatos(usuario, momento_agora, de_fora))}")
    if de_fora:
        print("Ficaram de fora:", "; ".join(f"{n} {motivo}" for motivo, n in sorted(de_fora.items(), key=lambda x: -x[1])))
    faixas = {"90+": 0, "80-89": 0, "70-79": 0, "60-69": 0, "abaixo de 60": 0}
    for _c in banco.listar_cortes(usuario):
        _n = _c["nota"]
        faixas["90+" if _n >= 90 else "80-89" if _n >= 80 else "70-79" if _n >= 70 else "60-69" if _n >= 60
               else "abaixo de 60"] += 1
    print("Notas de todos os cortes:", ", ".join(f"{faixa}: {n}" for faixa, n in faixas.items()))
    escala = montar(usuario, momento_agora)
    if not escala:
        print("Nenhuma conta do automático conectada (YouTube, Instagram ou Facebook).")
    for v in escala:
        quando = v.horario.astimezone(agendador._fuso()).strftime("%d/%m %H:%M")
        marca = "★" if v.nobre else " "
        if v.candidato:
            c = v.candidato
            print(f"{quando} {marca} {v.conta['nome'][:22]:<22} nota {c.nota:>3} ({c.pontos:>5.1f}) {c.modo:<8} {c.titulo[:50]}")
        else:
            print(f"{quando} {marca} {v.conta['nome'][:22]:<22} — nenhum corte serve para esta vaga")
