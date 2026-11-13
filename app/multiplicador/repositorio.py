"""Repositorio: le e grava templates, midias, frases, videos gerados e perfis salvos.

Toda a conversa com o banco dos templates fica aqui; o painel e o render so
chamam estas funcoes.
"""
import json
import shutil
from contextlib import closing

from app import banco, config
from app.multiplicador import modelos

CAMPOS_MIDIA = {"zona", "ajuste", "zoom", "pos_x", "pos_y", "selecionada", "rotulo"}
AJUSTES = ("preencher", "caber")


def _dict(linha) -> dict | None:
    return dict(linha) if linha is not None else None


# ---------- templates ----------

def criar_template(usuario_id: int, layout: str, nome: str = "Novo template") -> int:
    if layout not in modelos.LAYOUTS:
        raise ValueError("Layout desconhecido.")
    with closing(banco.conectar()) as conexao, conexao:
        return conexao.execute(
            "INSERT INTO templates (usuario_id, nome, layout) VALUES (?, ?, ?)",
            (usuario_id, nome.strip() or "Novo template", layout)).lastrowid


def ler_template(template_id: int) -> dict | None:
    with closing(banco.conectar()) as conexao:
        linha = conexao.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
    if linha is None:
        return None
    dados = dict(linha)
    dados["config"] = json.loads(dados["config"] or "{}")
    return dados


def listar_templates(usuario_id: int) -> list[dict]:
    """Templates do usuario, do mais recente para o mais antigo, com contadores e a capa."""
    with closing(banco.conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT t.*, "
            " (SELECT COUNT(*) FROM template_midias m WHERE m.template_id = t.id AND m.selecionada = 1) AS n_midias, "
            " (SELECT COUNT(*) FROM template_frases f WHERE f.template_id = t.id AND f.selecionada = 1) AS n_frases, "
            " (SELECT COUNT(*) FROM template_saidas s WHERE s.template_id = t.id) AS n_saidas, "
            " (SELECT COUNT(*) FROM template_saidas s WHERE s.template_id = t.id AND s.estado = 'pronto') AS n_prontas, "
            " (SELECT COUNT(*) FROM template_saidas s WHERE s.template_id = t.id AND s.estado = 'falhou') AS n_falhas, "
            " (SELECT s.id FROM template_saidas s WHERE s.template_id = t.id AND s.estado = 'pronto' "
            "   ORDER BY s.id LIMIT 1) AS saida_capa "
            "FROM templates t WHERE t.usuario_id = ? ORDER BY t.atualizado_em DESC, t.id DESC",
            (usuario_id,)).fetchall()
    return [dict(l) | {"config": json.loads(l["config"] or "{}")} for l in linhas]


def atualizar_template(template_id: int, *, nome: str | None = None, layout: str | None = None,
                       config_nova: dict | None = None, passo: int | None = None) -> None:
    """Altera so o que foi informado. A configuracao nova e mesclada com a que ja existe."""
    atual = ler_template(template_id)
    if atual is None:
        raise KeyError("Template nao encontrado.")
    if layout is not None and layout not in modelos.LAYOUTS:
        raise ValueError("Layout desconhecido.")
    cfg = atual["config"]
    if config_nova:
        for secao, valores in config_nova.items():
            if secao in modelos.CONFIG_PADRAO and isinstance(valores, dict):
                cfg.setdefault(secao, {}).update(valores)
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute(
            "UPDATE templates SET nome = ?, layout = ?, config = ?, passo = ?, "
            "atualizado_em = datetime('now') WHERE id = ?",
            ((nome or atual["nome"]).strip() or atual["nome"], layout or atual["layout"],
             json.dumps(cfg, ensure_ascii=False), passo or atual["passo"], template_id))


def excluir_template(template_id: int) -> None:
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute("DELETE FROM templates WHERE id = ?", (template_id,))
    shutil.rmtree(pasta_do_template(template_id), ignore_errors=True)


def pasta_do_template(template_id: int):
    return config.PASTA_DADOS / "templates" / str(template_id)


# ---------- midias ----------

def listar_midias(template_id: int) -> list[dict]:
    with closing(banco.conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT m.*, c.titulo AS corte_titulo, c.inicio_s, c.fim_s "
            "FROM template_midias m LEFT JOIN cortes c ON c.id = m.corte_id "
            "WHERE m.template_id = ? ORDER BY m.zona, m.id", (template_id,)).fetchall()
    return [dict(l) for l in linhas]


def ler_midia(midia_id: int) -> dict | None:
    with closing(banco.conectar()) as conexao:
        return _dict(conexao.execute("SELECT * FROM template_midias WHERE id = ?", (midia_id,)).fetchone())


def adicionar_cortes(template_id: int, corte_ids: list[int], zona: int = 1) -> int:
    """Poe cortes (o trecho do video original, sem legenda) como midias. Devolve quantos entraram."""
    entrou = 0
    with closing(banco.conectar()) as conexao, conexao:
        for corte_id in corte_ids:
            corte = conexao.execute("SELECT id, titulo FROM cortes WHERE id = ?", (corte_id,)).fetchone()
            ja = conexao.execute(
                "SELECT 1 FROM template_midias WHERE template_id = ? AND corte_id = ? AND zona = ?",
                (template_id, corte_id, zona)).fetchone()
            if corte is None or ja:
                continue
            conexao.execute(
                "INSERT INTO template_midias (template_id, origem, corte_id, rotulo, zona) "
                "VALUES (?, 'corte', ?, ?, ?)", (template_id, corte_id, corte["titulo"], zona))
            entrou += 1
    return entrou


def adicionar_arquivo(template_id: int, arquivo_relativo: str, rotulo: str, origem: str = "upload",
                      zona: int = 1) -> int:
    with closing(banco.conectar()) as conexao, conexao:
        return conexao.execute(
            "INSERT INTO template_midias (template_id, origem, arquivo, rotulo, zona) VALUES (?, ?, ?, ?, ?)",
            (template_id, origem, arquivo_relativo, rotulo, zona)).lastrowid


def atualizar_midia(midia_id: int, **campos) -> None:
    desconhecidos = set(campos) - CAMPOS_MIDIA
    if desconhecidos:
        raise KeyError(f"Campos nao permitidos: {sorted(desconhecidos)}")
    if not campos:
        return
    if "ajuste" in campos and campos["ajuste"] not in AJUSTES:
        raise ValueError("Ajuste invalido.")
    if "zoom" in campos:
        campos["zoom"] = min(max(float(campos["zoom"]), 1.0), 4.0)
    for chave in ("pos_x", "pos_y"):
        if chave in campos:
            campos[chave] = min(max(float(campos[chave]), 0.0), 100.0)
    if "selecionada" in campos:
        campos["selecionada"] = 1 if campos["selecionada"] else 0
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute(
            f"UPDATE template_midias SET {', '.join(f'{k} = ?' for k in campos)} WHERE id = ?",
            (*campos.values(), midia_id))


def excluir_midia(midia_id: int) -> None:
    midia = ler_midia(midia_id)
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute("DELETE FROM template_midias WHERE id = ?", (midia_id,))
    if midia and midia["origem"] in ("upload", "perfil") and midia["arquivo"]:
        (config.PASTA_DADOS / midia["arquivo"]).unlink(missing_ok=True)


# ---------- frases ----------

def listar_frases(template_id: int) -> list[dict]:
    with closing(banco.conectar()) as conexao:
        return [dict(l) for l in conexao.execute(
            "SELECT * FROM template_frases WHERE template_id = ? ORDER BY id", (template_id,))]


def ler_frase(frase_id: int) -> dict | None:
    with closing(banco.conectar()) as conexao:
        return _dict(conexao.execute("SELECT * FROM template_frases WHERE id = ?", (frase_id,)).fetchone())


def adicionar_frases(template_id: int, textos: list[str], origem: str = "manual") -> int:
    """Grava as frases novas (ignora vazias e repetidas). Devolve quantas entraram."""
    entrou = 0
    with closing(banco.conectar()) as conexao, conexao:
        existentes = {l["texto"].strip().lower() for l in conexao.execute(
            "SELECT texto FROM template_frases WHERE template_id = ?", (template_id,))}
        for texto in textos:
            texto = " ".join(str(texto).split())
            if not texto or texto.lower() in existentes:
                continue
            conexao.execute("INSERT INTO template_frases (template_id, texto, origem) VALUES (?, ?, ?)",
                            (template_id, texto, origem))
            existentes.add(texto.lower())
            entrou += 1
    return entrou


def atualizar_frase(frase_id: int, *, texto: str | None = None, selecionada: bool | None = None) -> None:
    with closing(banco.conectar()) as conexao, conexao:
        if texto is not None and texto.strip():
            conexao.execute("UPDATE template_frases SET texto = ? WHERE id = ?", (" ".join(texto.split()), frase_id))
        if selecionada is not None:
            conexao.execute("UPDATE template_frases SET selecionada = ? WHERE id = ?",
                            (1 if selecionada else 0, frase_id))


def excluir_frase(frase_id: int) -> None:
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute("DELETE FROM template_frases WHERE id = ?", (frase_id,))


# ---------- videos gerados ----------

def combinacoes(template_id: int) -> tuple[list[dict], list[dict]]:
    """As midias (zona 1) e frases selecionadas: o cruzamento delas e o que sera gerado."""
    midias = [m for m in listar_midias(template_id) if m["selecionada"] and m["zona"] == 1]
    frases = [f for f in listar_frases(template_id) if f["selecionada"]]
    return midias, frases


def gerar_saidas(template_id: int) -> tuple[int, int]:
    """Cria as linhas de video a gerar. Devolve (novas, que ja existiam). Falhas voltam para a fila."""
    midias, frases = combinacoes(template_id)
    novas = ja_existiam = 0
    with closing(banco.conectar()) as conexao, conexao:
        for midia in midias:
            for frase in frases:
                existente = conexao.execute(
                    "SELECT id, estado FROM template_saidas WHERE template_id = ? AND midia_id = ? AND frase_id = ?",
                    (template_id, midia["id"], frase["id"])).fetchone()
                if existente is None:
                    conexao.execute(
                        "INSERT INTO template_saidas (template_id, midia_id, frase_id) VALUES (?, ?, ?)",
                        (template_id, midia["id"], frase["id"]))
                    novas += 1
                else:
                    ja_existiam += 1
                    if existente["estado"] == "falhou":
                        conexao.execute("UPDATE template_saidas SET estado = 'aguardando', erro = NULL WHERE id = ?",
                                        (existente["id"],))
    return novas, ja_existiam


def listar_saidas(template_id: int) -> list[dict]:
    with closing(banco.conectar()) as conexao:
        return [dict(l) for l in conexao.execute(
            "SELECT s.*, f.texto AS frase, m.rotulo AS midia FROM template_saidas s "
            "JOIN template_frases f ON f.id = s.frase_id JOIN template_midias m ON m.id = s.midia_id "
            "WHERE s.template_id = ? ORDER BY s.id", (template_id,))]


def ler_saida(saida_id: int) -> dict | None:
    with closing(banco.conectar()) as conexao:
        return _dict(conexao.execute("SELECT * FROM template_saidas WHERE id = ?", (saida_id,)).fetchone())


def proxima_saida(template_id: int) -> dict | None:
    with closing(banco.conectar()) as conexao:
        return _dict(conexao.execute(
            "SELECT * FROM template_saidas WHERE template_id = ? AND estado = 'aguardando' ORDER BY id LIMIT 1",
            (template_id,)).fetchone())


def atualizar_saida(saida_id: int, **campos) -> None:
    permitidos = {"estado", "arquivo", "erro"}
    if set(campos) - permitidos:
        raise KeyError("Campo nao permitido.")
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute(f"UPDATE template_saidas SET {', '.join(f'{k} = ?' for k in campos)} WHERE id = ?",
                        (*campos.values(), saida_id))


def contagem_saidas(template_id: int) -> dict:
    with closing(banco.conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT estado, COUNT(*) AS total FROM template_saidas WHERE template_id = ? GROUP BY estado",
            (template_id,)).fetchall()
    resultado = {"aguardando": 0, "renderizando": 0, "pronto": 0, "falhou": 0}
    resultado.update({l["estado"]: l["total"] for l in linhas})
    resultado["total"] = sum(resultado.values())
    return resultado


def reiniciar_renderizacoes_interrompidas() -> None:
    """Ao religar o painel, o que estava sendo renderizado volta para a espera."""
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute("UPDATE template_saidas SET estado = 'aguardando' WHERE estado = 'renderizando'")


# ---------- perfis de pagina salvos ----------

def listar_perfis(usuario_id: int) -> list[dict]:
    with closing(banco.conectar()) as conexao:
        return [dict(l) | {"dados": json.loads(l["dados"])} for l in conexao.execute(
            "SELECT * FROM perfis_pagina WHERE usuario_id = ? ORDER BY id DESC", (usuario_id,))]


def salvar_perfil(usuario_id: int, rotulo: str, dados: dict) -> int:
    with closing(banco.conectar()) as conexao, conexao:
        return conexao.execute(
            "INSERT INTO perfis_pagina (usuario_id, rotulo, dados) VALUES (?, ?, ?)",
            (usuario_id, rotulo.strip() or "Perfil", json.dumps(dados, ensure_ascii=False))).lastrowid


def excluir_perfil(perfil_id: int) -> None:
    with closing(banco.conectar()) as conexao, conexao:
        conexao.execute("DELETE FROM perfis_pagina WHERE id = ?", (perfil_id,))
