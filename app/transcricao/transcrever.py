"""Transcricao: transforma a fala do video em texto com o tempo de cada palavra.

Usa o faster-whisper, que roda no seu computador (gratuito). Na primeira vez
ele baixa o modelo de voz (algumas centenas de MB); depois fica guardado.

Rodar sozinho:
    python -m app.transcricao.transcrever caminho/do/video.mp4
"""
import subprocess
import sys
from pathlib import Path

from app import config
from app.contratos import Palavra, Transcricao
from app.transcricao.frases import montar_frases

log = config.criar_log("transcricao")

MODELO_WHISPER = "small"   # "small" e rapido e razoavel; "medium" e melhor e mais lento
_modelo = None


def _carregar_modelo():
    global _modelo
    if _modelo is None:
        from faster_whisper import WhisperModel
        log.info("Carregando o modelo de voz '%s' (na primeira vez ele e baixado)...", MODELO_WHISPER)
        _modelo = WhisperModel(MODELO_WHISPER, device="cpu", compute_type="int8")
    return _modelo


def _extrair_audio(caminho_video: Path):
    """Extrai o audio (16 kHz, mono) com o ffmpeg e devolve como lista de numeros."""
    import numpy as np
    resultado = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(caminho_video),
         "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True,
    )
    if resultado.returncode != 0:
        erro = resultado.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Nao consegui extrair o audio do video: {erro[-200:]}")
    audio = np.frombuffer(resultado.stdout, dtype=np.float32)
    if audio.size == 0:
        raise RuntimeError("O video nao tem trilha de audio.")
    return audio


def transcrever(caminho_video: Path) -> Transcricao:
    """Transcreve o video no idioma original da fala, sem traduzir."""
    modelo = _carregar_modelo()
    audio = _extrair_audio(caminho_video)
    segmentos, info = modelo.transcribe(
        audio,
        word_timestamps=True,
        vad_filter=True,          # ignora trechos sem fala (musica, silencio)
        beam_size=5,
    )
    log.info("Idioma detectado: %s. Transcrevendo %.0f s de video...", info.language, info.duration)

    palavras: list[Palavra] = []
    proximo_aviso = 0.1
    for segmento in segmentos:
        for p in segmento.words or []:
            palavras.append(Palavra(p.word.strip(), round(p.start, 3), round(p.end, 3)))
        if info.duration and segmento.end / info.duration >= proximo_aviso:
            log.info("Transcricao: %d%%", int(segmento.end / info.duration * 100))
            proximo_aviso = segmento.end / info.duration + 0.1

    frases = montar_frases(palavras)
    log.info("Transcricao pronta: %d palavras em %d frases.", len(palavras), len(frases))
    return Transcricao(idioma=info.language, duracao_s=round(info.duration, 3), frases=frases)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python -m app.transcricao.transcrever caminho/do/video.mp4")
        sys.exit(1)
    _t = transcrever(Path(sys.argv[1]))
    print(f"\nIdioma: {_t.idioma} | Duracao: {_t.duracao_s:.0f} s | Frases: {len(_t.frases)}\n")
    for _f in _t.frases:
        print(f"[{_f.id}] ({_f.inicio:.1f}-{_f.fim:.1f}) {_f.texto}")
