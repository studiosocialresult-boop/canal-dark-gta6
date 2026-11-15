"""Relatorio de desempenho: transforma as leituras guardadas em numeros prontos para a tela.

So le o banco; nao fala com as redes e nao usa IA. Os grupos, as listas e a variacao usam a foto de
24 h de cada post (todos os posts comparados na mesma idade). Os totais usam a leitura mais recente.

Rodar para ver o relatorio de 7 dias de visualizacoes:
    python -m app.desempenho.relatorio
"""
from datetime import datetime, timedelta

from app.desempenho import repositorio
from app.postagem import agendador, contas
from app.postagem.redes import REDES

PERIODOS = (7, 30, 90)
MEDIDAS = ("visualizacoes", "curtidas", "comentarios")
MINIMO_POR_GRUPO = 3
FAIXAS_NOTA = ("80 ou mais", "70 a 79", "abaixo de 70")
MAXIMO_FONTES = 5
TAMANHO_LISTA = 5


def montar(usuario_id: int, dias: int, medida: str, conta_id: int | None = None,
           momento_agora: datetime | None = None) -> dict:
    if dias not in PERIODOS:
        raise ValueError(f"Periodo invalido: {dias}")
    if medida not in MEDIDAS:
        raise ValueError(f"Medida invalida: {medida}")
    agora = momento_agora or agendador.agora()
    inicio = agora - timedelta(days=dias)
    anterior = agora - timedelta(days=2 * dias)
    linhas = repositorio.linhas_do_relatorio(usuario_id, agendador.texto(anterior), agendador.texto(agora), conta_id)
    inicio_texto = agendador.texto(inicio)
    atuais = [l for l in linhas if l["publicado_em"] >= inicio_texto]
    anteriores = [l for l in linhas if l["publicado_em"] < inicio_texto]

    posts = [_post(l, medida) for l in atuais]
    com_foto = [(l, p) for l, p in zip(atuais, posts) if p["24h"] is not None]
    ordenados = sorted((p for _, p in com_foto), key=lambda p: (-p["24h"], p["id"]))
    melhores = ordenados[:TAMANHO_LISTA]
    ids_melhores = {p["id"] for p in melhores}
    piores = [p for p in reversed(ordenados) if p["id"] not in ids_melhores][:TAMANHO_LISTA]

    por_hora = _valores_por_hora(com_foto)
    return {
        "dias": dias, "medida": medida,
        "totais": _totais(atuais, anteriores, medida, por_hora),
        "grupos": {
            "modo": _por_rotulo(com_foto, ("narrado", "original"), lambda l: l["modo"] if l["corte_id"] else None),
            "nota": _por_rotulo(com_foto, FAIXAS_NOTA, lambda l: _faixa_nota(l["nota"])),
            "rede": _grupo_rede(atuais, com_foto),
            "fonte": _grupo_fonte(com_foto),
            "tipo": _por_rotulo(com_foto, ("corte", "template"), lambda l: l["origem"]),
            "hora": [_item(str(h), por_hora[h]) for h in range(24)],
        },
        "melhores": melhores, "piores": piores,
        "sem_medida": _redes_sem_medida(atuais, medida),
        "contas": [{"id": c["id"], "nome": c["nome"], "rede": c["rede"]} for c in contas.listar_contas(usuario_id)],
    }


def _valor(numeros, medida: str):
    return None if numeros is None else getattr(numeros, medida)


def _local(texto_utc: str) -> datetime:
    return agendador.momento(texto_utc).astimezone(agendador._fuso())


def _post(linha: dict, medida: str) -> dict:
    leituras = linha["leituras"]
    return {"id": linha["id"], "titulo": linha["titulo"], "url": linha["url"], "rede": linha["rede"],
            "conta": linha["conta_nome"], "corte_id": linha["corte_id"],
            "publicado_em": _local(linha["publicado_em"]).strftime("%Y-%m-%dT%H:%M"),
            "removido": bool(linha["removida_em"]),
            **{marco: _valor(leituras.get(marco), medida) for marco in ("atual", "24h", "3d", "7d")}}


def _faixa_nota(nota) -> str | None:
    if nota is None:
        return None
    return FAIXAS_NOTA[0] if nota >= 80 else FAIXAS_NOTA[1] if nota >= 70 else FAIXAS_NOTA[2]


def _media(valores: list[int]) -> int | None:
    if len(valores) < MINIMO_POR_GRUPO:
        return None
    return round(sum(valores) / len(valores))


def _item(rotulo: str, valores: list[int]) -> dict:
    return {"rotulo": rotulo, "posts": len(valores), "media": _media(valores)}


def _por_rotulo(com_foto: list, rotulos: tuple, chave) -> list[dict]:
    valores = {r: [] for r in rotulos}
    for linha, post in com_foto:
        rotulo = chave(linha)
        if rotulo in valores:
            valores[rotulo].append(post["24h"])
    return [_item(r, valores[r]) for r in rotulos]


def _grupo_rede(atuais: list, com_foto: list) -> list[dict]:
    valores = {l["rede"]: [] for l in atuais}
    for linha, post in com_foto:
        valores[linha["rede"]].append(post["24h"])
    return [_item(REDES[r]["nome"], v) for r, v in sorted(valores.items(), key=lambda i: REDES[i[0]]["nome"])]


def _grupo_fonte(com_foto: list) -> list[dict]:
    valores: dict[str, list[int]] = {}
    for linha, post in com_foto:
        if linha["fonte"]:
            valores.setdefault(linha["fonte"], []).append(post["24h"])
    mais_usadas = sorted(valores.items(), key=lambda i: (-len(i[1]), i[0]))[:MAXIMO_FONTES]
    return [_item(f, v) for f, v in mais_usadas]


def _valores_por_hora(com_foto: list) -> dict[int, list[int]]:
    valores: dict[int, list[int]] = {h: [] for h in range(24)}
    for linha, post in com_foto:
        valores[_local(linha["publicado_em"]).hour].append(post["24h"])
    return valores


def _melhor_horario(valores: dict[int, list[int]]) -> dict | None:
    melhor, melhor_media = None, None
    for h in range(23):                                      # janelas (h, h+1): 0-1 ... 22-23
        juntos = valores[h] + valores[h + 1]
        if len(juntos) < MINIMO_POR_GRUPO:
            continue
        media = sum(juntos) / len(juntos)
        if melhor_media is None or media > melhor_media:
            melhor, melhor_media = h, media
    return None if melhor is None else {"inicio_h": melhor, "fim_h": melhor + 2}


def _fotos_24h(linhas: list, medida: str) -> list[int]:
    valores = [_valor(l["leituras"].get("24h"), medida) for l in linhas]
    return [v for v in valores if v is not None]


def _variacao(atuais: list, anteriores: list, medida: str) -> float | None:
    """Media por post (foto de 24 h) deste periodo contra a do anterior. Compara medias, nao somas:
    os posts mais novos ainda nao tem foto, e uma soma daria queda falsa."""
    agora, antes = _fotos_24h(atuais, medida), _fotos_24h(anteriores, medida)
    if len(agora) < MINIMO_POR_GRUPO or len(antes) < MINIMO_POR_GRUPO:
        return None
    media_antes = sum(antes) / len(antes)
    if not media_antes:
        return None
    return round((sum(agora) / len(agora) - media_antes) / media_antes * 100, 1)


def _totais(atuais: list, anteriores: list, medida: str, por_hora: dict) -> dict:
    totais: dict = {"posts": len(atuais)}
    for m in MEDIDAS:
        valores = [_valor(l["leituras"].get("atual"), m) for l in atuais]
        valores = [v for v in valores if v is not None]
        totais[m] = sum(valores) if valores else None
    totais["variacao_pct"] = _variacao(atuais, anteriores, medida)
    totais["melhor_horario"] = _melhor_horario(por_hora)
    return totais


def _redes_sem_medida(atuais: list, medida: str) -> list[str]:
    """Redes com post lido no periodo mas sem nenhum numero dessa medida (ex.: Facebook nao informa views)."""
    lidas: dict[str, bool] = {}
    for l in atuais:
        if not l["leituras"]:
            continue
        tem = any(_valor(n, medida) is not None for n in l["leituras"].values())
        lidas[l["rede"]] = lidas.get(l["rede"], False) or tem
    return sorted(r for r, tem in lidas.items() if not tem)


if __name__ == "__main__":
    import json
    from app import banco
    banco.criar_tabelas()
    resultado = montar(1, 7, "visualizacoes")
    for chave in ("melhores", "piores", "contas"):
        resultado.pop(chave)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
