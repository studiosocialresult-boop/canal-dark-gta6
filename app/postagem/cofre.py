"""Cofre: criptografa os acessos (tokens) das contas antes de guardar no banco.

A chave fica no .env (CANAL_CHAVE_SECRETA). Se nao existir, e criada e gravada
la na primeira vez. Sem a chave certa, as credenciais guardadas nao abrem e as
contas precisam ser conectadas de novo (nunca quebra o resto do painel).
"""
import json
import os
import threading

from cryptography.fernet import Fernet, InvalidToken
from dotenv import dotenv_values

from app import config

_trava = threading.Lock()


class ErroCofre(Exception):
    """As credenciais guardadas nao puderam ser abertas (chave diferente ou dado corrompido)."""


def _chave() -> bytes:
    with _trava:
        chave = os.getenv("CANAL_CHAVE_SECRETA")
        arquivo = config.RAIZ / ".env"
        if not chave and arquivo.exists():
            # outro processo (ex.: o painel e um comando no terminal) pode ter criado a chave depois que
            # este programa leu o .env: rele antes de criar outra, senao as contas salvas nao abririam.
            chave = dotenv_values(arquivo).get("CANAL_CHAVE_SECRETA")
            if chave:
                os.environ["CANAL_CHAVE_SECRETA"] = chave
        if not chave:
            chave = Fernet.generate_key().decode()
            conteudo = arquivo.read_text(encoding="utf-8") if arquivo.exists() else ""
            separador = "" if conteudo.endswith("\n") or not conteudo else "\n"
            arquivo.write_text(conteudo + separador +
                               "# Chave que criptografa os acessos das contas (nao apague).\n"
                               f"CANAL_CHAVE_SECRETA={chave}\n", encoding="utf-8")
            os.environ["CANAL_CHAVE_SECRETA"] = chave
        return chave.encode()


def guardar(dados: dict) -> str:
    """Transforma as credenciais em texto criptografado."""
    return Fernet(_chave()).encrypt(json.dumps(dados).encode()).decode()


def abrir(texto: str) -> dict:
    """Abre as credenciais guardadas. Levanta ErroCofre se nao der."""
    try:
        return json.loads(Fernet(_chave()).decrypt(texto.encode()))
    except (InvalidToken, ValueError) as erro:
        raise ErroCofre("Não consegui abrir o acesso desta conta. Conecte a conta de novo.") from erro
