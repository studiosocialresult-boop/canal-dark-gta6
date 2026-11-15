"""Leituras dos numeros dos posts: tudo o que le e grava no banco.

Nada aqui conversa com as redes. Horarios em UTC ('AAAA-MM-DD HH:MM:SS').
"""
from contextlib import closing

from app import banco
from app.postagem.redes import Numeros

MARCOS_VALIDOS = ("atual", "24h", "3d", "7d")


def gravar_leitura(usuario_id: int, publicacao_id: int, marco: str, numeros: Numeros, lido_em: str) -> None:
    """Grava (ou regrava) a leitura de um post naquele marco."""
    if marco not in MARCOS_VALIDOS:
        raise ValueError(f"Marco desconhecido: {marco}")
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute(
            "INSERT INTO leituras (usuario_id, publicacao_id, marco, visualizacoes, curtidas, comentarios, lido_em) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (publicacao_id, marco) DO UPDATE SET "
            "visualizacoes = excluded.visualizacoes, curtidas = excluded.curtidas, "
            "comentarios = excluded.comentarios, lido_em = excluded.lido_em",
            (usuario_id, publicacao_id, marco, numeros.visualizacoes, numeros.curtidas, numeros.comentarios, lido_em))


def marcos_gravados(publicacao_ids: list[int]) -> dict[int, set[str]]:
    resultado = {p: set() for p in publicacao_ids}
    if not publicacao_ids:
        return resultado
    with closing(banco.conectar()) as conexao:
        for linha in conexao.execute(
                f"SELECT publicacao_id, marco FROM leituras WHERE publicacao_id IN ({_lugares(publicacao_ids)})",
                publicacao_ids):
            resultado[linha["publicacao_id"]].add(linha["marco"])
    return resultado


def publicacoes_para_ler(agora_utc: str, idade_maxima_h: int) -> list[dict]:
    """Posts publicados ha menos de `idade_maxima_h` horas, ainda na rede, de contas conectadas."""
    with closing(banco.conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT p.id, p.usuario_id, p.conta_id, c.rede, p.id_externo, p.publicado_em FROM publicacoes p "
            "JOIN contas c ON c.id = p.conta_id "
            "WHERE p.estado = 'publicada' AND p.id_externo IS NOT NULL AND p.removida_em IS NULL "
            "AND c.estado = 'conectada' AND p.publicado_em IS NOT NULL "
            "AND p.publicado_em >= datetime(?, ?) ORDER BY p.conta_id, p.publicado_em, p.id",
            (agora_utc, f"-{int(idade_maxima_h)} hours")).fetchall()
    return [dict(l) for l in linhas]


def marcar_removida(publicacao_id: int, agora_utc: str) -> None:
    """A rede disse que o post nao existe mais: para de ser lido (o historico fica)."""
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute("UPDATE publicacoes SET removida_em = ? WHERE id = ?", (agora_utc, publicacao_id))


def linhas_do_relatorio(usuario_id: int, desde_utc: str, ate_utc: str, conta_id: int | None = None) -> list[dict]:
    """Posts publicados em [desde, ate), com a conta, o corte de origem e as leituras de cada marco."""
    filtros = ["p.usuario_id = ?", "p.estado = 'publicada'", "p.publicado_em >= ?", "p.publicado_em < ?"]
    valores: list = [usuario_id, desde_utc, ate_utc]
    if conta_id is not None:
        filtros.append("p.conta_id = ?")
        valores.append(conta_id)
    with closing(banco.conectar()) as conexao:
        linhas = [dict(l) for l in conexao.execute(
            "SELECT p.id, p.titulo, p.url, c.rede, p.conta_id, c.nome AS conta_nome, p.origem, p.corte_id, "
            "p.publicado_em, p.removida_em, co.modo, co.nota, v.canal AS fonte FROM publicacoes p "
            "JOIN contas c ON c.id = p.conta_id LEFT JOIN cortes co ON co.id = p.corte_id "
            "LEFT JOIN videos v ON v.id = co.video_id "
            f"WHERE {' AND '.join(filtros)} ORDER BY p.publicado_em, p.id", valores)]
        ids = [l["id"] for l in linhas]
        leituras: dict[int, dict] = {i: {} for i in ids}
        if ids:
            for l in conexao.execute(
                    "SELECT publicacao_id, marco, visualizacoes, curtidas, comentarios FROM leituras "
                    f"WHERE publicacao_id IN ({_lugares(ids)})", ids):
                leituras[l["publicacao_id"]][l["marco"]] = Numeros(l["visualizacoes"], l["curtidas"], l["comentarios"])
    for linha in linhas:
        linha["leituras"] = leituras[linha["id"]]
    return linhas


def visualizacoes_por_corte(usuario_id: int) -> dict[int, int]:
    """Soma das visualizacoes (leitura mais recente) de todos os posts de cada corte."""
    with closing(banco.conectar()) as conexao:
        return {l["corte_id"]: l["total"] for l in conexao.execute(
            "SELECT p.corte_id, SUM(l.visualizacoes) AS total FROM leituras l "
            "JOIN publicacoes p ON p.id = l.publicacao_id "
            "WHERE p.usuario_id = ? AND l.marco = 'atual' AND p.corte_id IS NOT NULL "
            "AND l.visualizacoes IS NOT NULL GROUP BY p.corte_id", (usuario_id,))}


def _lugares(itens: list) -> str:
    return ", ".join("?" * len(itens))
