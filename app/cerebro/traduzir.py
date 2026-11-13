"""Traducao da legenda: passa as frases de um corte para portugues do Brasil.

Recebe as frases de UM corte e devolve as mesmas frases (mesmo id, inicio e
fim) com o texto em portugues. Como a traducao nao tem o tempo de cada
palavra, o tempo da frase e repartido entre as palavras em portugues.

As instrucoes da IA ficam em prompts/traducao_legenda.md. Usa o modelo rapido
(Haiku), que e barato.

Rodar sozinho (gasta uma fracao de centavo da API):
    python -m app.cerebro.traduzir "Alright, so here we are." en
"""
import sys

from app import banco, config, ia
from app.contratos import Frase
from app.transcricao.frases import repartir_tempo

ESQUEMA = {
    "type": "object",
    "properties": {
        "traducoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "texto": {"type": "string"},
                },
                "required": ["id", "texto"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["traducoes"],
    "additionalProperties": False,
}

NOMES_IDIOMA = {
    "en": "inglês", "es": "espanhol", "fr": "francês", "de": "alemão", "it": "italiano",
    "ja": "japonês", "ko": "coreano", "ru": "russo", "pt": "português",
}


def traduzir_frases(frases: list[Frase], idioma_origem: str, *, usuario_id: int,
                    video_id: int | None = None, cliente=None) -> list[Frase]:
    """Devolve as frases com o texto em portugues do Brasil, na mesma ordem."""
    if not frases:
        return []
    sistema = ia.carregar_prompt("traducao_legenda.md",
                                 idioma=NOMES_IDIOMA.get(idioma_origem, idioma_origem))
    mensagem = "\n".join(f"[{f.id}] {f.texto}" for f in frases)
    ids = [f.id for f in frases]

    dados = ia.pedir_json(
        modelo=config.MODELO_RAPIDO,
        esforco=config.ESFORCO_RAPIDO,
        sistema=sistema,
        mensagem=mensagem,
        esquema=ESQUEMA,
        validar=lambda d: validar_traducoes(d, ids),
        etapa="traducao_legenda",
        usuario_id=usuario_id,
        video_id=video_id,
        cliente=cliente,
    )
    por_id = {t["id"]: t["texto"].strip() for t in dados["traducoes"]}
    return [
        Frase(id=f.id, inicio=f.inicio, fim=f.fim, texto=por_id[f.id],
              palavras=repartir_tempo(por_id[f.id], f.inicio, f.fim))
        for f in frases
    ]


def validar_traducoes(dados: dict, ids_esperados: list[int]) -> list[str]:
    """Confere que voltou exatamente uma traducao nao vazia para cada frase enviada."""
    problemas: list[str] = []
    recebidos = [t["id"] for t in dados.get("traducoes", [])]
    faltando = [i for i in ids_esperados if i not in recebidos]
    sobrando = [i for i in recebidos if i not in ids_esperados]
    repetidos = sorted({i for i in recebidos if recebidos.count(i) > 1})
    if faltando:
        problemas.append(f"Faltou a tradução das frases: {faltando}.")
    if sobrando:
        problemas.append(f"Vieram frases que não foram enviadas: {sobrando}.")
    if repetidos:
        problemas.append(f"Estas frases vieram mais de uma vez: {repetidos}.")
    for t in dados.get("traducoes", []):
        if not t["texto"].strip():
            problemas.append(f"A tradução da frase {t['id']} está vazia.")
    return problemas


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print('Uso: python -m app.cerebro.traduzir "texto" idioma   (ex.: en)')
        sys.exit(1)
    banco.criar_tabelas()
    _frase = Frase(0, 0.0, 3.0, sys.argv[1], repartir_tempo(sys.argv[1], 0.0, 3.0))
    try:
        _resultado = traduzir_frases([_frase], sys.argv[2], usuario_id=config.USUARIO_PADRAO)
    except ia.ErroIA as _erro:
        print("Nao deu certo:", _erro)
        sys.exit(1)
    print(_resultado[0].texto)
