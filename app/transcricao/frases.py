"""Divide a lista de palavras da transcricao em frases completas.

O cerebro escolhe os cortes por frase (da frase X ate a frase Y). Por isso
todo corte comeca e termina numa frase inteira, nunca no meio de uma fala.

Rodar sozinho mostra um exemplo:
    python -m app.transcricao.frases
"""
from app.contratos import Frase, Palavra

FIM_DE_FRASE = (".", "!", "?", "…")
PAUSA_LONGA_S = 1.2        # silencio que encerra a frase mesmo sem pontuacao
FRASE_LONGA_S = 15.0       # depois disso, quebra na primeira virgula ou pausa curta
FRASE_MAXIMA_S = 25.0      # limite duro, para fala sem nenhuma pontuacao
PAUSA_CURTA_S = 0.4


def montar_frases(palavras: list[Palavra]) -> list[Frase]:
    """Agrupa as palavras em frases, usando a pontuacao e as pausas da fala."""
    palavras = [Palavra(p.texto.strip(), p.inicio, p.fim) for p in palavras if p.texto.strip()]
    frases: list[Frase] = []
    atual: list[Palavra] = []

    for posicao, palavra in enumerate(palavras):
        atual.append(palavra)
        proxima = palavras[posicao + 1] if posicao + 1 < len(palavras) else None
        if proxima is None or _deve_fechar(atual, palavra, proxima):
            frases.append(Frase(
                id=len(frases),
                inicio=atual[0].inicio,
                fim=atual[-1].fim,
                texto=" ".join(p.texto for p in atual),
                palavras=atual,
            ))
            atual = []
    return frases


def _deve_fechar(atual: list[Palavra], palavra: Palavra, proxima: Palavra) -> bool:
    pausa = proxima.inicio - palavra.fim
    duracao = palavra.fim - atual[0].inicio
    texto = palavra.texto.rstrip("\"'”’)]")

    if pausa >= PAUSA_LONGA_S:
        return True
    if texto.endswith(FIM_DE_FRASE):
        # "3.5", "Sr. Silva" e "U.S. market" nao encerram frase: a proxima palavra
        # tem que comecar com maiuscula ou numero, ou vir depois de uma pausa.
        inicial = proxima.texto.lstrip("\"'“‘([")[:1]
        return inicial.isupper() or inicial.isdigit() or pausa >= 0.3
    if duracao >= FRASE_MAXIMA_S:
        return True
    if duracao >= FRASE_LONGA_S and (texto.endswith((",", ";", ":")) or pausa >= PAUSA_CURTA_S):
        return True
    return False


def repartir_tempo(texto: str, inicio: float, fim: float) -> list[Palavra]:
    """Distribui o tempo de uma frase entre as palavras de um texto.

    Usado na legenda traduzida: a traducao nao tem o tempo de cada palavra,
    entao cada palavra recebe uma fatia proporcional ao seu tamanho.
    """
    termos = texto.split()
    if not termos:
        return []
    pesos = [len(t) + 1 for t in termos]
    total = sum(pesos)
    duracao = max(fim - inicio, 0.0)
    palavras = []
    cursor = inicio
    for termo, peso in zip(termos, pesos):
        fatia = duracao * peso / total
        palavras.append(Palavra(termo, round(cursor, 3), round(cursor + fatia, 3)))
        cursor += fatia
    palavras[-1].fim = fim
    return palavras


if __name__ == "__main__":
    _fala = "O trailer saiu hoje. E olha, ninguem esperava isso! Sera que o mapa e maior?"
    _palavras = repartir_tempo(_fala, 0.0, 9.0)
    for _frase in montar_frases(_palavras):
        print(f"[{_frase.id}] ({_frase.inicio:.1f}-{_frase.fim:.1f}) {_frase.texto}")
