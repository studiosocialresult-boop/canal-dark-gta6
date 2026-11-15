"""Banco de dados (SQLite em dados/canal.db).

Guarda os videos de origem, os cortes e o gasto com IA. Toda tabela tem
usuario_id, para a ferramenta poder ter varios usuarios no futuro.

Rodar sozinho cria o banco e lista as tabelas:
    python -m app.banco
"""
import sqlite3
from contextlib import closing

from app import config
from app.contratos import CorteProposto, Roteiro

TEMPLATES_SQL = """
CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    nome TEXT NOT NULL,
    layout TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    passo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

FILA_SQL = """
-- Fila de trabalho do painel: um item por vez e processado, na ordem de chegada.
-- tipo: "link" (processar um video), "narrar" (narrar um corte; alvo = id do corte),
-- "lote" (gerar os videos de um template; alvo = id do template) ou "baixar" (baixar um video
-- para a biblioteca; alvo = link). O codigo valida o tipo.
-- estado: aguardando -> processando -> pronto (ou falhou)
CREATE TABLE IF NOT EXISTS fila (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    tipo TEXT NOT NULL,
    alvo TEXT NOT NULL,
    rotulo TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'aguardando',
    progresso TEXT,
    resultado TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    iniciado_em TEXT,
    terminado_em TEXT
);
"""

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS configuracoes (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    chave TEXT NOT NULL,
    valor TEXT NOT NULL,
    PRIMARY KEY (usuario_id, chave)
);

-- Videos de origem. A fonte (url, canal, titulo) fica guardada para dar credito.
-- estado: novo -> baixado -> transcrito -> analisado -> pronto (ou falhou)
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    plataforma TEXT NOT NULL,
    id_externo TEXT NOT NULL,
    url TEXT NOT NULL,
    titulo TEXT,
    canal TEXT,
    duracao_s REAL,
    idioma TEXT,
    caminho_arquivo TEXT,
    caminho_transcricao TEXT,
    estado TEXT NOT NULL DEFAULT 'novo',
    erro TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (usuario_id, plataforma, id_externo)
);

-- Cortes escolhidos pelo cerebro.
-- estado: proposto -> renderizado -> aprovado / descartado (ou falhou)
CREATE TABLE IF NOT EXISTS cortes (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    video_id INTEGER NOT NULL REFERENCES videos(id),
    frase_inicio INTEGER NOT NULL,
    frase_fim INTEGER NOT NULL,
    inicio_s REAL NOT NULL,
    fim_s REAL NOT NULL,
    nota INTEGER NOT NULL,
    motivo TEXT NOT NULL,
    titulo TEXT NOT NULL,
    modo TEXT NOT NULL CHECK (modo IN ('original', 'narrado')),
    estado TEXT NOT NULL DEFAULT 'proposto',
    caminho_arquivo TEXT,
    erro TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Narracao de um corte: primeiro o roteiro (texto), depois o audio.
-- estado: roteirizado -> narrado (ou falhou). Um corte tem no maximo uma narracao.
CREATE TABLE IF NOT EXISTS narracoes (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    corte_id INTEGER NOT NULL UNIQUE REFERENCES cortes(id),
    roteiro TEXT NOT NULL,
    caracteres INTEGER NOT NULL DEFAULT 0,
    caminho_audio TEXT,
    estado TEXT NOT NULL DEFAULT 'roteirizado',
    erro TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Fila de trabalho do painel: um item por vez e processado, na ordem de chegada.
-- tipo: "link" (processar um video), "narrar" (narrar um corte; alvo = id do corte),
-- "lote" (gerar os videos de um template; alvo = id do template) ou "baixar" (baixar um video
-- para a biblioteca; alvo = link). O codigo valida o tipo.
-- estado: aguardando -> processando -> pronto (ou falhou)
CREATE TABLE IF NOT EXISTS fila (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    tipo TEXT NOT NULL,
    alvo TEXT NOT NULL,
    rotulo TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'aguardando',
    progresso TEXT,
    resultado TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    iniciado_em TEXT,
    terminado_em TEXT
);

-- Perfis de pagina salvos (foto, nome, @, tema...) para reutilizar em varios templates.
CREATE TABLE IF NOT EXISTS perfis_pagina (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    rotulo TEXT NOT NULL,
    dados TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Templates: um layout (post, meme ou viral) e a configuracao do assistente (JSON).
-- estado: rascunho -> pronto (tem midia e frase) ; passo = ultimo passo do assistente aberto.
CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    nome TEXT NOT NULL,
    layout TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    passo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Videos do template. origem: "corte", "upload" ou "perfil".
-- com_legenda (so corte): 1 usa o corte pronto, com legenda e narracao; 0 usa o trecho do video original, limpo.
-- avulsa: 1 = criada pela janela do corte ("Postar com template"); nao aparece no assistente nem entra no lote.
-- zona: 1 (principal) ou 2 (segunda zona do layout viral).
CREATE TABLE IF NOT EXISTS template_midias (
    id INTEGER PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    origem TEXT NOT NULL CHECK (origem IN ('corte', 'upload', 'perfil')),
    corte_id INTEGER REFERENCES cortes(id),
    arquivo TEXT,
    rotulo TEXT NOT NULL,
    zona INTEGER NOT NULL DEFAULT 1,
    ajuste TEXT NOT NULL DEFAULT 'preencher',
    zoom REAL NOT NULL DEFAULT 1,
    pos_x REAL NOT NULL DEFAULT 50,
    pos_y REAL NOT NULL DEFAULT 50,
    selecionada INTEGER NOT NULL DEFAULT 1,
    com_legenda INTEGER NOT NULL DEFAULT 1,
    avulsa INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

-- midia_id: a frase pertence a um video so (so sai combinada com ele). Vazio: vale para todos os videos.
CREATE TABLE IF NOT EXISTS template_frases (
    id INTEGER PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    texto TEXT NOT NULL,
    origem TEXT NOT NULL DEFAULT 'manual',
    selecionada INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    midia_id INTEGER REFERENCES template_midias(id) ON DELETE CASCADE
);

-- Videos baixados pelas telas Perfis (ficam para usar nos templates e no editor).
CREATE TABLE IF NOT EXISTS biblioteca (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    plataforma TEXT NOT NULL,
    id_externo TEXT NOT NULL,
    url TEXT NOT NULL,
    titulo TEXT,
    canal TEXT,
    duracao_s REAL,
    arquivo TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (usuario_id, plataforma, id_externo)
);

-- Um video gerado = uma midia x uma frase. estado: aguardando -> renderizando -> pronto (ou falhou).
CREATE TABLE IF NOT EXISTS template_saidas (
    id INTEGER PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    midia_id INTEGER NOT NULL REFERENCES template_midias(id) ON DELETE CASCADE,
    frase_id INTEGER NOT NULL REFERENCES template_frases(id) ON DELETE CASCADE,
    estado TEXT NOT NULL DEFAULT 'aguardando',
    arquivo TEXT,
    erro TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (template_id, midia_id, frase_id)
);

-- Contas das redes sociais conectadas. As credenciais (tokens de acesso) ficam criptografadas.
-- rede: youtube, instagram, facebook ou tiktok. estado: conectada, expirada (precisa conectar de novo) ou erro.
CREATE TABLE IF NOT EXISTS contas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    rede TEXT NOT NULL,
    id_externo TEXT NOT NULL,
    nome TEXT NOT NULL,
    foto TEXT,
    credenciais TEXT NOT NULL,
    ativa INTEGER NOT NULL DEFAULT 1,
    posts_por_dia INTEGER NOT NULL DEFAULT 4,
    estado TEXT NOT NULL DEFAULT 'conectada',
    erro TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (usuario_id, rede, id_externo)
);

-- Publicacoes: um video em uma conta, num horario. Horarios em UTC ('AAAA-MM-DD HH:MM:SS').
-- chave_video identifica o conteudo de origem (ex.: "corte:12"): o mesmo corte nunca vai duas vezes
-- para a mesma conta, mesmo com frase ou layout diferente (indice unico abaixo).
-- estado: agendada -> publicando -> publicada (ou falhou, ou cancelada)
CREATE TABLE IF NOT EXISTS publicacoes (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    conta_id INTEGER NOT NULL REFERENCES contas(id) ON DELETE CASCADE,
    origem TEXT NOT NULL,
    corte_id INTEGER,
    saida_id INTEGER,
    arquivo TEXT NOT NULL,
    chave_video TEXT NOT NULL,
    titulo TEXT NOT NULL,
    legenda TEXT NOT NULL,
    opcoes TEXT NOT NULL DEFAULT '{}',
    agendada_para TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'agendada',
    tentativas INTEGER NOT NULL DEFAULT 0,
    proxima_tentativa TEXT,
    id_externo TEXT,
    url TEXT,
    erro TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    publicado_em TEXT,
    removida_em TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS publicacao_unica_por_conta
    ON publicacoes (conta_id, chave_video) WHERE estado != 'cancelada';

-- Leituras dos numeros de um post nas redes (Fase 8). marco: 'atual' (regravada a cada rodada) ou a
-- foto tirada quando o post completou aquela idade ('24h', '3d', '7d'). NULL = a rede nao informa.
CREATE TABLE IF NOT EXISTS leituras (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    publicacao_id INTEGER NOT NULL REFERENCES publicacoes(id) ON DELETE CASCADE,
    marco TEXT NOT NULL,
    visualizacoes INTEGER,
    curtidas INTEGER,
    comentarios INTEGER,
    lido_em TEXT NOT NULL,
    UNIQUE (publicacao_id, marco)
);

-- Busca diaria (Fase 6): canais acompanhados, cada execucao da busca e o ranking que ela montou.
CREATE TABLE IF NOT EXISTS canais_monitorados (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    url TEXT NOT NULL,
    nome TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (usuario_id, url)
);
-- estado: rodando -> pronta (ou falhou)
CREATE TABLE IF NOT EXISTS buscas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    dia TEXT NOT NULL,
    iniciada_em TEXT NOT NULL DEFAULT (datetime('now')),
    terminada_em TEXT,
    estado TEXT NOT NULL DEFAULT 'rodando',
    resumo TEXT,
    erro TEXT
);
-- Uma linha por video encontrado. destino: enfileirado / ja_processado / fora_da_meta / ignorado.
CREATE TABLE IF NOT EXISTS ranking (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    busca_id INTEGER NOT NULL REFERENCES buscas(id),
    dia TEXT NOT NULL,
    plataforma TEXT NOT NULL DEFAULT 'youtube',
    id_externo TEXT NOT NULL,
    url TEXT NOT NULL,
    titulo TEXT,
    canal TEXT,
    duracao_s REAL,
    views INTEGER,
    publicado TEXT,
    horas REAL,
    velocidade REAL,
    aceleracao REAL,
    origem TEXT NOT NULL,
    posicao INTEGER NOT NULL,
    destino TEXT NOT NULL,
    motivo TEXT,
    coletado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ranking_por_video ON ranking (usuario_id, id_externo, coletado_em);

-- Cada chamada paga a um servico de IA, para medir o custo por corte.
CREATE TABLE IF NOT EXISTS uso_api (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    video_id INTEGER REFERENCES videos(id),
    servico TEXT NOT NULL,
    modelo TEXT,
    etapa TEXT NOT NULL,
    tokens_entrada INTEGER NOT NULL DEFAULT 0,
    tokens_saida INTEGER NOT NULL DEFAULT 0,
    caracteres INTEGER NOT NULL DEFAULT 0,
    custo_usd REAL NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CAMPOS_VIDEO = {
    "titulo", "canal", "duracao_s", "idioma", "caminho_arquivo",
    "caminho_transcricao", "estado", "erro",
}
CAMPOS_CORTE = {"estado", "caminho_arquivo", "erro"}
CAMPOS_NARRACAO = {"caminho_audio", "estado", "erro"}
CAMPOS_FILA = {"estado", "progresso", "resultado", "iniciado_em", "terminado_em"}


def conectar() -> sqlite3.Connection:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(config.ARQUIVO_BANCO)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    return conexao


def criar_tabelas() -> None:
    """Cria as tabelas que faltam e o usuario padrao. Pode rodar quantas vezes quiser."""
    _migrar_tabelas_com_trava()
    with closing(conectar()) as conexao, conexao:
        conexao.executescript(ESQUEMA)
        _garantir_colunas(conexao)
        conexao.execute(
            "INSERT OR IGNORE INTO usuarios (id, nome) VALUES (?, ?)",
            (config.USUARIO_PADRAO, "dono"),
        )


def _garantir_colunas(conexao) -> None:
    """Bancos antigos nao tem colunas que foram acrescentadas depois. Acrescenta sem perder dados."""
    colunas_midias = {l["name"] for l in conexao.execute("PRAGMA table_info(template_midias)")}
    if "avulsa" not in colunas_midias:
        conexao.execute("ALTER TABLE template_midias ADD COLUMN avulsa INTEGER NOT NULL DEFAULT 0")
    if "com_legenda" not in colunas_midias:
        conexao.execute("ALTER TABLE template_midias ADD COLUMN com_legenda INTEGER NOT NULL DEFAULT 1")
    colunas = {l["name"] for l in conexao.execute("PRAGMA table_info(template_frases)")}
    if "midia_id" not in colunas:
        conexao.execute("ALTER TABLE template_frases ADD COLUMN midia_id INTEGER "
                        "REFERENCES template_midias(id) ON DELETE CASCADE")
    colunas = {l["name"] for l in conexao.execute("PRAGMA table_info(publicacoes)")}
    if colunas and "removida_em" not in colunas:
        conexao.execute("ALTER TABLE publicacoes ADD COLUMN removida_em TEXT")


TRAVAS_ANTIGAS = {"fila": "CHECK (tipo", "templates": "CHECK (layout"}


def _sem_comentarios(sql: str) -> str:
    return "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))


def _migrar_tabelas_com_trava() -> None:
    """Bancos antigos tem `fila` e `templates` com listas fixas de tipos e layouts (CHECK). Refaz as
    duas tabelas sem a trava, copiando tudo numa unica transacao. Roda uma vez e nao perde dados."""
    if not config.ARQUIVO_BANCO.exists():
        return
    conexao = sqlite3.connect(config.ARQUIVO_BANCO, isolation_level=None)
    conexao.row_factory = sqlite3.Row
    try:
        refazer = []
        for nome, trava in TRAVAS_ANTIGAS.items():
            linha = conexao.execute("SELECT sql FROM sqlite_master WHERE name = ?", (nome,)).fetchone()
            if linha is not None and trava in linha["sql"]:
                refazer.append(nome)
        if not refazer:
            return
        conexao.execute("PRAGMA foreign_keys = OFF")
        # Sem isto, renomear a tabela antiga faria as tabelas filhas passarem a apontar para o nome novo dela.
        conexao.execute("PRAGMA legacy_alter_table = ON")
        conexao.execute("BEGIN")
        try:
            for nome in refazer:
                conexao.execute(f"ALTER TABLE {nome} RENAME TO {nome}_antiga")
                conexao.execute(_sem_comentarios(FILA_SQL if nome == "fila" else TEMPLATES_SQL))
                conexao.execute(f"INSERT INTO {nome} SELECT * FROM {nome}_antiga")
                conexao.execute(f"DROP TABLE {nome}_antiga")
            conexao.execute("COMMIT")
        except Exception:
            conexao.execute("ROLLBACK")
            raise
    finally:
        conexao.execute("PRAGMA legacy_alter_table = OFF")
        conexao.execute("PRAGMA foreign_keys = ON")
        conexao.close()


# ---------- configuracoes por usuario ----------

def ler_config(usuario_id: int, chave: str):
    """Le uma configuracao do usuario; se ele nunca mudou, devolve o valor padrao."""
    padrao = config.CONFIG_PADRAO[chave]
    with closing(conectar()) as conexao:
        linha = conexao.execute(
            "SELECT valor FROM configuracoes WHERE usuario_id = ? AND chave = ?",
            (usuario_id, chave),
        ).fetchone()
    if linha is None:
        return padrao
    return type(padrao)(linha["valor"])


def salvar_config(usuario_id: int, chave: str, valor) -> None:
    if chave not in config.CONFIG_PADRAO:
        raise KeyError(f"Configuracao desconhecida: {chave}")
    with closing(conectar()) as conexao, conexao:
        conexao.execute(
            "INSERT INTO configuracoes (usuario_id, chave, valor) VALUES (?, ?, ?) "
            "ON CONFLICT (usuario_id, chave) DO UPDATE SET valor = excluded.valor",
            (usuario_id, chave, str(valor)),
        )


# ---------- videos ----------

def buscar_video(usuario_id: int, plataforma: str, id_externo: str):
    with closing(conectar()) as conexao:
        return conexao.execute(
            "SELECT * FROM videos WHERE usuario_id = ? AND plataforma = ? AND id_externo = ?",
            (usuario_id, plataforma, id_externo),
        ).fetchone()


def ler_video(video_id: int):
    with closing(conectar()) as conexao:
        return conexao.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()


def registrar_video(usuario_id: int, plataforma: str, id_externo: str, url: str) -> int:
    """Registra o video e devolve o id. Se ja existir, devolve o id existente."""
    with closing(conectar()) as conexao, conexao:
        conexao.execute(
            "INSERT OR IGNORE INTO videos (usuario_id, plataforma, id_externo, url) VALUES (?, ?, ?, ?)",
            (usuario_id, plataforma, id_externo, url),
        )
        linha = conexao.execute(
            "SELECT id FROM videos WHERE usuario_id = ? AND plataforma = ? AND id_externo = ?",
            (usuario_id, plataforma, id_externo),
        ).fetchone()
    return linha["id"]


def atualizar_video(video_id: int, **campos) -> None:
    _atualizar("videos", CAMPOS_VIDEO, video_id, campos, marcar_data=True)


# ---------- cortes ----------

def registrar_corte(usuario_id: int, video_id: int, corte: CorteProposto) -> int:
    with closing(conectar()) as conexao, conexao:
        cursor = conexao.execute(
            "INSERT INTO cortes (usuario_id, video_id, frase_inicio, frase_fim, inicio_s, fim_s, "
            "nota, motivo, titulo, modo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (usuario_id, video_id, corte.frase_inicio, corte.frase_fim, corte.inicio, corte.fim,
             corte.nota, corte.motivo, corte.titulo, corte.modo),
        )
        return cursor.lastrowid


def cortes_do_video(video_id: int) -> list:
    with closing(conectar()) as conexao:
        return conexao.execute(
            "SELECT * FROM cortes WHERE video_id = ? ORDER BY nota DESC, id", (video_id,)
        ).fetchall()


def atualizar_corte(corte_id: int, **campos) -> None:
    _atualizar("cortes", CAMPOS_CORTE, corte_id, campos)


def ler_corte(corte_id: int):
    with closing(conectar()) as conexao:
        return conexao.execute("SELECT * FROM cortes WHERE id = ?", (corte_id,)).fetchone()


# ---------- narracoes ----------

def salvar_roteiro(usuario_id: int, corte_id: int, roteiro: Roteiro) -> int:
    """Guarda o roteiro do corte e devolve o id da narracao. Regravar troca o texto
    e volta o estado para 'roteirizado', porque o audio antigo deixa de valer."""
    with closing(conectar()) as conexao, conexao:
        conexao.execute(
            "INSERT INTO narracoes (usuario_id, corte_id, roteiro, caracteres) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (corte_id) DO UPDATE SET roteiro = excluded.roteiro, "
            "caracteres = excluded.caracteres, caminho_audio = NULL, estado = 'roteirizado', erro = NULL",
            (usuario_id, corte_id, roteiro.para_json(), len(roteiro.texto)),
        )
        linha = conexao.execute("SELECT id FROM narracoes WHERE corte_id = ?", (corte_id,)).fetchone()
    return linha["id"]


def ler_narracao(corte_id: int):
    """Devolve a linha da narracao do corte, ou None se ele ainda nao tem roteiro."""
    with closing(conectar()) as conexao:
        return conexao.execute("SELECT * FROM narracoes WHERE corte_id = ?", (corte_id,)).fetchone()


def atualizar_narracao(narracao_id: int, **campos) -> None:
    _atualizar("narracoes", CAMPOS_NARRACAO, narracao_id, campos)


# ---------- painel: lista de cortes e numeros do dia ----------

def listar_cortes(usuario_id: int) -> list:
    """Todos os cortes do usuario, do mais novo para o mais velho, com a fonte e a narracao."""
    with closing(conectar()) as conexao:
        return conexao.execute(
            "SELECT c.*, v.titulo AS video_titulo, v.canal AS video_canal, v.url AS video_url, "
            "v.plataforma AS video_plataforma, n.estado AS narracao_estado, "
            "COALESCE((SELECT SUM(u.custo_usd) FROM uso_api u WHERE u.video_id = c.video_id), 0) "
            "  / (SELECT COUNT(*) FROM cortes c2 WHERE c2.video_id = c.video_id) AS custo_usd "
            "FROM cortes c JOIN videos v ON v.id = c.video_id "
            "LEFT JOIN narracoes n ON n.corte_id = c.id "
            "WHERE c.usuario_id = ? ORDER BY c.id DESC", (usuario_id,)).fetchall()


def numeros_do_painel(usuario_id: int) -> dict:
    """Contadores da tela Cortes: totais por estado e gasto com IA."""
    with closing(conectar()) as conexao:
        estados = {l["estado"]: l["total"] for l in conexao.execute(
            "SELECT estado, COUNT(*) AS total FROM cortes WHERE usuario_id = ? GROUP BY estado",
            (usuario_id,))}
        hoje = conexao.execute(
            "SELECT COUNT(*) AS total FROM cortes WHERE usuario_id = ? AND date(criado_em) = date('now')",
            (usuario_id,)).fetchone()["total"]
        gasto = conexao.execute(
            "SELECT COALESCE(SUM(custo_usd), 0) AS total FROM uso_api WHERE usuario_id = ?",
            (usuario_id,)).fetchone()["total"]
        gasto_hoje = conexao.execute(
            "SELECT COALESCE(SUM(custo_usd), 0) AS total FROM uso_api "
            "WHERE usuario_id = ? AND date(criado_em) = date('now')", (usuario_id,)).fetchone()["total"]
        videos = conexao.execute(
            "SELECT COUNT(*) AS total FROM videos WHERE usuario_id = ? AND estado = 'pronto'",
            (usuario_id,)).fetchone()["total"]
    return {"estados": estados, "cortes_hoje": hoje, "gasto_usd": gasto,
            "gasto_hoje_usd": gasto_hoje, "videos_prontos": videos}


# ---------- fila de trabalho ----------

def enfileirar(usuario_id: int, tipo: str, alvo: str, rotulo: str) -> int:
    with closing(conectar()) as conexao, conexao:
        return conexao.execute(
            "INSERT INTO fila (usuario_id, tipo, alvo, rotulo) VALUES (?, ?, ?, ?)",
            (usuario_id, tipo, alvo, rotulo)).lastrowid


def item_na_fila(usuario_id: int, tipo: str, alvo: str):
    """Devolve o item ainda pendente (aguardando ou processando) para o mesmo alvo, se houver."""
    with closing(conectar()) as conexao:
        return conexao.execute(
            "SELECT * FROM fila WHERE usuario_id = ? AND tipo = ? AND alvo = ? "
            "AND estado IN ('aguardando', 'processando')", (usuario_id, tipo, alvo)).fetchone()


def proximo_da_fila():
    with closing(conectar()) as conexao:
        return conexao.execute(
            "SELECT * FROM fila WHERE estado = 'aguardando' ORDER BY id LIMIT 1").fetchone()


def listar_fila(usuario_id: int, limite: int = 12) -> list:
    """Itens ativos primeiro, depois os mais recentes ja terminados."""
    with closing(conectar()) as conexao:
        return conexao.execute(
            "SELECT * FROM fila WHERE usuario_id = ? ORDER BY "
            "CASE estado WHEN 'processando' THEN 0 WHEN 'aguardando' THEN 1 ELSE 2 END, id DESC LIMIT ?",
            (usuario_id, limite)).fetchall()


def atualizar_fila(item_id: int, **campos) -> None:
    _atualizar("fila", CAMPOS_FILA, item_id, campos)


def retomar_fila() -> None:
    """Ao ligar o painel, o que estava sendo processado volta para a fila (tudo e retomavel)."""
    with closing(conectar()) as conexao, conexao:
        conexao.execute("UPDATE fila SET estado = 'aguardando', progresso = NULL "
                        "WHERE estado = 'processando'")


# ---------- gasto com IA ----------

def registrar_uso_api(usuario_id: int, servico: str, etapa: str, *, video_id: int | None = None,
                      modelo: str | None = None, tokens_entrada: int = 0, tokens_saida: int = 0,
                      caracteres: int = 0, custo_usd: float = 0.0) -> None:
    with closing(conectar()) as conexao, conexao:
        conexao.execute(
            "INSERT INTO uso_api (usuario_id, video_id, servico, modelo, etapa, tokens_entrada, "
            "tokens_saida, caracteres, custo_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (usuario_id, video_id, servico, modelo, etapa, tokens_entrada, tokens_saida,
             caracteres, custo_usd),
        )


def custo_do_video(video_id: int) -> float:
    """Soma, em dolares, o que ja foi gasto com IA neste video."""
    with closing(conectar()) as conexao:
        linha = conexao.execute(
            "SELECT COALESCE(SUM(custo_usd), 0) AS total FROM uso_api WHERE video_id = ?",
            (video_id,),
        ).fetchone()
    return linha["total"]


def _atualizar(tabela: str, permitidos: set, registro_id: int, campos: dict,
               marcar_data: bool = False) -> None:
    desconhecidos = set(campos) - permitidos
    if desconhecidos:
        raise KeyError(f"Campos nao permitidos em {tabela}: {sorted(desconhecidos)}")
    if not campos:
        return
    partes = [f"{nome} = ?" for nome in campos]
    if marcar_data:
        partes.append("atualizado_em = datetime('now')")
    with closing(conectar()) as conexao, conexao:
        conexao.execute(
            f"UPDATE {tabela} SET {', '.join(partes)} WHERE id = ?",
            (*campos.values(), registro_id),
        )


if __name__ == "__main__":
    criar_tabelas()
    with closing(conectar()) as _conexao:
        _tabelas = [l["name"] for l in _conexao.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    print("Banco em:", config.ARQUIVO_BANCO)
    print("Tabelas: ", ", ".join(_tabelas))
