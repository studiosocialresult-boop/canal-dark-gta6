"""Renderizar: monta um video de template (layout + midia + frase) com o ffmpeg.

O cartao (frase, foto, nome, faixas) vem de cartao.py; aqui o video entra na(s)
zona(s) e o cartao vai por cima. A previa do assistente usa o mesmo caminho,
so que de um unico quadro. Edicao e so editorial: nada de espelhar, mudar
velocidade ou tom, nem filtros para escapar da deteccao de direitos autorais.

Rodar sozinho, para um video de exemplo (gera dados/tmp/render_<layout>.mp4):
    python -m app.multiplicador.renderizar testes/exemplo_zoo.mp4
"""
import hashlib
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

from app import banco, config
from app.multiplicador import cartao, modelos, repositorio
from app.multiplicador.modelos import ALTURA, LARGURA

log = config.criar_log("render")
FPS = 30
VERSAO_PREVIA = 2      # sobe quando o desenho da previa muda, para nao mostrar quadros antigos do cache


class ErroRender(Exception):
    """Nao foi possivel montar o video."""


# ---------- origem dos videos ----------

def resolver_midia(midia: dict) -> tuple[Path, float | None, float | None]:
    """Devolve (arquivo, inicio_s, duracao_s). Corte: so o trecho, do video original e sem legenda."""
    if midia["origem"] == "corte":
        corte = banco.ler_corte(midia["corte_id"])
        if corte is None:
            raise ErroRender("O corte usado como midia nao existe mais.")
        video = banco.ler_video(corte["video_id"])
        arquivo = config.caminho_absoluto(video["caminho_arquivo"] or "")
        if not arquivo.exists():
            raise ErroRender("O video original deste corte foi apagado do computador.")
        return arquivo, corte["inicio_s"], corte["fim_s"] - corte["inicio_s"]
    arquivo = config.caminho_absoluto(midia["arquivo"] or "")
    if not arquivo.exists():
        raise ErroRender(f"Nao achei o arquivo de video: {midia['rotulo']}.")
    return arquivo, None, None


def duracao_do_arquivo(arquivo: Path) -> float:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(arquivo)],
        capture_output=True, text=True)
    try:
        return float(saida.stdout.strip())
    except ValueError:
        raise ErroRender("Nao consegui ler a duracao do video.")


# ---------- filtros ----------

def _filtro_zona(entrada: int, saida: str, zona: tuple, midia: dict | None, fundo: str) -> str:
    """Filtro que ajusta um video a uma zona do layout (preencher, caber ou so desfocado)."""
    _x, _y, w, h = zona
    modo = (midia or {}).get("ajuste", "preencher")
    zoom = float((midia or {}).get("zoom", 1.0))
    px = float((midia or {}).get("pos_x", 50)) / 100
    py = float((midia or {}).get("pos_y", 50)) / 100
    desfoque = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                f"scale={max(w // 5, 16)}:{max(h // 5, 16)},boxblur=6:2,scale={w}:{h},eq=brightness=-0.08")
    if midia is None:                                  # segunda zona sem video proprio: so o fundo desfocado
        return f"[{entrada}:v]{desfoque},setsar=1[{saida}]"
    if modo == "caber":
        atras = (desfoque if fundo == "desfocado" else f"scale={w}:{h},drawbox=x=0:y=0:w={w}:h={h}:color=black:t=fill")
        return (f"[{entrada}:v]split=2[a{entrada}][b{entrada}];[a{entrada}]{atras}[f{entrada}];"
                f"[b{entrada}]scale={w}:{h}:force_original_aspect_ratio=decrease[c{entrada}];"
                f"[f{entrada}][c{entrada}]overlay=(W-w)/2:(H-h)/2,setsar=1[{saida}]")
    ampliar = f"scale=iw*{zoom:.3f}:ih*{zoom:.3f}," if zoom > 1.001 else ""
    return (f"[{entrada}:v]scale={w}:{h}:force_original_aspect_ratio=increase,{ampliar}"
            f"crop={w}:{h}:x='(iw-{w})*{px:.4f}':y='(ih-{h})*{py:.4f}',setsar=1[{saida}]")


def montar_comando(*, overlay: Path, zonas: dict, fontes: list, ajustes: list, fundo: str,
                   duracao: float, destino: Path, so_quadro: bool = False) -> list[str]:
    """Comando do ffmpeg. fontes: lista de (arquivo, inicio_s, duracao_s) uma por zona; ajustes: dict da midia."""
    comando = ["ffmpeg", "-nostdin", "-y", "-v", "error"]
    for arquivo, inicio, dur in fontes:
        if inicio:
            comando += ["-ss", f"{inicio + (1.0 if so_quadro else 0):.3f}"]
        elif so_quadro:
            comando += ["-ss", "1.0"]
        comando += ["-t", f"{(dur or duracao):.3f}", "-i", str(arquivo)]
    comando += ["-loop", "1", "-framerate", str(FPS), "-i", str(overlay)]
    indice_overlay = len(fontes)

    partes, camadas = [], []
    nomes_zona = ["video", "video2"]
    for i, (nome, zona) in enumerate((n, zonas[n]) for n in nomes_zona if n in zonas):
        midia = ajustes[i] if i < len(ajustes) else None
        partes.append(_filtro_zona(i if i < len(fontes) else 0, f"z{i}", zona, midia, fundo))
        camadas.append((f"z{i}", zona))
    partes.append(f"color=c=black:s={LARGURA}x{ALTURA}:r={FPS}:d={duracao:.3f}[base]")
    atual = "base"
    for i, (nome, (x, y, _w, _h)) in enumerate(camadas):
        partes.append(f"[{atual}][{nome}]overlay={x}:{y}[t{i}]")
        atual = f"t{i}"
    partes.append(f"[{atual}][{indice_overlay}:v]overlay=0:0:shortest=1,format=yuv420p[saida]")

    comando += ["-filter_complex", ";".join(partes), "-map", "[saida]"]
    if so_quadro:
        # O primeiro quadro da composicao sai antes de o video chegar ao filtro (zona preta):
        # descartar o primeiro meio segundo da saida resolve.
        comando += ["-ss", "0.5", "-frames:v", "1", "-q:v", "3", str(destino)]
    else:
        comando += ["-map", "0:a:0?", "-t", f"{duracao:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(destino)]
    return comando


def _rodar(comando: list[str]) -> None:
    resultado = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if resultado.returncode != 0:
        raise ErroRender(f"O ffmpeg falhou: {resultado.stderr.strip()[-300:]}")


# ---------- uso ----------

def _avatar(config_template: dict) -> Path | None:
    caminho = config_template.get("perfil", {}).get("avatar")
    return config.caminho_absoluto(caminho) if caminho else None


def _preparar(template: dict, frase: str, midias: list[dict]):
    """Desenha o cartao e resolve os videos das zonas. Devolve (overlay_png, zonas, fontes, ajustes, duracao)."""
    layout = template["layout"]
    cfg = modelos.config_completa(template["config"])
    imagem, zonas = cartao.compor(layout, template["config"], frase, _avatar(template["config"]))
    principal = midias[0]
    arquivo, inicio, dur = resolver_midia(principal)
    duracao = dur if dur else duracao_do_arquivo(arquivo)
    fontes, ajustes = [(arquivo, inicio, dur)], [principal]
    if "video2" in zonas:
        if len(midias) > 1:
            fontes.append(resolver_midia(midias[1]))
            ajustes.append(midias[1])
        else:
            fontes.append((arquivo, inicio, dur))        # mesmo video, so desfocado
            ajustes.append(None)
    return imagem, zonas, fontes, ajustes, duracao, cfg["video"]["fundo"]


def _midias_do_template(template_id: int, principal: dict) -> list[dict]:
    """A midia principal e, no layout viral, o video escolhido para a segunda zona (se houver)."""
    segunda = [m for m in repositorio.listar_midias(template_id) if m["zona"] == 2 and m["selecionada"]]
    return [principal] + segunda[:1]


def renderizar_saida(saida_id: int) -> Path:
    """Gera o mp4 de um video do template e atualiza o banco."""
    saida = repositorio.ler_saida(saida_id)
    template = repositorio.ler_template(saida["template_id"])
    midia = repositorio.ler_midia(saida["midia_id"])
    frase = repositorio.ler_frase(saida["frase_id"])
    destino = repositorio.pasta_do_template(template["id"]) / f"saida_{saida_id}.mp4"
    destino.parent.mkdir(parents=True, exist_ok=True)
    repositorio.atualizar_saida(saida_id, estado="renderizando", erro=None)
    try:
        imagem, zonas, fontes, ajustes, duracao, fundo = _preparar(
            template, frase["texto"], _midias_do_template(template["id"], midia))
        with tempfile.TemporaryDirectory(prefix="tpl_") as pasta:
            overlay = Path(pasta) / "cartao.png"
            imagem.save(overlay)
            inicio = time.time()
            _rodar(montar_comando(overlay=overlay, zonas=zonas, fontes=fontes, ajustes=ajustes,
                                  fundo=fundo, duracao=duracao, destino=destino))
        log.info("Video %d pronto em %.0f s (%.0f s de video).", saida_id, time.time() - inicio, duracao)
    except Exception as erro:
        destino.unlink(missing_ok=True)
        repositorio.atualizar_saida(saida_id, estado="falhou", erro=str(erro)[:300])
        raise
    repositorio.atualizar_saida(saida_id, estado="pronto", arquivo=config.caminho_relativo(destino), erro=None)
    return destino


def previa(template: dict, frase: str, midia: dict | None) -> Path:
    """Imagem JPG de como o template fica (um quadro). Sem video, mostra uma zona cinza no lugar."""
    pasta = repositorio.pasta_do_template(template["id"]) / "previas"
    pasta.mkdir(parents=True, exist_ok=True)
    extras = ""
    if midia:
        extras = repr(sorted((k, v) for k, v in midia.items() if k in ("id", "zoom", "pos_x", "pos_y", "ajuste", "arquivo", "corte_id")))
        extras += repr([(m["id"], m["zoom"], m["pos_x"], m["pos_y"], m["ajuste"]) for m in repositorio.listar_midias(template["id"]) if m["zona"] == 2])
    avatar = _avatar(template["config"])
    marca_avatar = avatar.stat().st_mtime if avatar and avatar.exists() else 0
    chave = hashlib.sha1(f"v{VERSAO_PREVIA}|{template['layout']}|{template['config']}|{frase}|{extras}|{marca_avatar}".encode()).hexdigest()[:16]
    destino = pasta / f"{chave}.jpg"
    if destino.exists():
        return destino
    for antigo in sorted(pasta.glob("*.jpg"), key=lambda a: a.stat().st_mtime)[:-40]:   # guarda so as ultimas
        antigo.unlink(missing_ok=True)

    if midia is None:
        imagem, zonas = cartao.compor(template["layout"], template["config"], frase, _avatar(template["config"]))
        fundo = Image.new("RGBA", (LARGURA, ALTURA), (58, 60, 72, 255))
        fundo.alpha_composite(imagem)
        fundo.convert("RGB").resize((540, 960), Image.LANCZOS).save(destino, quality=88)
        return destino

    imagem, zonas, fontes, ajustes, duracao, fundo = _preparar(template, frase, _midias_do_template(template["id"], midia))
    with tempfile.TemporaryDirectory(prefix="tpl_") as temporaria:
        overlay = Path(temporaria) / "cartao.png"
        imagem.save(overlay)
        bruto = Path(temporaria) / "quadro.jpg"
        _rodar(montar_comando(overlay=overlay, zonas=zonas, fontes=fontes, ajustes=ajustes, fundo=fundo,
                              duracao=min(duracao, 3.0), destino=bruto, so_quadro=True))
        Image.open(bruto).resize((540, 960), Image.LANCZOS).save(destino, quality=88)
    return destino


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python -m app.multiplicador.renderizar video.mp4")
        sys.exit(1)
    config.garantir_pastas()
    _video = Path(sys.argv[1]).resolve()
    _dur = duracao_do_arquivo(_video)
    for _layout in modelos.LAYOUTS:
        _imagem, _zonas = cartao.compor(_layout, {}, "A Rockstar anunciou um festival ao vivo em Miami para celebrar o lançamento")
        with tempfile.TemporaryDirectory() as _pasta:
            _overlay = Path(_pasta) / "cartao.png"
            _imagem.save(_overlay)
            _saida = config.PASTA_DADOS / "tmp" / f"render_{_layout}.mp4"
            _saida.parent.mkdir(parents=True, exist_ok=True)
            _midia = {"ajuste": "preencher", "zoom": 1.0, "pos_x": 50, "pos_y": 50}
            _rodar(montar_comando(overlay=_overlay, zonas=_zonas, fontes=[(_video, None, None)] * len(_zonas),
                                  ajustes=[_midia, None][:len(_zonas)], fundo="desfocado", duracao=_dur, destino=_saida))
            print("Pronto:", _saida)
