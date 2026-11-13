"""Download: baixa o video de origem a partir de um link (yt-dlp).

Rodar sozinho:
    python -m app.download.baixar "https://www.youtube.com/watch?v=..."
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app import config
from app.contratos import VideoBaixado

log = config.criar_log("download")

ID_YOUTUBE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def identificar(url: str) -> tuple[str, str]:
    """Descobre a plataforma e o id do video a partir do link, sem baixar nada."""
    partes = urlparse(url.strip())
    host = (partes.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    caminho = [p for p in partes.path.split("/") if p]

    if host == "youtu.be" and caminho:
        candidato = caminho[0]
    elif host in ("youtube.com", "music.youtube.com"):
        if caminho[:1] == ["watch"]:
            candidato = (parse_qs(partes.query).get("v") or [""])[0]
        elif caminho[:1] in (["shorts"], ["live"], ["embed"]) and len(caminho) > 1:
            candidato = caminho[1]
        else:
            candidato = ""
    else:
        candidato = ""

    if candidato:
        if not ID_YOUTUBE.match(candidato):
            raise ValueError("O link do YouTube nao tem um id de video valido.")
        return "youtube", candidato

    if host.endswith("instagram.com") and len(caminho) > 1 and caminho[0] in ("reel", "reels", "p", "tv"):
        return "instagram", caminho[1]
    if host.endswith("tiktok.com") and "video" in caminho:
        return "tiktok", caminho[caminho.index("video") + 1]
    raise ValueError("Link nao reconhecido. Por enquanto a ferramenta aceita links do YouTube.")


def baixar(url: str, pasta_destino: Path) -> VideoBaixado:
    """Baixa o video em mp4 (ate 1080p) e devolve os dados da fonte."""
    plataforma, id_externo = identificar(url)
    pasta_destino.mkdir(parents=True, exist_ok=True)
    modelo_arquivo = pasta_destino / f"{plataforma}_{id_externo}.%(ext)s"

    comando = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "--no-warnings",
        "--newline",
        "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--merge-output-format", "mp4",
        "-o", str(modelo_arquivo),
        "--print-json",
        "--no-simulate",
    ]
    if config.ARQUIVO_COOKIES.exists():
        comando += ["--cookies", str(config.ARQUIVO_COOKIES)]
        log.info("Usando o login do arquivo de cookies.")
    comando.append(url)
    if plataforma == "youtube" and shutil.which("deno") is None:
        log.warning("O Deno nao foi encontrado. Sem ele o YouTube costuma recusar o download. "
                    "Instale o Deno e abra um terminal novo.")
    log.info("Baixando %s %s...", plataforma, id_externo)
    resultado = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if resultado.returncode != 0:
        raise RuntimeError(_explicar_erro(resultado.stderr))

    info = _ler_json(resultado.stdout)
    caminho = pasta_destino / f"{plataforma}_{id_externo}.mp4"
    if not caminho.exists():
        raise RuntimeError("O download terminou, mas nao achei o arquivo mp4.")
    log.info("Download concluido: %s (%.0f MB).", caminho.name, caminho.stat().st_size / 1e6)

    return VideoBaixado(
        plataforma=plataforma,
        id_externo=id_externo,
        url=url,
        titulo=info.get("title") or "",
        canal=info.get("channel") or info.get("uploader") or "",
        duracao_s=float(info.get("duration") or 0),
        caminho=caminho,
    )


def _ler_json(saida: str) -> dict:
    for linha in reversed(saida.strip().splitlines()):
        linha = linha.strip()
        if linha.startswith("{"):
            try:
                return json.loads(linha)
            except json.JSONDecodeError:
                continue
    return {}


def _explicar_erro(erro: str) -> str:
    texto = erro.lower()
    if "confirm your age" in texto or "age-restricted" in texto:
        if config.ARQUIVO_COOKIES.exists():
            return ("O video tem restricao de idade e o YouTube nao liberou. Confira: (1) o Deno "
                    "esta instalado (rode verificar.py); (2) os cookies nao expiraram (exporte de "
                    "novo); (3) a conta e maior de 18.")
        return ("O video tem restricao de idade. Coloque o cookies.txt da conta secundaria "
                "na pasta do projeto para liberar.")
    if "sign in to confirm" in texto or "not a bot" in texto:
        return "O YouTube bloqueou o download (pediu confirmacao de que nao sou robo)."
    if "private video" in texto or "members-only" in texto:
        return "O video e privado ou exclusivo para membros."
    if "video unavailable" in texto or "has been removed" in texto:
        return "O video nao esta mais disponivel."
    if "live event will begin" in texto or "is live" in texto:
        return "Este video e uma live em andamento. Espere ela terminar."
    ultima = (erro.strip().splitlines() or ["erro desconhecido"])[-1]
    return f"O download falhou: {ultima[:200]}"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Uso: python -m app.download.baixar "link do video"')
        sys.exit(1)
    config.garantir_pastas()
    try:
        _video = baixar(sys.argv[1], config.PASTA_BRUTOS)
    except (ValueError, RuntimeError) as _erro:
        print("Nao deu certo:", _erro)
        sys.exit(1)
    print("Titulo :", _video.titulo)
    print("Canal  :", _video.canal)
    print("Duracao:", _video.duracao_s, "s")
    print("Arquivo:", _video.caminho)
