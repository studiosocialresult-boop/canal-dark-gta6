"""Configuracoes centrais do projeto: pastas, modelos de IA, valores padrao e log.

Rodar sozinho mostra onde cada pasta esta:
    python -m app.config
"""
import logging
import logging.handlers
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

# A pasta de dados pode ser trocada pela variavel CANAL_PASTA_DADOS (usada nos testes e na VPS).
PASTA_DADOS = Path(os.getenv("CANAL_PASTA_DADOS") or RAIZ / "dados")
PASTA_BRUTOS = PASTA_DADOS / "brutos"
PASTA_CORTES = PASTA_DADOS / "cortes"
PASTA_TRANSCRICOES = PASTA_DADOS / "transcricoes"
PASTA_NARRACOES = PASTA_DADOS / "narracoes"
PASTA_BIBLIOTECA = PASTA_DADOS / "biblioteca"
PASTA_LOGS = PASTA_DADOS / "logs"
ARQUIVO_BANCO = PASTA_DADOS / "canal.db"
PASTA_PROMPTS = RAIZ / "prompts"
# Login do YouTube (conta secundaria) para baixar videos com restricao de idade.
# Opcional: se o arquivo nao existir, o download funciona sem login.
ARQUIVO_COOKIES = Path(os.getenv("CANAL_COOKIES", RAIZ / "cookies.txt"))

# Enquanto nao existe login, tudo pertence a este usuario.
USUARIO_PADRAO = 1

# Modelos da API da Anthropic (definidos no CLAUDE.md do projeto).
MODELO_CEREBRO = "claude-sonnet-5-5"   # escolha dos cortes e roteiro
MODELO_RAPIDO = "claude-haiku-5-5"     # titulos, legendas e hashtags
ESFORCO_CEREBRO = "medium"
ESFORCO_RAPIDO = "low"

# Ritmo da narracao, em caracteres por segundo (com espacos). Serve para o roteiro
# caber no tempo do corte. Valores iniciais: conferir com a voz real da ElevenLabs.
NARRACAO_CPS_IDEAL = 14.0      # ritmo confortavel
NARRACAO_CPS_MAX = 16.0        # acima disso a voz teria que correr
NARRACAO_SILENCIO_MAX_S = 6.0  # maior buraco sem voz aceito entre dois blocos
GANCHO_MAX_S = 5.0             # duracao maxima do gancho no modo "original"
CONTEXTO_ROTEIRO_FRASES = 6    # frases anteriores ao corte mostradas a IA

# Voz da narracao (ElevenLabs). A voz e so uma configuracao: trocar e mudar o id.
# George: voz pronta, grave, de contador de historias (vozes em portugues exigem plano pago).
VOZ_ID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
VOZ_MODELO = "eleven_multilingual_v2"
VOZ_IDIOMA = "pt"
PRECO_VOZ_USD_POR_CARACTERE = 0.00017   # estimativa (plano Starter); so para medir custo
PAUSA_ENTRE_BLOCOS_S = 0.15             # respiro minimo entre dois blocos de voz

# Preco em dolares por 1 milhao de tokens (entrada, saida). Serve so para estimar custo.
PRECOS_USD_POR_MILHAO = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}

# Postagem (Fase 5).
URL_PAINEL = os.getenv("CANAL_URL_PAINEL", "http://127.0.0.1:8000")   # base dos enderecos de retorno do login
FUSO = os.getenv("CANAL_FUSO", "America/Sao_Paulo")                 # horarios da agenda sao mostrados neste fuso
VERSAO_META = "v27.0"                                                # versao da API da Meta (Instagram e Facebook)

# Valores padrao das configuracoes por usuario. O banco guarda so o que o usuario mudou.
CONFIG_PADRAO = {
    "cortes_min": 3,
    "cortes_max": 5,
    "duracao_min_s": 20,
    "duracao_max_s": 75,
    "nota_minima_narracao": 70,
    # Postagem
    # Ritmo inicial de cada conta nova, por rede (posts por dia). Somados dao ~13 posts/dia, dentro da
    # meta de 10 a 20, sem saturar nenhuma conta (acima de ~6 por dia na mesma conta os videos disputam publico).
    "posts_dia_youtube": 4,
    "posts_dia_instagram": 3,
    "posts_dia_facebook": 3,
    "posts_dia_tiktok": 3,
    "intervalo_minimo_min": 120,   # minutos minimos entre dois posts da mesma conta
    "janela_inicio": 11,           # primeira hora do dia em que posta (fuso local): pega o almoco...
    "janela_fim": 23,              # ...o fim de tarde e o pico da noite (ultima hora, exclusiva)
    "modo_automatico": 0,          # 1: aprova e agenda sozinho os cortes com nota alta (desligado por padrao)
    "nota_minima_automatico": 80,  # nota minima para o modo automatico aprovar um corte
    # Busca diaria
    "busca_ativa": 0,              # 1: busca sozinha todo dia e manda os melhores para a fila (gasta creditos de IA)
    "busca_hora": 6,               # hora do dia (fuso local) em que a busca roda
    "busca_janela_h": 48,          # so entram videos postados nas ultimas N horas
    "meta_cortes_dia": 15,         # quantos cortes novos por dia a busca tenta gerar
    "apagar_brutos_dias": 7,       # videos baixados mais velhos que isso saem do disco (cortes ficam)
}


def garantir_pastas() -> None:
    """Cria as pastas de dados que ainda nao existem."""
    for pasta in (PASTA_BRUTOS, PASTA_CORTES, PASTA_TRANSCRICOES, PASTA_NARRACOES, PASTA_BIBLIOTECA, PASTA_LOGS):
        pasta.mkdir(parents=True, exist_ok=True)


def caminho_relativo(caminho: Path) -> str:
    """Converte um caminho dentro de dados/ para o texto guardado no banco.

    O banco guarda caminhos relativos e com barra normal, para o mesmo banco
    funcionar no Windows e no Linux.
    """
    return Path(caminho).resolve().relative_to(PASTA_DADOS.resolve()).as_posix()


def caminho_absoluto(texto: str) -> Path:
    """Converte o texto guardado no banco de volta para um caminho real."""
    return PASTA_DADOS / Path(texto)


def criar_log(nome: str) -> logging.Logger:
    """Devolve um log que escreve na tela e em dados/logs/canal.log."""
    raiz = logging.getLogger("canal")
    if not raiz.handlers:
        PASTA_LOGS.mkdir(parents=True, exist_ok=True)
        formato = logging.Formatter("%(asctime)s [%(name)s] %(message)s", "%d/%m %H:%M:%S")
        tela = logging.StreamHandler()
        tela.setFormatter(formato)
        PASTA_LOGS.mkdir(parents=True, exist_ok=True)
        # Ate 5 arquivos de 5 MB: o log nunca enche o disco da VPS.
        arquivo = logging.handlers.RotatingFileHandler(PASTA_LOGS / "canal.log", maxBytes=5_000_000,
                                                       backupCount=4, encoding="utf-8")
        arquivo.setFormatter(formato)
        raiz.addHandler(tela)
        raiz.addHandler(arquivo)
        raiz.setLevel(logging.INFO)
    return raiz.getChild(nome) if nome != "canal" else raiz


if __name__ == "__main__":
    garantir_pastas()
    print("Raiz do projeto:", RAIZ)
    print("Pasta de dados: ", PASTA_DADOS)
    print("Banco:          ", ARQUIVO_BANCO)
    print("Prompts:        ", PASTA_PROMPTS)
    print("Chave Anthropic:", "configurada" if os.getenv("ANTHROPIC_API_KEY") else "FALTANDO no .env")
