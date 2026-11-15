"""Redes: o que e comum a todos os conectores de postagem (erros, resultado, limites de cada rede).

Limites conferidos na documentacao oficial em 13/11/2026 (detalhes no plano.md, Fase 5).
- limite_diario: o teto TECNICO da rede por conta em 24 h. O agendador usa um freio bem menor (o dobro da meta
  da conta, ver agendador.limite_seguro), para um defeito nunca chegar perto dele.
- rampa: posts por dia de uma conta nova nas semanas 1-2 e 3-4; da 5a semana em diante vale a meta da conta.
"""
from dataclasses import dataclass, field

import requests

REDES = {
    "youtube": {"nome": "YouTube Shorts", "chaves_env": ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"),
                "limite_diario": 100, "duracao_min_s": 1, "duracao_max_s": 180, "automatico": True,
                "legenda_max": 5000, "rampa": (2, 3)},
    "instagram": {"nome": "Instagram Reels", "chaves_env": ("META_APP_ID", "META_APP_SECRET"),
                  "limite_diario": 50, "duracao_min_s": 3, "duracao_max_s": 900, "automatico": True,
                  "legenda_max": 2200, "rampa": (1, 2)},
    "facebook": {"nome": "Facebook Reels", "chaves_env": ("META_APP_ID", "META_APP_SECRET"),
                 "limite_diario": 30, "duracao_min_s": 3, "duracao_max_s": 90, "automatico": True,
                 "legenda_max": 2200, "rampa": (1, 2)},
    # TikTok: as regras exigem que o dono escolha a privacidade e confirme cada post. Por isso nunca entra
    # no modo automatico. Sem auditoria do app, so publica como privado (SELF_ONLY) em conta privada.
    "tiktok": {"nome": "TikTok", "chaves_env": ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
               "limite_diario": 15, "duracao_min_s": 3, "duracao_max_s": 600, "automatico": False,
               "legenda_max": 2200, "rampa": (1, 2)},
}

TEMPO_LIMITE = 60          # segundos de espera por resposta (fora o envio do arquivo)
TEMPO_LIMITE_ENVIO = 600   # segundos para enviar um pedaco do video


class ErroPostagem(Exception):
    """A rede recusou ou falhou.

    temporario: vale tentar de novo mais tarde (rede fora do ar, limite por minuto).
    reconectar: o acesso venceu ou foi retirado; a conta precisa ser conectada de novo.
    """

    def __init__(self, mensagem: str, *, temporario: bool = False, reconectar: bool = False):
        super().__init__(mensagem)
        self.temporario = temporario
        self.reconectar = reconectar


@dataclass
class Resultado:
    """O que a rede devolveu depois de publicar."""
    id_externo: str
    url: str | None = None
    observacao: str | None = None


@dataclass
class Numeros:
    """Numeros de um post lidos na rede. None = a rede nao informa (diferente de zero)."""
    visualizacoes: int | None = None
    curtidas: int | None = None
    comentarios: int | None = None


@dataclass
class Credenciais:
    """O que fica guardado (criptografado) para cada conta."""
    dados: dict = field(default_factory=dict)
    mudou: bool = False          # o conector renovou o token: precisa guardar de novo

    def __getitem__(self, chave):
        return self.dados[chave]

    def get(self, chave, padrao=None):
        return self.dados.get(chave, padrao)

    def atualizar(self, **valores) -> None:
        self.dados.update(valores)
        self.mudou = True


def configurada(rede: str) -> bool:
    """O app desta rede foi cadastrado (as chaves estao no .env)?"""
    import os
    return all(os.getenv(chave) for chave in REDES[rede]["chaves_env"])


def chamar(metodo: str, url: str, *, rede: str, **kwargs) -> requests.Response:
    """Faz a chamada HTTP e traduz falhas de conexao e respostas 5xx/429 em ErroPostagem temporario."""
    kwargs.setdefault("timeout", TEMPO_LIMITE)
    try:
        resposta = requests.request(metodo, url, **kwargs)
    except requests.RequestException as erro:
        raise ErroPostagem(f"Sem conexão com {REDES[rede]['nome']} ({type(erro).__name__}).", temporario=True) from erro
    if resposta.status_code == 429 or resposta.status_code >= 500:
        raise ErroPostagem(f"{REDES[rede]['nome']} está ocupado ou fora do ar (erro {resposta.status_code}). "
                           "Vou tentar de novo.", temporario=True)
    return resposta


def json_ou_vazio(resposta: requests.Response) -> dict:
    try:
        return resposta.json()
    except ValueError:
        return {}
