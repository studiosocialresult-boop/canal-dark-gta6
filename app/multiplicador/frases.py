"""Frases: a IA (Haiku, barata) escreve variacoes de uma frase base.

As instrucoes ficam em prompts/frases_variacoes.md. A resposta e conferida
(quantidade, tamanho, repeticao, emoji) e a IA e chamada de novo se vier errada.

Rodar sozinho (gasta uma fracao de centavo):
    python -m app.multiplicador.frases "A página perfeita para quem quer saber tudo do GTA 6" 5
"""
import re
import sys
import unicodedata

from app import banco, config, ia

MAX_CARACTERES = 110
LIMITE_QUANTIDADE = 20

ESQUEMA = {
    "type": "object",
    "properties": {"frases": {"type": "array", "items": {"type": "string"}}},
    "required": ["frases"],
    "additionalProperties": False,
}

PROIBIDO = re.compile(r"[\U00010000-\U0010FFFF#@\"“”]|\.\.\.|…")


def _normal(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", sem_acento).strip()


def validar_frases(dados: dict, base: str, quantidade: int) -> list[str]:
    """Confere a resposta da IA. Devolve a lista de problemas (vazia: esta boa)."""
    frases = [f.strip() for f in dados.get("frases", [])]
    problemas = []
    if len(frases) != quantidade:
        problemas.append(f"Vieram {len(frases)} frases e eram {quantidade} pedidas.")
    normais = [_normal(f) for f in frases]
    repetidas = sorted({f for f, n in zip(frases, normais) if normais.count(n) > 1})
    if repetidas:
        problemas.append(f"Estas frases estão repetidas: {repetidas}.")
    for numero, frase in enumerate(frases, start=1):
        if not frase:
            problemas.append(f"A frase {numero} está vazia.")
        elif len(frase) > MAX_CARACTERES:
            problemas.append(f"A frase {numero} tem {len(frase)} caracteres e o máximo é {MAX_CARACTERES}.")
        elif PROIBIDO.search(frase):
            problemas.append(f"A frase {numero} tem emoji, hashtag, aspas ou reticências. Tire.")
        elif _normal(frase) == _normal(base):
            problemas.append(f"A frase {numero} é igual à ideia base. Escreva uma variação de verdade.")
    return problemas


def gerar_variacoes(base: str, quantidade: int, *, usuario_id: int, cliente=None) -> list[str]:
    """Devolve `quantidade` variacoes da frase base. Levanta ia.ErroIA se a IA nao entregar."""
    base = " ".join(base.split())
    if len(base) < 8:
        raise ValueError("Escreva uma ideia um pouco mais completa (pelo menos uma frase curta).")
    if not 1 <= quantidade <= LIMITE_QUANTIDADE:
        raise ValueError(f"Peça de 1 a {LIMITE_QUANTIDADE} variações por vez.")
    dados = ia.pedir_json(
        modelo=config.MODELO_RAPIDO,
        esforco=config.ESFORCO_RAPIDO,
        sistema=ia.carregar_prompt("frases_variacoes.md", max_caracteres=MAX_CARACTERES, quantidade=quantidade),
        mensagem=f"Ideia base: {base}\nQuantidade de variações: {quantidade}",
        esquema=ESQUEMA,
        validar=lambda d: validar_frases(d, base, quantidade),
        etapa="frases_variacoes",
        usuario_id=usuario_id,
        cliente=cliente,
    )
    return [f.strip() for f in dados["frases"]]


if __name__ == "__main__":
    if len(sys.argv) != 3 or not sys.argv[2].isdigit():
        print('Uso: python -m app.multiplicador.frases "ideia base" quantidade')
        sys.exit(1)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    banco.criar_tabelas()
    try:
        for _numero, _frase in enumerate(gerar_variacoes(sys.argv[1], int(sys.argv[2]),
                                                          usuario_id=config.USUARIO_PADRAO), start=1):
            print(f"{_numero}. {_frase}")
    except (ia.ErroIA, ValueError) as _erro:
        print("Nao deu certo:", _erro)
        sys.exit(1)
