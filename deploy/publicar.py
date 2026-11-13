"""Publica o Canal Dark na VPS a partir deste computador.

Leva o codigo (a ultima versao salva no git), o .env e o cookies.txt e reinstala o servico.
As chaves que ja existem no .env da VPS (ex.: colocadas pela tela Configuracoes) nao sao trocadas.
Com --levar-dados, leva tambem o banco, os cortes, os templates e a biblioteca (feito uma vez,
na mudanca para a VPS) e transforma o painel deste computador em painel de testes.

Uso (ou os arquivos .bat na pasta do projeto):
    python deploy/publicar.py                 atualiza o programa na VPS
    python deploy/publicar.py --levar-dados   primeira vez: leva tambem os dados
    python deploy/publicar.py --cookies       so troca o cookies.txt (quando o YouTube pedir login de novo)
    python deploy/publicar.py --logs          mostra as ultimas linhas do log da VPS

Precisa de CANAL_VPS (ex.: ubuntu@1.2.3.4) e CANAL_VPS_CHAVE (arquivo da chave SSH) no .env.
"""
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import closing
from pathlib import Path

from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parent.parent
PASTA_REMOTA = "canal-dark"                 # dentro da pasta do usuario na VPS
# Linhas do .env que valem so neste computador.
SO_NO_COMPUTADOR = ("CANAL_PAINEL_DE_TESTE=", "CANAL_URL_PAINEL=", "CANAL_VPS=", "CANAL_VPS_CHAVE=",
                    "CANAL_PASTA_DADOS=", "CANAL_COOKIES=")
# Dentro de dados/: o que nao vai para a VPS (videos brutos sao baixados de novo se precisar).
DADOS_FORA = {"brutos", "tmp", "logs", "canal.db", "canal.db-journal", "canal.db-wal", "canal.db-shm"}


class Falha(Exception):
    pass


def _ambiente() -> tuple[str, Path]:
    valores = dotenv_values(RAIZ / ".env")
    destino, chave = valores.get("CANAL_VPS"), valores.get("CANAL_VPS_CHAVE")
    if not destino or not chave:
        raise Falha("Faltam CANAL_VPS e CANAL_VPS_CHAVE no arquivo .env.")
    chave = Path(chave).expanduser()
    if not chave.exists():
        raise Falha(f"Não achei a chave SSH em {chave}.")
    return destino, chave


def _ssh(destino: str, chave: Path, comando: str, mostrar: bool = True) -> str:
    resultado = subprocess.run(
        ["ssh", "-i", str(chave), "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", destino, comando],
        capture_output=not mostrar, text=True, encoding="utf-8", errors="replace")
    if resultado.returncode != 0:
        raise Falha(f"O comando na VPS falhou: {comando.split()[0]}")
    return resultado.stdout or ""


def _enviar(destino: str, chave: Path, local: Path, remoto: str) -> None:
    resultado = subprocess.run(
        ["scp", "-q", "-i", str(chave), "-o", "BatchMode=yes", str(local), f"{destino}:{remoto}"],
        capture_output=True, text=True)
    if resultado.returncode != 0:
        raise Falha(f"Não consegui enviar {local.name} para a VPS.")


def _env_para_vps(pasta: Path) -> Path:
    linhas = (RAIZ / ".env").read_text(encoding="utf-8").splitlines()
    arquivo = pasta / "env"
    arquivo.write_text("\n".join(l for l in linhas if not l.startswith(SO_NO_COMPUTADOR)) + "\n", encoding="utf-8")
    return arquivo


def _pacote_do_codigo(pasta: Path) -> Path:
    mudancas = subprocess.run(["git", "status", "--porcelain"], cwd=RAIZ, capture_output=True, text=True).stdout
    if mudancas.strip():
        print("Atenção: há mudanças não salvas no git. Só vai para a VPS o que já foi salvo (commit).")
    arquivo = pasta / "codigo.tar"
    resultado = subprocess.run(["git", "archive", "--format=tar", "-o", str(arquivo), "HEAD"], cwd=RAIZ,
                               capture_output=True, text=True)
    if resultado.returncode != 0:
        raise Falha("Não consegui empacotar o código (git archive).")
    return arquivo


def _pacote_dos_dados(pasta: Path) -> Path:
    """Copia o banco de forma segura (mesmo com o painel aberto) e empacota o resto de dados/."""
    dados = RAIZ / "dados"
    copia = pasta / "canal.db"
    # closing(): o "with" do sqlite3 sozinho nao fecha o arquivo, e o Windows nao deixa apagar arquivo aberto.
    with closing(sqlite3.connect(dados / "canal.db")) as origem, closing(sqlite3.connect(copia)) as destino:
        origem.backup(destino)
    arquivo = pasta / "dados.tar.gz"
    with tarfile.open(arquivo, "w:gz") as tar:
        tar.add(copia, arcname="canal.db")
        for item in dados.iterdir():
            if item.name not in DADOS_FORA:
                tar.add(item, arcname=item.name)
    return arquivo


def publicar(levar_dados: bool = False) -> None:
    destino, chave = _ambiente()
    remoto = f"~/{PASTA_REMOTA}"
    with tempfile.TemporaryDirectory() as tmp:
        pasta = Path(tmp)
        print("1/4 Empacotando o código…")
        codigo = _pacote_do_codigo(pasta)
        print("2/4 Enviando para a VPS…")
        _ssh(destino, chave, f"mkdir -p {remoto}/dados", mostrar=False)
        _enviar(destino, chave, codigo, "/tmp/canal-codigo.tar")
        # O .env nao e copiado por cima: as chaves que ja existem na VPS (colocadas pelo painel) ficam.
        _enviar(destino, chave, _env_para_vps(pasta), "/tmp/canal-env-novo")
        if (RAIZ / "cookies.txt").exists():
            _enviar(destino, chave, RAIZ / "cookies.txt", f"{remoto}/cookies.txt")
        # Troca o codigo antigo pelo novo (dados, .env, cookies e .venv ficam).
        _ssh(destino, chave, f"cd {remoto} && rm -rf app prompts deploy testes && tar -xf /tmp/canal-codigo.tar "
                             f"&& rm /tmp/canal-codigo.tar", mostrar=False)
        _ssh(destino, chave, f"cd {remoto} && python3 -m app.chaves juntar /tmp/canal-env-novo .env "
                             f"&& rm /tmp/canal-env-novo")
        if levar_dados:
            print("   Levando os dados (banco, cortes, templates, biblioteca)…")
            dados = _pacote_dos_dados(pasta)
            print(f"   {dados.stat().st_size / 1e6:.0f} MB")
            _enviar(destino, chave, dados, "/tmp/canal-dados.tar.gz")
            carimbo = time.strftime("%Y%m%d-%H%M%S")
            _ssh(destino, chave, f"sudo systemctl stop canal-dark 2>/dev/null; cd {remoto} && "
                                 f"if [ -f dados/canal.db ]; then mv dados dados_antes_{carimbo} && mkdir dados; fi && "
                                 f"tar -xzf /tmp/canal-dados.tar.gz -C dados && rm /tmp/canal-dados.tar.gz", mostrar=False)
        print("3/4 Instalando e reiniciando o serviço na VPS…")
        _ssh(destino, chave, f"cd {remoto} && bash deploy/instalar_vps.sh")
    if levar_dados:
        _virar_painel_de_teste()
    print("4/4 Pronto.")


def _virar_painel_de_teste() -> None:
    arquivo = RAIZ / ".env"
    texto = arquivo.read_text(encoding="utf-8")
    if "CANAL_PAINEL_DE_TESTE=1" not in texto:
        linhas = [l for l in texto.splitlines() if not l.startswith("CANAL_PAINEL_DE_TESTE=")]
        linhas.append("CANAL_PAINEL_DE_TESTE=1")
        arquivo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        print("   O painel deste computador agora é de testes (não publica nem faz a busca diária).")


def trocar_cookies() -> None:
    destino, chave = _ambiente()
    if not (RAIZ / "cookies.txt").exists():
        raise Falha("Não achei o cookies.txt na pasta do projeto.")
    _enviar(destino, chave, RAIZ / "cookies.txt", f"~/{PASTA_REMOTA}/cookies.txt")
    _ssh(destino, chave, f"chmod 600 ~/{PASTA_REMOTA}/cookies.txt && sudo systemctl restart canal-dark", mostrar=False)
    print("cookies.txt trocado na VPS e painel reiniciado.")


def ver_logs() -> None:
    destino, chave = _ambiente()
    _ssh(destino, chave, f"tail -n 60 ~/{PASTA_REMOTA}/dados/logs/canal.log; echo; systemctl is-active canal-dark")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if "--cookies" in sys.argv:
            trocar_cookies()
        elif "--logs" in sys.argv:
            ver_logs()
        else:
            publicar(levar_dados="--levar-dados" in sys.argv)
    except Falha as erro:
        print("Não deu certo:", erro)
        sys.exit(1)
