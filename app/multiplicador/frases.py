"""Frases: a IA (Haiku, barata) escreve variacoes de uma frase base.

As instrucoes ficam em prompts/frases_variacoes.md. A resposta e conferida
(quantidade, tamanho, repeticao, emoji) e a IA e chamada de novo se vier errada.

Rodar sozinho (gasta uma fracao de centavo):
    python -m app.multiplicador.frases "A página perfeita para quem quer saber tudo do GTA 6" 5

Frases casadas com um video (a IA le o titulo dele):
    gerar_para_video("Rockstar confirma GTA 6 a 30 FPS nos consoles", None, 3, usuario_id=1)
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


def gerar_para_video(titulo: str, motivo: str | None, quantidade: int, *, usuario_id: int, cliente=None) -> list[str]:
    """Frases escritas para UM video, a partir do titulo dele (e do motivo de o corte ter sido escolhido).

    Prompt em prompts/frases_do_video.md. Devolve `quantidade` frases, da mais forte para a mais fraca.
    """
    titulo = " ".join((titulo or "").split())
    if len(titulo) < 3:
        raise ValueError("Este vídeo não tem título para a IA se basear.")
    if not 1 <= quantidade <= LIMITE_QUANTIDADE:
        raise ValueError(f"Peça de 1 a {LIMITE_QUANTIDADE} frases por vídeo.")
    linhas = [f"Título do vídeo: {titulo}"]
    motivo = " ".join((motivo or "").split())
    if motivo:
        linhas.append(f"Por que este trecho foi escolhido: {motivo[:600]}")
    linhas.append(f"Quantidade de frases: {quantidade}")
    mensagem = "\n".join(linhas)
    dados = ia.pedir_json(
        modelo=config.MODELO_RAPIDO,
        esforco=config.ESFORCO_RAPIDO,
        sistema=ia.carregar_prompt("frases_do_video.md", max_caracteres=MAX_CARACTERES, quantidade=quantidade),
        mensagem=mensagem,
        esquema=ESQUEMA,
        validar=lambda d: validar_frases(d, titulo, quantidade),
        etapa="frases_do_video",
        usuario_id=usuario_id,
        cliente=cliente,
    )
    return [f.strip() for f in dados["frases"]]


def frase_do_corte(corte, *, usuario_id: int, cliente=None) -> tuple[str, bool]:
    """A frase do gancho de um corte: a guardada ou, na primeira vez, uma nova escrita pela IA (e guardada).

    Devolve (frase, nova)."""
    if corte["frase_gancho"]:
        return corte["frase_gancho"], False
    frase = gerar_para_video(corte["titulo"], corte["motivo"], 1, usuario_id=usuario_id, cliente=cliente)[0]
    banco.atualizar_corte(corte["id"], frase_gancho=frase)
    return frase, True


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
