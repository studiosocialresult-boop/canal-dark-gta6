"""Avisos no Telegram: o painel manda uma mensagem quando algo falha (ou quando a busca do dia termina).

So funciona com CANAL_AVISOS=1 (ligado na VPS; no computador fica desligado para nao avisar em dobro)
e com TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env. Sem isso, nao faz nada e nunca quebra o resto.
O token nunca aparece em log nem em mensagem de erro.

Rodar sozinho:
    python -m app.avisos descobrir   -> depois de mandar "oi" para o seu robo, grava o TELEGRAM_CHAT_ID no .env
    python -m app.avisos testar      -> manda uma mensagem de teste
"""
import os
import sys
import threading
import time

import requests

from app import config

log = config.criar_log("avisos")

REPETIR_DEPOIS_S = 3 * 3600        # a mesma mensagem nao e repetida antes disso
_enviados: dict[str, float] = {}
_trava = threading.Lock()


def ligado() -> bool:
    return (os.getenv("CANAL_AVISOS") == "1" and bool(os.getenv("TELEGRAM_BOT_TOKEN"))
            and bool(os.getenv("TELEGRAM_CHAT_ID")))


def _enviar(texto: str) -> bool:
    try:
        resposta = requests.post(
            f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
            json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": texto[:3900], "disable_web_page_preview": True},
            timeout=15)
    except requests.RequestException:
        log.warning("Aviso: o Telegram nao respondeu.")          # sem detalhes: a URL leva o token
        return False
    if resposta.status_code != 200:
        log.warning("Aviso: o Telegram recusou a mensagem (codigo %d).", resposta.status_code)
        return False
    return True


def avisar(texto: str, chave: str | None = None, esperar: bool = False) -> bool:
    """Manda `texto` no Telegram (em segundo plano). `chave` evita repetir o mesmo aviso por 3 horas.
    Devolve False se os avisos estao desligados ou se a mensagem foi repetida."""
    if not ligado():
        return False
    chave = chave or texto
    with _trava:
        if time.time() - _enviados.get(chave, 0) < REPETIR_DEPOIS_S:
            return False
        _enviados[chave] = time.time()
    if esperar:
        return _enviar(texto)
    threading.Thread(target=_enviar, args=(texto,), name="aviso", daemon=True).start()
    return True


def descobrir_chat() -> str:
    """Le a ultima mensagem mandada ao robo e grava o id da conversa no .env."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Falta o TELEGRAM_BOT_TOKEN no arquivo .env.")
    try:
        dados = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
    except (requests.RequestException, ValueError):
        raise SystemExit("O Telegram nao respondeu. Confira o token e a internet.")
    if not dados.get("ok"):
        raise SystemExit("O Telegram recusou o token. Confira se copiou ele inteiro.")
    conversas = [u["message"]["chat"]["id"] for u in dados.get("result", []) if "message" in u]
    if not conversas:
        raise SystemExit("Nenhuma mensagem encontrada. Abra o seu robo no Telegram, mande 'oi' e rode de novo.")
    chat = str(conversas[-1])
    arquivo = config.RAIZ / ".env"
    linhas = [l for l in arquivo.read_text(encoding="utf-8").splitlines() if not l.startswith("TELEGRAM_CHAT_ID=")]
    linhas.append(f"TELEGRAM_CHAT_ID={chat}")
    arquivo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    os.environ["TELEGRAM_CHAT_ID"] = chat
    return chat


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    acao = sys.argv[1] if len(sys.argv) > 1 else ""
    if acao == "descobrir":
        descobrir_chat()
        print("Pronto: a conversa foi gravada no .env (TELEGRAM_CHAT_ID).")
    elif acao == "testar":
        os.environ["CANAL_AVISOS"] = "1"
        ok = avisar("✅ Canal Dark: os avisos estão funcionando.", chave=f"teste-{time.time()}", esperar=True)
        print("Mensagem enviada." if ok else "Não deu certo: confira o token e o TELEGRAM_CHAT_ID no .env.")
        sys.exit(0 if ok else 1)
    else:
        print("Uso: python -m app.avisos descobrir | testar")
        sys.exit(1)
