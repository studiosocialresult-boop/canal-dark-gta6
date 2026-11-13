"""Edicao: corta o trecho, converte para vertical 9:16 e queima a legenda (ffmpeg).

Resultado: mp4 1080x1920, video centralizado sobre fundo desfocado, com
legenda palavra a palavra (a palavra falada fica em amarelo).

Edicao e so editorial. Nada de espelhar, mudar velocidade ou tom, nem filtros
feitos para escapar da deteccao de direitos autorais.

Rodar sozinho (usa o video de exemplo):
    python -m app.edicao.cortar testes/exemplo_zoo.mp4 4.5 12.3
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app import config
from app.contratos import CorteProposto, Frase, Palavra

log = config.criar_log("edicao")

LARGURA, ALTURA = 1080, 1920
PALAVRAS_POR_GRUPO = 3
MAX_CARACTERES_GRUPO = 16   # em maiusculas, Arial 80 negrito: cerca de 16 letras por linha
SEGURA_GRUPO_S = 0.35      # quanto tempo a legenda fica na tela depois da ultima palavra

CABECALHO_ASS = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {LARGURA}
PlayResY: {ALTURA}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Legenda,Arial,80,&H0000E0FF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,2,2,70,70,430,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _tempo_ass(segundos: float) -> str:
    centesimos = round(max(segundos, 0.0) * 100)
    horas, resto = divmod(centesimos, 360000)
    minutos, resto = divmod(resto, 6000)
    seg, cent = divmod(resto, 100)
    return f"{horas}:{minutos:02d}:{seg:02d}.{cent:02d}"


def _limpar(texto: str) -> str:
    """Tira caracteres que o formato de legenda trataria como comando."""
    return texto.replace("{", "(").replace("}", ")").replace("\\", "/").replace("\n", " ")


def _agrupar(palavras: list[Palavra]) -> list[list[Palavra]]:
    """Junta as palavras em grupos curtos que cabem na tela."""
    grupos: list[list[Palavra]] = []
    atual: list[Palavra] = []
    for p in palavras:
        tamanho = sum(len(x.texto) + 1 for x in atual) + len(p.texto)
        if atual and (len(atual) >= PALAVRAS_POR_GRUPO or tamanho > MAX_CARACTERES_GRUPO):
            grupos.append(atual)
            atual = []
        atual.append(p)
        if p.texto.rstrip("\"'”)").endswith((".", "!", "?")):
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)
    return grupos


def gerar_ass(frases: list[Frase], inicio_corte: float, duracao: float) -> str:
    """Monta o arquivo de legenda. Os tempos das palavras sao do video ORIGINAL."""
    grupos: list[list[Palavra]] = []
    for frase in frases:
        palavras = [Palavra(_limpar(p.texto), p.inicio - inicio_corte, p.fim - inicio_corte)
                    for p in frase.palavras if p.texto.strip()]
        grupos += _agrupar(palavras)

    linhas = [CABECALHO_ASS]
    for numero, grupo in enumerate(grupos):
        inicio = max(grupo[0].inicio, 0.0)
        fim = grupo[-1].fim + SEGURA_GRUPO_S
        if numero + 1 < len(grupos):
            fim = min(fim, grupos[numero + 1][0].inicio)
        fim = min(fim, duracao)
        if fim <= inicio:
            continue
        partes = []
        for i, p in enumerate(grupo):
            proximo = grupo[i + 1].inicio if i + 1 < len(grupo) else p.fim
            centesimos = max(1, round((proximo - p.inicio) * 100))
            partes.append(f"{{\\k{centesimos}}}{p.texto.upper()}")
        linhas.append(
            f"Dialogue: 0,{_tempo_ass(inicio)},{_tempo_ass(fim)},Legenda,,0,0,0,,{' '.join(partes)}\n"
        )
    return "".join(linhas)


# Fundo: o proprio video ampliado, reduzido, borrado e ampliado de novo (borrar pequeno e rapido).
# Frente: o video inteiro, ajustado a largura, centralizado.
FILTRO = (
    f"[0:v]split=2[fundo][frente];"
    f"[fundo]scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=increase,"
    f"crop={LARGURA}:{ALTURA},scale=216:384,boxblur=6:2,scale={LARGURA}:{ALTURA},"
    f"eq=brightness=-0.08[bg];"
    f"[frente]scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=decrease[fg];"
    f"[bg][fg]overlay=(W-w)/2:(H-h)/2,subtitles=legenda.ass,format=yuv420p[saida]"
)


def gerar_corte(caminho_video: Path, corte: CorteProposto, frases_legenda: list[Frase],
                destino: Path) -> Path:
    """Gera o corte vertical com legenda e devolve o caminho do mp4."""
    caminho_video = Path(caminho_video).resolve()
    destino = Path(destino).resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)
    duracao = corte.fim - corte.inicio
    if duracao <= 0:
        raise ValueError("O corte tem duracao zero ou negativa.")

    # A legenda e o ffmpeg rodam dentro de uma pasta temporaria sem espacos no
    # caminho do arquivo .ass: o filtro de legenda do ffmpeg se confunde com
    # espacos e com "D:\" em caminhos do Windows.
    with tempfile.TemporaryDirectory(prefix="legenda_") as pasta:
        (Path(pasta) / "legenda.ass").write_text(
            gerar_ass(frases_legenda, corte.inicio, duracao), encoding="utf-8")
        comando = [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-ss", f"{corte.inicio:.3f}", "-t", f"{duracao:.3f}",
            "-i", str(caminho_video),
            "-filter_complex", FILTRO,
            "-map", "[saida]", "-map", "0:a:0?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(destino),
        ]
        log.info("Renderizando %.0f s de video em %dx%d...", duracao, LARGURA, ALTURA)
        comeco = time.time()
        resultado = subprocess.run(comando, cwd=pasta, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace")
    if resultado.returncode != 0:
        destino.unlink(missing_ok=True)
        raise RuntimeError(f"O ffmpeg falhou: {resultado.stderr.strip()[-300:]}")
    log.info("Corte pronto em %.0f s: %s", time.time() - comeco, destino.name)
    return destino


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Uso: python -m app.edicao.cortar video.mp4 inicio_s fim_s")
        sys.exit(1)
    from app.transcricao import transcrever
    _video = Path(sys.argv[1])
    _ini, _fim = float(sys.argv[2]), float(sys.argv[3])
    _t = transcrever.transcrever(_video)
    _frases = [f for f in _t.frases if f.inicio >= _ini - 0.5 and f.fim <= _fim + 0.5]
    _corte = CorteProposto(0, 0, _ini, _fim, 80, "teste", "teste", "original")
    config.garantir_pastas()
    _saida = gerar_corte(_video, _corte, _frases, config.PASTA_CORTES / "teste_edicao.mp4")
    print("Arquivo:", _saida)
