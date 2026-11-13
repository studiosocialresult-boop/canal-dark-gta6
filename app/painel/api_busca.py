"""Rotas do painel para a Fase 6: a tela Hoje (ranking da busca diaria) e os canais acompanhados."""
import threading
from datetime import datetime, timedelta

from fastapi import Body, FastAPI, HTTPException, Request

from app import banco, config
from app.busca import diaria, perfil

USUARIO = config.USUARIO_PADRAO
_trava = threading.Lock()
_rodando = {"ativo": False, "erro": None}


def _proxima_busca() -> str | None:
    """Quando a busca automatica roda a seguir (horario local), ou None se estiver desligada."""
    if not banco.ler_config(USUARIO, "busca_ativa"):
        return None
    agora = datetime.now(diaria._fuso())
    hora = banco.ler_config(USUARIO, "busca_hora")
    alvo = agora.replace(hour=hora, minute=0, second=0, microsecond=0)
    ultima = diaria.ultima_busca(USUARIO)
    ja_hoje = ultima is not None and ultima["dia"] == agora.strftime("%Y-%m-%d") and ultima["estado"] == "pronta"
    if ja_hoje or agora >= alvo:
        alvo = alvo + timedelta(days=1) if ja_hoje else agora
        if ja_hoje:
            alvo = alvo.replace(hour=hora, minute=0)
    return alvo.strftime("%Y-%m-%dT%H:%M")


def _linha_json(r: dict) -> dict:
    return {"posicao": r["posicao"], "id": r["id_externo"], "url": r["url"], "titulo": r["titulo"] or "(sem título)",
            "canal": r["canal"] or "", "views": r["views"], "horas": r["horas"], "velocidade": r["velocidade"],
            "aceleracao": r["aceleracao"], "origem": r["origem"], "destino": r["destino"], "motivo": r["motivo"],
            "duracao_s": r["duracao_s"], "miniatura": f"https://i.ytimg.com/vi/{r['id_externo']}/mqdefault.jpg"}


def _rodar_em_segundo_plano(enfileirar: bool) -> None:
    try:
        diaria.rodar(USUARIO, enfileirar=enfileirar)
        diaria.limpar_brutos(USUARIO)
        _rodando["erro"] = None
    except Exception as erro:
        _rodando["erro"] = str(erro)[:300]
    finally:
        _rodando["ativo"] = False


def registrar(app: FastAPI, paginas, contexto) -> None:
    @app.get("/hoje")
    def pagina_hoje(request: Request):
        return paginas.TemplateResponse(request, "hoje.html", contexto(request, "hoje"))

    @app.get("/api/hoje")
    def api_hoje():
        busca, ranking = diaria.ranking_atual(USUARIO)
        ultima = diaria.ultima_busca(USUARIO)
        enfileirados = sum(1 for r in ranking if r["destino"] == "enfileirado")
        return {
            "ativa": bool(banco.ler_config(USUARIO, "busca_ativa")),
            "hora": banco.ler_config(USUARIO, "busca_hora"),
            "janela_h": banco.ler_config(USUARIO, "busca_janela_h"),
            "meta_cortes": banco.ler_config(USUARIO, "meta_cortes_dia"),
            "rodando": _rodando["ativo"] or (ultima is not None and ultima["estado"] == "rodando"),
            "erro": _rodando["erro"] or (ultima["erro"] if ultima is not None and ultima["estado"] == "falhou" else None),
            "proxima": _proxima_busca(),
            "busca": ({"id": busca["id"], "dia": busca["dia"], "terminada_em": busca["terminada_em"], "resumo": busca["resumo"]}
                      if busca else None),
            "enfileirados": enfileirados,
            "ranking": [_linha_json(r) for r in ranking],
            "canais": [{"id": c["id"], "nome": c["nome"], "url": c["url"]} for c in diaria.listar_canais(USUARIO)],
            "historico": [{"id": b["id"], "dia": b["dia"], "estado": b["estado"], "resumo": b["resumo"], "erro": b["erro"]}
                          for b in diaria.historico(USUARIO)],
        }

    @app.post("/api/hoje/buscar")
    def api_buscar(dados: dict = Body(default={})):
        with _trava:
            if _rodando["ativo"]:
                raise HTTPException(409, "Já existe uma busca em andamento.")
            _rodando["ativo"] = True
        threading.Thread(target=_rodar_em_segundo_plano, args=(bool(dados.get("enfileirar", True)),),
                         name="busca-manual", daemon=True).start()
        return {"ok": True}

    @app.post("/api/hoje/processar")
    def api_processar(dados: dict = Body(...)):
        """Manda um video do ranking para a fila de cortes, mesmo fora da meta."""
        video_id = str(dados.get("id", ""))
        _, ranking = diaria.ranking_atual(USUARIO)
        linha = next((r for r in ranking if r["id_externo"] == video_id), None)
        if linha is None:
            raise HTTPException(404, "Esse vídeo não está no ranking de hoje.")
        if banco.buscar_video(USUARIO, "youtube", video_id) is not None:
            raise HTTPException(409, "Este vídeo já foi processado.")
        if banco.item_na_fila(USUARIO, "link", linha["url"]):
            raise HTTPException(409, "Este vídeo já está na fila.")
        banco.enfileirar(USUARIO, "link", linha["url"], linha["titulo"] or linha["url"])
        return {"ok": True}

    @app.post("/api/canais")
    def api_adicionar_canal(dados: dict = Body(...)):
        try:
            canal = diaria.adicionar_canal(USUARIO, str(dados.get("url", "")))
        except perfil.ErroPerfil as erro:
            raise HTTPException(400, str(erro))
        return {"ok": True, "canal": {"id": canal["id"], "nome": canal["nome"], "url": canal["url"]}}

    @app.delete("/api/canais/{canal_id}")
    def api_remover_canal(canal_id: int):
        if not diaria.remover_canal(USUARIO, canal_id):
            raise HTTPException(404, "Canal não encontrado.")
        return {"ok": True}
