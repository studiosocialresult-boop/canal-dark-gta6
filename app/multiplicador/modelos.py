"""Modelos de template: os 3 layouts e as configuracoes que o assistente edita.

Um template e um layout (post, meme ou viral) mais uma configuracao: perfil da
pagina, estilo do texto e como cada video se encaixa na zona de video. A
configuracao salva guarda so o que o dono mudou; o resto vem dos padroes daqui.
"""
import copy

LARGURA, ALTURA = 1080, 1920

LAYOUTS = {
    # Tela cheia: o video ocupa tudo, sem frase nem perfil. Usado pela tela Editor (fica fora das listas de layouts).
    "cheio": {
        "nome": "Tela cheia (Editor)",
        "descricao": "O vídeo ocupa a tela inteira, só com o enquadramento ajustado.",
        "perfil_padrao": None, "mostra_perfil": False, "zonas_de_video": 1, "alinhamento_padrao": "centro",
        "oculto": True,
    },
    "post": {
        "nome": "Post de rede social",
        "descricao": "Foto e nome da página no topo, a frase logo abaixo e o vídeo ocupando o resto.",
        "perfil_padrao": "topo", "mostra_perfil": True, "zonas_de_video": 1, "alinhamento_padrao": "esquerda",
    },
    "meme": {
        "nome": "Meme / notícia",
        "descricao": "A frase em destaque no topo, o vídeo no meio e a foto e o nome da página no rodapé.",
        "perfil_padrao": "base", "mostra_perfil": True, "zonas_de_video": 1, "alinhamento_padrao": "centro",
    },
    "viral": {
        "nome": "Vídeo viral (tela dividida)",
        "descricao": "Um vídeo em cima, a frase em uma faixa no meio e outro vídeo embaixo.",
        "perfil_padrao": None, "mostra_perfil": False, "zonas_de_video": 2, "alinhamento_padrao": "centro",
    },
}

CONFIG_PADRAO = {
    "perfil": {
        "mostrar": None,            # None: o layout decide
        "nome": "Seu Nome",
        "handle": "seunome",
        "avatar": None,             # caminho dentro de dados/ (ou None: usa a inicial do nome)
        "tema": "escuro",           # escuro ou claro
        "alinhamento": None,        # esquerda, centro ou direita; None: o layout decide
        "posicao": None,            # topo ou base; None: o layout decide
        "tam_avatar": 110,
        "fonte_nome": 40,
        "fonte_handle": 32,
    },
    "texto": {
        "tamanho": 64,              # tamanho maximo da fonte da frase (diminui sozinho se nao couber)
        "cor": None,                # "#rrggbb"; None: automatica pelo tema
        "espaco_lateral": 64,
        "entrelinha": 1.18,
        "faixa_minima": 0,          # altura minima da faixa da frase (0: automatica)
    },
    "video": {
        "fundo": "desfocado",       # desfocado ou solido: o que aparece atras do video quando ele "cabe"
    },
}

CORES = {
    "escuro": {"fundo": (0, 0, 0), "texto": (255, 255, 255), "suave": (150, 154, 168)},
    "claro": {"fundo": (255, 255, 255), "texto": (16, 17, 22), "suave": (96, 100, 114)},
}


def config_completa(salva: dict | None) -> dict:
    """Junta a configuracao salva com os padroes (so o que foi mudado fica guardado)."""
    resultado = copy.deepcopy(CONFIG_PADRAO)
    for secao, valores in (salva or {}).items():
        if secao in resultado and isinstance(valores, dict):
            resultado[secao].update(valores)
    return resultado


def perfil_visivel(layout: str, config: dict) -> bool:
    escolha = config["perfil"]["mostrar"]
    return LAYOUTS[layout]["mostra_perfil"] if escolha is None else bool(escolha)


def posicao_do_perfil(layout: str, config: dict) -> str:
    return config["perfil"]["posicao"] or LAYOUTS[layout]["perfil_padrao"] or "base"


def alinhamento(layout: str, config: dict) -> str:
    return config["perfil"]["alinhamento"] or LAYOUTS[layout]["alinhamento_padrao"]


def layouts_visiveis() -> dict:
    """Os layouts que o dono escolhe no assistente (o de tela cheia e so do Editor)."""
    return {k: v for k, v in LAYOUTS.items() if not v.get("oculto")}
