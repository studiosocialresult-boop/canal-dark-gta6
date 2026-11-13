"""Perfil: lista os videos de um canal do YouTube para a tela Perfis.

Usa o yt-dlp para listar (titulo, visualizacoes, duracao) e le a data de
publicacao na pagina de cada um dos videos mais recentes, o que permite
calcular a velocidade (visualizacoes por hora). Nao precisa de chave de API.

Fica isolado neste modulo de proposito: Instagram e TikTok dependem de coleta
nao oficial, que muda toda hora; quando entrarem, serao outros modulos ao lado
deste, sem mexer no resto.

Rodar sozinho:
    python -m app.busca.perfil @nomedocanal
"""
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from app import config

ABAS = ("videos", "shorts")
LIMITE_PADRAO = 36
COM_DATA = 15          # quantos dos mais recentes tem a data lida (cada um e uma consulta)
VALIDADE_CACHE_S = 600
_cache: dict = {}

CABECALHOS = {"Accept-Language": "en-US,en;q=0.9", "User-Agent": "Mozilla/5.0"}


class ErroPerfil(Exception):
    """Nao foi possivel listar este perfil (a mensagem ja e para o dono)."""


@dataclass
class Post:
    id: str
    titulo: str
    url: str
    views: int | None
    duracao_s: float | None
    publicado: str | None        # ISO 8601 (so os mais recentes tem)
    miniatura: str
    velocidade: float | None     # visualizacoes por hora
    ordem: int                   # 0 = o mais novo da lista


def normalizar_alvo(texto: str) -> str:
    """Transforma '@canal' ou o link de um canal no endereco base do canal."""
    texto = (texto or "").strip()
    if not texto:
        raise ErroPerfil("Cole o @ ou o link do canal.")
    if re.fullmatch(r"@[\w.\-]{2,60}", texto):
        return f"https://www.youtube.com/{texto}"
    if "://" not in texto and re.match(r"^(www\.)?youtube\.com/", texto):
        texto = "https://" + texto
    url = urlparse(texto)
    if url.hostname not in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        raise ErroPerfil("Por enquanto a análise de perfis funciona só com canais do YouTube. "
                         "Instagram e TikTok chegam depois.")
    partes = [p for p in url.path.split("/") if p]
    if not partes or partes[0] in ("watch", "shorts", "live", "embed"):
        raise ErroPerfil("Esse é o link de um vídeo. Cole o link do canal (ele começa com youtube.com/@…).")
    if partes[0].startswith("@"):
        return f"https://www.youtube.com/{partes[0]}"
    if partes[0] in ("channel", "c", "user") and len(partes) >= 2:
        return f"https://www.youtube.com/{partes[0]}/{partes[1]}"
    raise ErroPerfil("Não reconheci esse link de canal. Use o @ do canal (ex.: @nomedocanal).")


def _yt_dlp(args: list[str], timeout: int = 150) -> str:
    comando = [sys.executable, "-m", "yt_dlp", "--no-warnings", *args]
    if config.ARQUIVO_COOKIES.exists():
        comando[4:4] = ["--cookies", str(config.ARQUIVO_COOKIES)]
    try:
        resultado = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ErroPerfil("O YouTube demorou demais para responder. Tente de novo em instantes.")
    if resultado.returncode != 0:
        erro = resultado.stderr.lower()
        if "does not exist" in erro or "404" in erro or "not found" in erro or "unavailable" in erro:
            raise ErroPerfil("Não achei esse canal. Confira o @ ou o link.")
        if "sign in" in erro or "not a bot" in erro:
            raise ErroPerfil("O YouTube pediu login. Confira o cookies.txt (Configurações mostra o estado).")
        raise ErroPerfil("Não consegui ler esse canal agora. Tente de novo em instantes.")
    return resultado.stdout


def _data_do_video(video_id: str) -> str | None:
    """Data de publicacao (ISO) lida na pagina do video. None se nao deu (so some a velocidade)."""
    try:
        resposta = requests.get(f"https://www.youtube.com/watch?v={video_id}", headers=CABECALHOS, timeout=20)
        achou = (re.search(r'itemprop="datePublished" content="([^"]+)"', resposta.text)
                 or re.search(r'"publishDate":"([^"]+)"', resposta.text))
    except requests.RequestException:
        return None
    return achou.group(1) if achou else None


def _datas(ids: list[str]) -> dict[str, str]:
    """Le as datas de varios videos ao mesmo tempo."""
    if not ids:
        return {}
    with ThreadPoolExecutor(max_workers=6) as grupo:
        return {i: d for i, d in zip(ids, grupo.map(_data_do_video, ids)) if d}


def velocidade(views: int | None, publicado: str | None, agora: datetime | None = None) -> float | None:
    """Visualizacoes por hora desde a publicacao (minimo de 1 hora, para nao explodir no primeiro minuto)."""
    if not views or not publicado:
        return None
    try:
        quando = datetime.fromisoformat(publicado.replace("Z", "+00:00"))
    except ValueError:
        return None
    horas = max(((agora or datetime.now(timezone.utc)) - quando).total_seconds() / 3600, 1.0)
    return round(views / horas, 1)


def listar(texto: str, aba: str = "videos", limite: int = LIMITE_PADRAO) -> dict:
    """Devolve {"canal": {...}, "posts": [...]} do canal. Usa um cache curto para trocar filtros sem esperar."""
    if aba not in ABAS:
        raise ErroPerfil("Escolha Vídeos ou Shorts.")
    base = normalizar_alvo(texto)
    chave = (base, aba, limite)
    guardado = _cache.get(chave)
    if guardado and time.time() - guardado[0] < VALIDADE_CACHE_S:
        return guardado[1]

    saida = _yt_dlp(["--flat-playlist", "--playlist-end", str(limite), "-J", f"{base}/{aba}"])
    try:
        dados = json.loads(saida[saida.index("{"):])
    except (ValueError, json.JSONDecodeError):
        raise ErroPerfil("O YouTube devolveu uma resposta que não consegui ler.")
    entradas = [e for e in dados.get("entries", []) if e and e.get("id")]
    datas = _datas([e["id"] for e in entradas[:COM_DATA]])

    posts = []
    for ordem, e in enumerate(entradas):
        publicado = datas.get(e["id"])
        views = e.get("view_count")
        eh_short = aba == "shorts"
        posts.append(Post(
            id=e["id"], titulo=e.get("title") or "(sem título)",
            url=f"https://www.youtube.com/{'shorts/' if eh_short else 'watch?v='}{e['id']}",
            views=int(views) if views is not None else None,
            duracao_s=float(e["duration"]) if e.get("duration") else None,
            publicado=publicado, miniatura=f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg",
            velocidade=velocidade(views, publicado), ordem=ordem))
    canal = {"nome": dados.get("channel") or dados.get("uploader") or "Canal", "id": dados.get("channel_id"),
             "arroba": dados.get("uploader_id"), "url": base, "aba": aba}
    resultado = {"canal": canal, "posts": [asdict(p) for p in posts]}
    _cache[chave] = (time.time(), resultado)
    return resultado


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python -m app.busca.perfil @canal")
        sys.exit(1)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        _r = listar(sys.argv[1])
    except ErroPerfil as _erro:
        print("Nao deu certo:", _erro)
        sys.exit(1)
    print(_r["canal"])
    for _p in _r["posts"][:10]:
        print(f"{_p['views'] or 0:>10} views | {(_p['velocidade'] or 0):>9.1f}/h | {_p['titulo'][:60]}")
