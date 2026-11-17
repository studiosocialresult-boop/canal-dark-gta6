"""Mostra a previa da escalacao do modo automatico com os dados reais da VPS, sem agendar nada.

Leva o app/ e o prompts/ deste computador para uma pasta temporaria na VPS, faz uma copia (so leitura) do banco,
aponta para a pasta de cortes de verdade, roda `python -m app.postagem.escalacao` e apaga tudo no fim.
Nao mexe no painel que esta rodando, nao reinicia o servico e nao altera o banco de verdade.

Rodar (ou dar dois cliques em ver_escalacao_vps.bat):
    .venv\\Scripts\\python.exe deploy\\previa_escalacao_vps.py
"""
import sys
import tarfile
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from deploy import publicar  # noqa: E402

PASTA_REMOTA = "/tmp/canal-previa"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    destino, chave = publicar._ambiente()
    pacote = Path(tempfile.gettempdir()) / "canal-previa.tar"
    with tarfile.open(pacote, "w") as tar:
        for pasta in ("app", "prompts"):
            tar.add(RAIZ / pasta, arcname=pasta, filter=lambda t: None if "__pycache__" in t.name else t)
    try:
        publicar._enviar(destino, chave, pacote, f"{PASTA_REMOTA}.tar")
    finally:
        pacote.unlink(missing_ok=True)
    copia_do_banco = ("import os, sqlite3; "
                      "o = sqlite3.connect('file:' + os.path.expanduser('~/canal-dark/dados/canal.db') + '?mode=ro', uri=True); "
                      "d = sqlite3.connect('dados/canal.db'); o.backup(d); d.close(); o.close()")
    comando = (
        f"trap 'rm -rf {PASTA_REMOTA} {PASTA_REMOTA}.tar' EXIT; set -e; "
        f"rm -rf {PASTA_REMOTA}; mkdir -p {PASTA_REMOTA}/dados; cd {PASTA_REMOTA}; tar -xf {PASTA_REMOTA}.tar; "
        f"~/canal-dark/.venv/bin/python -c \"{copia_do_banco}\"; "
        "ln -s ~/canal-dark/dados/cortes dados/cortes; "
        f"CANAL_PASTA_DADOS={PASTA_REMOTA}/dados ~/canal-dark/.venv/bin/python -m app.postagem.escalacao 2>&1 "
        "| grep -v '\\[canal'"
    )
    publicar._ssh(destino, chave, comando)


if __name__ == "__main__":
    try:
        main()
    except publicar.Falha as erro:
        print("Não deu certo:", erro)
        sys.exit(1)
