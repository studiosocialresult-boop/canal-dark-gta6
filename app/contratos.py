"""Contratos: o formato dos dados que passam de um modulo para o outro.

Todo modulo recebe e devolve estes tipos. Assim cada parte pode ser
construida e testada sozinha, sem conhecer o interior das outras.

Todos os tempos sao em segundos, contados desde o inicio do video original.
"""
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

MODOS = ("original", "narrado")


@dataclass
class Palavra:
    """Uma palavra falada, com o instante em que comeca e termina."""
    texto: str
    inicio: float
    fim: float


@dataclass
class Frase:
    """Uma frase completa. O id e a posicao dela na transcricao (0, 1, 2...)."""
    id: int
    inicio: float
    fim: float
    texto: str
    palavras: list[Palavra] = field(default_factory=list)


@dataclass
class Transcricao:
    """Tudo o que foi falado no video, ja dividido em frases."""
    idioma: str          # codigo de duas letras: "pt", "en"...
    duracao_s: float
    frases: list[Frase]

    def salvar(self, caminho: Path) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(asdict(self), ensure_ascii=False), encoding="utf-8")

    @classmethod
    def carregar(cls, caminho: Path) -> "Transcricao":
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        frases = [
            Frase(
                id=f["id"], inicio=f["inicio"], fim=f["fim"], texto=f["texto"],
                palavras=[Palavra(**p) for p in f["palavras"]],
            )
            for f in dados["frases"]
        ]
        return cls(idioma=dados["idioma"], duracao_s=dados["duracao_s"], frases=frases)


@dataclass
class VideoBaixado:
    """Um video de origem ja salvo no disco, com os dados da fonte."""
    plataforma: str      # "youtube", "instagram", "tiktok"...
    id_externo: str      # identificador do video na plataforma
    url: str
    titulo: str
    canal: str
    duracao_s: float
    caminho: Path


@dataclass
class CorteProposto:
    """Um trecho escolhido pelo cerebro para virar corte."""
    frase_inicio: int    # id da primeira frase do corte
    frase_fim: int       # id da ultima frase do corte (inclusive)
    inicio: float        # instante exato onde o corte comeca
    fim: float           # instante exato onde o corte termina
    nota: int            # 0 a 100
    motivo: str
    titulo: str
    modo: str            # "original" ou "narrado"

    @property
    def duracao_s(self) -> float:
        return self.fim - self.inicio


@dataclass
class BlocoRoteiro:
    """Um trecho da narracao. A voz comeca a falar quando a frase ancora comeca no video."""
    frase_inicio: int    # id da frase do corte em que o bloco e ancorado
    texto: str


@dataclass
class Roteiro:
    """O texto que o narrador fala em um corte.

    modo "narrado": varios blocos, que cobrem o corte do comeco ao fim.
    modo "original": no maximo um bloco, o gancho, falado logo antes do corte.
    Lista vazia significa que o corte fica sem narracao.
    """
    modo: str
    blocos: list[BlocoRoteiro] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return " ".join(b.texto for b in self.blocos)

    def para_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def de_json(cls, texto: str) -> "Roteiro":
        dados = json.loads(texto)
        return cls(modo=dados["modo"], blocos=[BlocoRoteiro(**b) for b in dados["blocos"]])
