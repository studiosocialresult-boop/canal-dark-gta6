"""Voz: transforma o roteiro de um corte em audio (ElevenLabs).

Para cada bloco do roteiro, pede a voz e os tempos de cada palavra. Depois
posiciona os blocos na linha do tempo do corte (cada um comeca quando a frase
ancora comeca no video, sem nunca cair em cima do bloco anterior) e junta tudo
em uma unica faixa de audio, narracao.mp3, mais um arquivo voz.json com o
tempo de cada palavra, que a edicao usa para a legenda.

Tudo fica em dados/narracoes/<id do corte>/.

Rodar sozinho, para um corte que ja tem roteiro (gasta caracteres da ElevenLabs):
    python -m app.narracao.voz 3
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

from app import banco, config
from app.contratos import Palavra, Roteiro, Transcricao

log = config.criar_log("voz")

URL_VOZ = "https://api.elevenlabs.io/v1/text-to-speech/{voz}/with-timestamps"


class ErroVoz(Exception):
    """A ElevenLabs nao conseguiu gerar a voz."""


@dataclass
class BlocoVoz:
    """Um bloco ja falado e posicionado. Tempos em segundos desde o inicio do CORTE."""
    frase_inicio: int
    texto: str
    inicio: float
    fim: float
    palavras: list[Palavra] = field(default_factory=list)


@dataclass
class Voz:
    """A narracao pronta de um corte."""
    modo: str
    duracao_s: float                  # onde a ultima fala termina
    blocos: list[BlocoVoz]
    arquivo_audio: str = "narracao.mp3"

    @property
    def palavras(self) -> list[Palavra]:
        return [p for b in self.blocos for p in b.palavras]

    def salvar(self, pasta: Path) -> None:
        (pasta / "voz.json").write_text(json.dumps(asdict(self), ensure_ascii=False), encoding="utf-8")

    @classmethod
    def carregar(cls, pasta: Path) -> "Voz":
        d = json.loads((pasta / "voz.json").read_text(encoding="utf-8"))
        blocos = [BlocoVoz(b["frase_inicio"], b["texto"], b["inicio"], b["fim"],
                           [Palavra(**p) for p in b["palavras"]]) for b in d["blocos"]]
        return cls(d["modo"], d["duracao_s"], blocos, d.get("arquivo_audio", "narracao.mp3"))


def pasta_da_narracao(corte_id: int) -> Path:
    return config.PASTA_NARRACOES / str(corte_id)


# ---------- conversa com a ElevenLabs ----------

def _pedir_voz(texto: str, tentativas: int = 3, espera_s: float = 10.0) -> tuple[bytes, dict]:
    """Pede a voz de um texto. Devolve (audio mp3, tempos por caractere)."""
    chave = os.getenv("ELEVENLABS_API_KEY")
    if not chave:
        raise ErroVoz("Nao encontrei a chave da ElevenLabs. Confira o ELEVENLABS_API_KEY no arquivo .env.")
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = requests.post(
                URL_VOZ.format(voz=config.VOZ_ID),
                headers={"xi-api-key": chave, "Content-Type": "application/json"},
                params={"output_format": "mp3_44100_128"},
                json={"text": texto, "model_id": config.VOZ_MODELO, "language_code": config.VOZ_IDIOMA},
                timeout=120,
            )
        except requests.RequestException as erro:
            log.warning("Voz: falha de conexao (tentativa %d de %d): %s", tentativa, tentativas,
                        type(erro).__name__)
        else:
            if resposta.ok:
                dados = resposta.json()
                return base64.b64decode(dados["audio_base64"]), dados["alignment"]
            if resposta.status_code in (401, 429) and "quota" in resposta.text.lower():
                raise ErroVoz("Acabaram os caracteres do plano da ElevenLabs neste mes. "
                              "Espere a renovacao ou mude de plano no site da ElevenLabs.")
            if resposta.status_code == 401:
                raise ErroVoz("A chave da ElevenLabs foi recusada. Confira o arquivo .env.")
            if resposta.status_code == 402:
                raise ErroVoz("A ElevenLabs recusou: esta voz ou este recurso exige plano pago.")
            if resposta.status_code in (400, 404, 422):
                raise ErroVoz(f"A ElevenLabs rejeitou o pedido ({resposta.status_code}): {resposta.text[:200]}")
            log.warning("Voz: erro %d da ElevenLabs (tentativa %d de %d).",
                        resposta.status_code, tentativa, tentativas)
        if tentativa < tentativas:
            time.sleep(espera_s * tentativa)
    raise ErroVoz("A ElevenLabs nao respondeu depois de algumas tentativas. Tente de novo mais tarde.")


def palavras_do_alinhamento(texto: str, alinhamento: dict) -> list[Palavra]:
    """Converte o tempo por caractere em tempo por palavra (segundos desde o inicio do bloco)."""
    letras = alinhamento["characters"]
    comecos = alinhamento["character_start_times_seconds"]
    fins = alinhamento["character_end_times_seconds"]
    palavras: list[Palavra] = []
    atual, ini, fim = "", 0.0, 0.0
    for letra, c, f in zip(letras, comecos, fins):
        if letra.isspace():
            if atual:
                palavras.append(Palavra(atual, ini, fim))
            atual = ""
            continue
        if not atual:
            ini = c
        atual += letra
        fim = f
    if atual:
        palavras.append(Palavra(atual, ini, fim))
    return palavras


# ---------- montagem ----------

def posicionar(duracoes: list[float], ancoras: list[float]) -> list[float]:
    """Instante de inicio de cada bloco: na ancora, ou logo depois do bloco anterior acabar."""
    inicios: list[float] = []
    for duracao, ancora in zip(duracoes, ancoras):
        minimo = inicios[-1] + duracoes[len(inicios) - 1] + config.PAUSA_ENTRE_BLOCOS_S if inicios else 0.0
        inicios.append(max(ancora, minimo))
    return inicios


def _duracao_audio(caminho: Path) -> float:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(caminho)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(saida)


def _juntar_blocos(arquivos: list[Path], inicios: list[float], destino: Path) -> None:
    """Junta os blocos em uma faixa so, cada um no seu instante (ffmpeg)."""
    comando = ["ffmpeg", "-nostdin", "-y", "-v", "error"]
    for arquivo in arquivos:
        comando += ["-i", str(arquivo)]
    partes = [f"[{i}:a]adelay={int(round(t * 1000))}:all=1[a{i}]" for i, t in enumerate(inicios)]
    entradas = "".join(f"[a{i}]" for i in range(len(arquivos)))
    partes.append(f"{entradas}amix=inputs={len(arquivos)}:normalize=0:dropout_transition=0[saida]")
    comando += ["-filter_complex", ";".join(partes), "-map", "[saida]",
                "-c:a", "libmp3lame", "-b:a", "192k", str(destino)]
    resultado = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if resultado.returncode != 0:
        raise ErroVoz(f"O ffmpeg falhou ao juntar a narracao: {resultado.stderr.strip()[-300:]}")


def gerar_voz(roteiro: Roteiro, inicio_corte: float, transcricao: Transcricao, pasta: Path) -> Voz:
    """Gera a voz de todos os blocos e monta a faixa da narracao em `pasta`."""
    if not roteiro.blocos:
        raise ErroVoz("Este corte nao tem texto de narracao.")
    pasta.mkdir(parents=True, exist_ok=True)

    audios: list[bytes] = []
    palavras: list[list[Palavra]] = []
    for numero, bloco in enumerate(roteiro.blocos, start=1):
        log.info("Voz: gerando o bloco %d de %d (%d caracteres)...", numero, len(roteiro.blocos), len(bloco.texto))
        audio, alinhamento = _pedir_voz(bloco.texto)
        audios.append(audio)
        palavras.append(palavras_do_alinhamento(bloco.texto, alinhamento))

    with tempfile.TemporaryDirectory(prefix="voz_") as temporaria:
        arquivos = []
        for numero, audio in enumerate(audios):
            arquivo = Path(temporaria) / f"bloco_{numero}.mp3"
            arquivo.write_bytes(audio)
            arquivos.append(arquivo)
        duracoes = [_duracao_audio(a) for a in arquivos]
        if roteiro.modo == "original":
            inicios = [0.0]                         # o gancho comeca no primeiro instante
        else:
            ancoras = [max(transcricao.frases[b.frase_inicio].inicio - inicio_corte, 0.0)
                       for b in roteiro.blocos]
            inicios = posicionar(duracoes, ancoras)
        _juntar_blocos(arquivos, inicios, pasta / "narracao.mp3")

    blocos = []
    for bloco, duracao, inicio, lista in zip(roteiro.blocos, duracoes, inicios, palavras):
        blocos.append(BlocoVoz(
            bloco.frase_inicio, bloco.texto, inicio, inicio + duracao,
            [Palavra(p.texto, inicio + p.inicio, inicio + p.fim) for p in lista]))
    voz = Voz(roteiro.modo, blocos[-1].fim, blocos)
    voz.salvar(pasta)
    log.info("Voz pronta: %.1f s de fala, %d caracteres (%.1f por segundo).",
             sum(duracoes), len(roteiro.texto),
             len(roteiro.texto) / max(sum(duracoes), 0.1))
    return voz


def narrar_corte(corte_id: int) -> Voz:
    """Gera e guarda a voz de um corte que ja tem roteiro. Ponto de entrada do pipeline e do painel."""
    narracao = banco.ler_narracao(corte_id)
    if narracao is None:
        raise ValueError(f"O corte {corte_id} ainda nao tem roteiro.")
    corte = banco.ler_corte(corte_id)
    transcricao = Transcricao.carregar(config.PASTA_TRANSCRICOES / f"{corte['video_id']}.json")
    roteiro = Roteiro.de_json(narracao["roteiro"])
    pasta = pasta_da_narracao(corte_id)
    try:
        voz = gerar_voz(roteiro, corte["inicio_s"], transcricao, pasta)
    except ErroVoz as erro:
        banco.atualizar_narracao(narracao["id"], estado="falhou", erro=str(erro)[:500])
        raise
    banco.atualizar_narracao(
        narracao["id"], estado="narrado", erro=None,
        caminho_audio=config.caminho_relativo(pasta / "narracao.mp3"))
    banco.registrar_uso_api(
        corte["usuario_id"], "elevenlabs", "voz", video_id=corte["video_id"], modelo=config.VOZ_MODELO,
        caracteres=len(roteiro.texto), custo_usd=len(roteiro.texto) * config.PRECO_VOZ_USD_POR_CARACTERE)
    return voz


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("Uso: python -m app.narracao.voz <numero do corte>")
        sys.exit(1)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    banco.criar_tabelas()
    try:
        _voz = narrar_corte(int(sys.argv[1]))
    except (ErroVoz, ValueError) as _erro:
        print("Nao deu certo:", _erro)
        sys.exit(1)
    print()
    print("Arquivo:", pasta_da_narracao(int(sys.argv[1])) / "narracao.mp3")
    for _b in _voz.blocos:
        print(f"  {_b.inicio:5.1f}-{_b.fim:5.1f} s  {_b.texto[:70]}")
