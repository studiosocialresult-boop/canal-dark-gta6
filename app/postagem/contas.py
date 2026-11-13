"""Contas conectadas e publicacoes: leitura e gravacao no banco.

As credenciais passam sempre pelo cofre (criptografadas). Nada aqui conversa com as redes.
"""
import json
from contextlib import closing

from app import banco
from app.postagem import cofre
from app.postagem.redes import REDES, Credenciais

CAMPOS_CONTA = {"nome", "foto", "ativa", "posts_por_dia", "estado", "erro"}
CAMPOS_PUBLICACAO = {"titulo", "legenda", "opcoes", "agendada_para", "estado", "tentativas", "proxima_tentativa",
                     "id_externo", "url", "erro", "publicado_em"}


def _dict(linha):
    return dict(linha) if linha is not None else None


# ---------- contas ----------

def salvar_conta(usuario_id: int, rede: str, id_externo: str, nome: str, foto: str | None, credenciais: dict,
                 posts_por_dia: int) -> int:
    """Grava a conta conectada. Se ja existia, atualiza o acesso e volta a ficar conectada."""
    if rede not in REDES:
        raise ValueError("Rede desconhecida.")
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute(
            "INSERT INTO contas (usuario_id, rede, id_externo, nome, foto, credenciais, posts_por_dia) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (usuario_id, rede, id_externo) DO UPDATE SET "
            "nome = excluded.nome, foto = excluded.foto, credenciais = excluded.credenciais, estado = 'conectada', "
            "erro = NULL, atualizado_em = datetime('now')",
            (usuario_id, rede, str(id_externo), nome, foto, cofre.guardar(credenciais), posts_por_dia))
        return conexao.execute("SELECT id FROM contas WHERE usuario_id = ? AND rede = ? AND id_externo = ?",
                               (usuario_id, rede, str(id_externo))).fetchone()["id"]


def listar_contas(usuario_id: int) -> list[dict]:
    """Contas do usuario, sem as credenciais (o painel nunca recebe os tokens)."""
    with closing(banco.conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT id, usuario_id, rede, id_externo, nome, foto, ativa, posts_por_dia, estado, erro, criado_em "
            "FROM contas WHERE usuario_id = ? ORDER BY rede, nome", (usuario_id,)).fetchall()
    return [dict(l) for l in linhas]


def ler_conta(conta_id: int) -> dict | None:
    with closing(banco.conectar()) as conexao:
        linha = conexao.execute("SELECT * FROM contas WHERE id = ?", (conta_id,)).fetchone()
    if linha is None:
        return None
    conta = dict(linha)
    conta.pop("credenciais")
    return conta


def credenciais_da_conta(conta_id: int) -> Credenciais:
    with closing(banco.conectar()) as conexao:
        linha = conexao.execute("SELECT credenciais FROM contas WHERE id = ?", (conta_id,)).fetchone()
    return Credenciais(cofre.abrir(linha["credenciais"]))


def regravar_credenciais(conta_id: int, credenciais: Credenciais) -> None:
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute("UPDATE contas SET credenciais = ?, atualizado_em = datetime('now') WHERE id = ?",
                        (cofre.guardar(credenciais.dados), conta_id))


def atualizar_conta(conta_id: int, **campos) -> None:
    if set(campos) - CAMPOS_CONTA:
        raise KeyError("Campo nao permitido.")
    if not campos:
        return
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute(f"UPDATE contas SET {', '.join(f'{k} = ?' for k in campos)}, atualizado_em = datetime('now') "
                        "WHERE id = ?", (*campos.values(), conta_id))


def remover_conta(conta_id: int) -> None:
    """Remove a conta e o que estava agendado para ela (o que ja foi publicado continua na rede)."""
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute("DELETE FROM contas WHERE id = ?", (conta_id,))


# ---------- publicacoes ----------

def criar_publicacao(usuario_id: int, conta_id: int, *, origem: str, corte_id: int | None, saida_id: int | None,
                     arquivo: str, chave_video: str, titulo: str, legenda: str, opcoes: dict,
                     agendada_para: str) -> int:
    with closing(banco.conectar()) as conexao, conexao:
        return conexao.execute(
            "INSERT INTO publicacoes (usuario_id, conta_id, origem, corte_id, saida_id, arquivo, chave_video, titulo, "
            "legenda, opcoes, agendada_para) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (usuario_id, conta_id, origem, corte_id, saida_id, arquivo, chave_video, titulo, legenda,
             json.dumps(opcoes, ensure_ascii=False), agendada_para)).lastrowid


def chaves_usadas(conta_id: int) -> set[str]:
    """Conteudos que ja foram (ou serao) publicados nesta conta."""
    with closing(banco.conectar()) as conexao:
        return {l["chave_video"] for l in conexao.execute(
            "SELECT chave_video FROM publicacoes WHERE conta_id = ? AND estado != 'cancelada'", (conta_id,))}


def horarios_ocupados(conta_id: int) -> list[str]:
    with closing(banco.conectar()) as conexao:
        return [l["agendada_para"] for l in conexao.execute(
            "SELECT agendada_para FROM publicacoes WHERE conta_id = ? AND estado IN ('agendada', 'publicando', 'publicada')",
            (conta_id,))]


def ler_publicacao(publicacao_id: int) -> dict | None:
    with closing(banco.conectar()) as conexao:
        linha = _dict(conexao.execute("SELECT * FROM publicacoes WHERE id = ?", (publicacao_id,)).fetchone())
    if linha:
        linha["opcoes"] = json.loads(linha["opcoes"] or "{}")
    return linha


def listar_publicacoes(usuario_id: int, desde: str | None = None, ate: str | None = None) -> list[dict]:
    """Publicacoes com a conta, ordenadas pelo horario."""
    filtros, valores = ["p.usuario_id = ?"], [usuario_id]
    if desde:
        filtros.append("p.agendada_para >= ?"); valores.append(desde)
    if ate:
        filtros.append("p.agendada_para < ?"); valores.append(ate)
    with closing(banco.conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT p.*, c.rede, c.nome AS conta_nome, c.foto AS conta_foto FROM publicacoes p "
            f"JOIN contas c ON c.id = p.conta_id WHERE {' AND '.join(filtros)} ORDER BY p.agendada_para, p.id",
            valores).fetchall()
    resultado = []
    for linha in linhas:
        item = dict(linha)
        item["opcoes"] = json.loads(item["opcoes"] or "{}")
        resultado.append(item)
    return resultado


def publicacoes_vencidas(agora_utc: str) -> list[dict]:
    """O que ja passou da hora e ainda nao foi publicado (inclui novas tentativas que chegaram na vez)."""
    with closing(banco.conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT p.* FROM publicacoes p JOIN contas c ON c.id = p.conta_id "
            "WHERE p.estado = 'agendada' AND c.ativa = 1 AND c.estado = 'conectada' AND p.agendada_para <= ? "
            "AND (p.proxima_tentativa IS NULL OR p.proxima_tentativa <= ?) ORDER BY p.agendada_para, p.id",
            (agora_utc, agora_utc)).fetchall()
    return [dict(l) | {"opcoes": json.loads(l["opcoes"] or "{}")} for l in linhas]


def publicadas_nas_ultimas_24h(conta_id: int, agora_utc: str) -> int:
    with closing(banco.conectar()) as conexao:
        return conexao.execute(
            "SELECT COUNT(*) FROM publicacoes WHERE conta_id = ? AND estado = 'publicada' "
            "AND publicado_em > datetime(?, '-1 day')", (conta_id, agora_utc)).fetchone()[0]


def atualizar_publicacao(publicacao_id: int, **campos) -> None:
    if set(campos) - CAMPOS_PUBLICACAO:
        raise KeyError("Campo nao permitido.")
    if "opcoes" in campos and isinstance(campos["opcoes"], dict):
        campos["opcoes"] = json.dumps(campos["opcoes"], ensure_ascii=False)
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute(f"UPDATE publicacoes SET {', '.join(f'{k} = ?' for k in campos)} WHERE id = ?",
                        (*campos.values(), publicacao_id))


def retomar_publicacoes_interrompidas() -> None:
    """Ao religar, o que estava 'publicando' volta para a fila (a rede pode nao ter recebido)."""
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute("UPDATE publicacoes SET estado = 'agendada' WHERE estado = 'publicando'")
