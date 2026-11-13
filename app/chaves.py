"""Chaves e integracoes: o painel grava as chaves no .env de onde ele roda (na VPS, o .env da VPS).

O painel nunca devolve o valor de uma chave, so se ela esta preenchida. Na publicacao
(deploy/publicar.py), as chaves que ja existem na VPS sao mantidas: quem manda nelas e o painel.

Este arquivo so usa a biblioteca padrao no topo, para o `juntar` rodar na VPS mesmo antes
do ambiente Python do projeto existir.

Rodar sozinho (na VPS, chamado pelo publicar.py):
    python3 -m app.chaves juntar <env novo> <env atual>
"""
import os
import re
import sys
import threading
from pathlib import Path

# (nome no .env, grupo, rotulo, ajuda, formato aceito)
_TOKEN = r"[A-Za-z0-9_\-:.\/+=~]{4,500}"
CHAVES = [
    ("ANTHROPIC_API_KEY", "IA e voz", "Chave da Anthropic", "A IA que escolhe os cortes e escreve as narrações.", _TOKEN),
    ("ELEVENLABS_API_KEY", "IA e voz", "Chave da ElevenLabs", "Grava a voz das narrações.", _TOKEN),
    ("TELEGRAM_BOT_TOKEN", "Avisos no Telegram", "Token do robô", "O BotFather manda este token quando você cria o robô.", _TOKEN),
    ("TELEGRAM_CHAT_ID", "Avisos no Telegram", "Conversa", "Preenchida sozinha pelo botão “Descobrir conversa”.", r"-?\d{1,20}"),
    ("YOUTUBE_CLIENT_ID", "YouTube", "ID do cliente (Client ID)", "Do Google Cloud: Credenciais → ID do cliente OAuth.", _TOKEN),
    ("YOUTUBE_CLIENT_SECRET", "YouTube", "Chave secreta do cliente (Client secret)", "Aparece junto com o ID do cliente.", _TOKEN),
    ("META_APP_ID", "Instagram e Facebook", "ID do app", "Do painel de desenvolvedores da Meta.", r"\d{5,25}"),
    ("META_APP_SECRET", "Instagram e Facebook", "Chave secreta do app", "Configurações do app → Básico.", _TOKEN),
    ("TIKTOK_CLIENT_KEY", "TikTok", "Client key", "Do portal de desenvolvedores do TikTok.", _TOKEN),
    ("TIKTOK_CLIENT_SECRET", "TikTok", "Client secret", "Aparece junto com a client key.", _TOKEN),
]
NOMES = {c[0] for c in CHAVES}
# Na publicacao, estas nunca sao trocadas se a VPS ja tiver valor. A chave do cofre entra aqui porque,
# se mudar, as contas conectadas na VPS deixam de abrir.
MANTER_NA_VPS = NOMES | {"CANAL_CHAVE_SECRETA"}

_trava = threading.Lock()


class ErroChave(Exception):
    """Valor recusado (a mensagem ja e para o dono)."""


def _arquivo() -> Path:
    from app import config
    return config.RAIZ / ".env"


def limpar(nome: str, valor: str) -> str:
    """Tira espacos e aspas que vem junto no copiar e colar e confere o formato."""
    if nome not in NOMES:
        raise ErroChave("Chave desconhecida.")
    valor = (valor or "").strip().strip("\"'").strip()
    formato = next(c[4] for c in CHAVES if c[0] == nome)
    if not re.fullmatch(formato, valor):
        raise ErroChave("Esse valor não parece certo. Copie de novo, sem espaços nem quebras de linha.")
    return valor


def _ler_linhas(arquivo: Path) -> list[str]:
    return arquivo.read_text(encoding="utf-8").splitlines() if arquivo.exists() else []


def _gravar(arquivo: Path, linhas: list[str]) -> None:
    temporario = arquivo.with_name(arquivo.name + ".novo")
    temporario.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(temporario, 0o600)
    os.replace(temporario, arquivo)


def salvar(nome: str, valor: str | None, arquivo: Path | None = None) -> None:
    """Grava (ou apaga, com valor vazio) uma chave no .env e ja passa a valer no painel."""
    arquivo = arquivo or _arquivo()
    if valor:
        valor = limpar(nome, valor)
    elif nome not in NOMES:
        raise ErroChave("Chave desconhecida.")
    with _trava:
        linhas = [l for l in _ler_linhas(arquivo) if not l.startswith(f"{nome}=")]
        if valor:
            linhas.append(f"{nome}={valor}")
        _gravar(arquivo, linhas)
        if valor:
            os.environ[nome] = valor
        else:
            os.environ.pop(nome, None)


def estado() -> list[dict]:
    """Lista para a tela: nome, grupo, rotulo, ajuda e se esta preenchida (nunca o valor)."""
    return [{"nome": n, "grupo": g, "rotulo": r, "ajuda": a, "preenchida": bool(os.getenv(n))}
            for n, g, r, a, _f in CHAVES]


def _valores(linhas: list[str]) -> dict[str, str]:
    valores = {}
    for linha in linhas:
        if "=" in linha and not linha.lstrip().startswith("#"):
            nome, valor = linha.split("=", 1)
            valores[nome.strip()] = valor.strip()
    return valores


def juntar(novo: Path, atual: Path) -> list[str]:
    """Junta o .env vindo do computador (novo) com o da VPS (atual) e grava em `atual`.
    As chaves de MANTER_NA_VPS que ja tem valor na VPS ficam como estao. Devolve os nomes mantidos."""
    linhas_novas = _ler_linhas(novo)
    da_vps = {n: v for n, v in _valores(_ler_linhas(atual)).items() if n in MANTER_NA_VPS and v}
    mantidas = sorted(da_vps)
    resultado = [l for l in linhas_novas if l.split("=", 1)[0].strip() not in da_vps]
    resultado += [f"{n}={v}" for n, v in sorted(da_vps.items())]
    _gravar(atual, resultado)
    return mantidas


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "juntar":
        mantidas = juntar(Path(sys.argv[2]), Path(sys.argv[3]))
        print(f"   .env da VPS atualizado ({len(mantidas)} chave(s) mantida(s) como estavam na VPS).")
    else:
        print("Uso: python3 -m app.chaves juntar <env novo> <env atual>")
        sys.exit(1)
