"""Rotas do painel para a Fase 5: conectar contas (login das redes), agendar e a Agenda."""
import secrets
import subprocess
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from app import banco, config, ia
from app.postagem import agendador, contas, legenda, meta, tiktok, youtube
from app.postagem.cofre import ErroCofre
from app.postagem.redes import REDES, ErroPostagem, configurada

USUARIO = config.USUARIO_PADRAO
SERVICOS = {"youtube": (youtube, ["youtube"]), "meta": (meta, ["instagram", "facebook"]), "tiktok": (tiktok, ["tiktok"])}
VALIDADE_LOGIN_S = 900
_logins_pendentes: dict[str, tuple[str, float]] = {}     # estado -> (servico, quando): protege o retorno do login


def retorno(servico: str) -> str:
    """Endereco que deve ser cadastrado no app de cada rede como 'URL de redirecionamento'."""
    return f"{config.URL_PAINEL.rstrip('/')}/contas/retorno/{servico}"


def _local(texto_utc: str | None) -> str | None:
    if not texto_utc:
        return None
    return agendador.momento(texto_utc).astimezone(agendador._fuso()).strftime("%Y-%m-%dT%H:%M")


def _de_local(valor: str) -> datetime:
    try:
        horario = datetime.fromisoformat(valor)
    except (TypeError, ValueError):
        raise HTTPException(400, "Horário inválido.")
    if horario.tzinfo is None:
        horario = horario.replace(tzinfo=agendador._fuso())
    return horario.astimezone(timezone.utc)


def _conta_do_dono(conta_id: int) -> dict:
    conta = contas.ler_conta(conta_id)
    if conta is None or conta["usuario_id"] != USUARIO:
        raise HTTPException(404, "Conta não encontrada.")
    return conta


def _publicacao_do_dono(publicacao_id: int) -> dict:
    publicacao = contas.ler_publicacao(publicacao_id)
    if publicacao is None or publicacao["usuario_id"] != USUARIO:
        raise HTTPException(404, "Publicação não encontrada.")
    return publicacao


def _publicacao_json(p: dict) -> dict:
    return {
        "id": p["id"], "conta_id": p["conta_id"], "rede": p["rede"], "rede_nome": REDES[p["rede"]]["nome"],
        "conta": p["conta_nome"], "conta_foto": p["conta_foto"], "origem": p["origem"], "corte_id": p["corte_id"],
        "saida_id": p["saida_id"], "titulo": p["titulo"], "legenda": p["legenda"], "opcoes": p["opcoes"],
        "quando": _local(p["agendada_para"]), "estado": p["estado"], "tentativas": p["tentativas"],
        "proxima_tentativa": _local(p["proxima_tentativa"]), "url": p["url"], "erro": p["erro"],
        "publicado_em": _local(p["publicado_em"]), "miniatura": f"/api/publicacoes/{p['id']}/miniatura.jpg",
    }


def registrar(app: FastAPI, paginas, contexto) -> None:
    # ---------- paginas ----------

    @app.get("/contas")
    def pagina_contas(request: Request):
        return paginas.TemplateResponse(request, "contas.html", contexto(request, "contas"))

    @app.get("/agenda")
    def pagina_agenda(request: Request):
        return paginas.TemplateResponse(request, "agenda.html", contexto(request, "agenda"))

    # ---------- contas ----------

    @app.get("/api/contas")
    def api_contas():
        redes = {r: {"nome": d["nome"], "configurada": configurada(r), "automatico": d["automatico"],
                     "limite_diario": d["limite_diario"], "duracao_max_s": d["duracao_max_s"]} for r, d in REDES.items()}
        servicos = {s: {"configurado": all(configurada(r) for r in redes_do_servico), "redes": redes_do_servico,
                        "retorno": retorno(s)} for s, (_m, redes_do_servico) in SERVICOS.items()}
        lista = [{**c, **agendador.resumo_ritmo(c), "limite_seguro": agendador.limite_seguro(c)}
                 for c in contas.listar_contas(USUARIO)]
        return {"contas": lista, "redes": redes, "servicos": servicos}

    @app.get("/contas/conectar/{servico}")
    def conectar(servico: str):
        if servico not in SERVICOS:
            raise HTTPException(404)
        modulo, _redes = SERVICOS[servico]
        try:
            estado = secrets.token_urlsafe(24)
            endereco = modulo.endereco_de_login(retorno(servico), estado)
        except ErroPostagem as erro:
            return RedirectResponse(f"/contas?erro={quote(str(erro))}")
        agora = time.time()
        for chave, (_s, criado) in list(_logins_pendentes.items()):      # limpa logins abandonados
            if agora - criado > VALIDADE_LOGIN_S:
                _logins_pendentes.pop(chave, None)
        _logins_pendentes[estado] = (servico, agora)
        return RedirectResponse(endereco)

    @app.get("/contas/retorno/{servico}")
    def retorno_do_login(servico: str, code: str = "", state: str = "", error: str = "", error_description: str = ""):
        pendente = _logins_pendentes.pop(state, None)
        if pendente is None or pendente[0] != servico or time.time() - pendente[1] > VALIDADE_LOGIN_S:
            return RedirectResponse(f"/contas?erro={quote('O login expirou ou não foi iniciado aqui. Tente conectar de novo.')}")
        if error or not code:
            motivo = error_description or error or "o login foi cancelado"
            return RedirectResponse(f"/contas?erro={quote('Login não concluído: ' + motivo)}")
        modulo, _redes = SERVICOS[servico]
        try:
            novas = modulo.concluir_login(code, retorno(servico))
        except ErroPostagem as erro:
            return RedirectResponse(f"/contas?erro={quote(str(erro))}")
        for c in novas:
            ritmo = banco.ler_config(USUARIO, f"posts_dia_{c['rede']}")
            contas.salvar_conta(USUARIO, c["rede"], c["id_externo"], c["nome"], c.get("foto"), c["credenciais"], ritmo)
        return RedirectResponse(f"/contas?conectadas={len(novas)}")

    @app.put("/api/contas/{conta_id}")
    def api_conta(conta_id: int, dados: dict = Body(...)):
        _conta_do_dono(conta_id)
        campos = {}
        if "ativa" in dados:
            campos["ativa"] = 1 if dados["ativa"] else 0
        if "posts_por_dia" in dados:
            try:
                ritmo = int(dados["posts_por_dia"])
            except (TypeError, ValueError):
                raise HTTPException(400, "Use um número de posts por dia.")
            if not 1 <= ritmo <= 24:
                raise HTTPException(400, "O ritmo deve ficar entre 1 e 24 posts por dia.")
            campos["posts_por_dia"] = ritmo
        if "rampa" in dados:
            campos["rampa"] = 1 if dados["rampa"] else 0
        contas.atualizar_conta(conta_id, **campos)
        return {"ok": True}

    @app.delete("/api/contas/{conta_id}")
    def api_remover_conta(conta_id: int):
        _conta_do_dono(conta_id)
        contas.remover_conta(conta_id)
        return {"ok": True}

    @app.get("/api/contas/{conta_id}/tiktok")
    def api_tiktok(conta_id: int):
        """Dados do criador, consultados na hora (as regras do TikTok exigem mostrar antes de postar)."""
        conta = _conta_do_dono(conta_id)
        if conta["rede"] != "tiktok":
            raise HTTPException(400, "Esta conta não é do TikTok.")
        try:
            credenciais = contas.credenciais_da_conta(conta_id)
            info = tiktok.info_do_criador(credenciais)
            if credenciais.mudou:
                contas.regravar_credenciais(conta_id, credenciais)
        except (ErroPostagem, ErroCofre) as erro:
            raise HTTPException(400, str(erro))
        return {"apelido": info.get("creator_nickname") or conta["nome"], "privacidades": info.get("privacy_level_options", []),
                "comentario_desligado": bool(info.get("comment_disabled")), "dueto_desligado": bool(info.get("duet_disabled")),
                "costura_desligada": bool(info.get("stitch_disabled")), "duracao_max_s": info.get("max_video_post_duration_sec")}

    # ---------- agendar ----------

    def _itens(dados: dict) -> list[dict]:
        itens = []
        try:
            itens += [agendador.item_de_corte(int(i), USUARIO) for i in dados.get("cortes", [])]
            itens += [agendador.item_de_saida(int(i), USUARIO) for i in dados.get("saidas", [])]
        except agendador.ErroAgenda as erro:
            raise HTTPException(400, str(erro))
        except (TypeError, ValueError):
            raise HTTPException(400, "Pedido inválido.")
        if not itens:
            raise HTTPException(400, "Escolha pelo menos um vídeo.")
        if len(itens) > 200:
            raise HTTPException(400, "Agende no máximo 200 vídeos de cada vez.")
        return itens

    @app.post("/api/agendar/legenda")
    def api_sugerir_legenda(dados: dict = Body(...)):
        """Sugestao de titulo, descricao e hashtags para o dono revisar antes de agendar."""
        item = _itens(dados)[0]
        try:
            textos = legenda.escrever(titulo=item["titulo"], motivo=item["motivo"], frase_na_tela=item["frase"],
                                      usuario_id=USUARIO, video_id=item.get("video_id"))
        except ia.ErroIA as erro:
            raise HTTPException(502, str(erro))
        return {"textos": textos, "credito": item["credito"]}

    @app.post("/api/agendar")
    def api_agendar(dados: dict = Body(...)):
        itens = _itens(dados)
        horario = _de_local(dados["horario"]) if dados.get("horario") else None
        textos = dados.get("textos")
        if textos is not None:
            problemas = legenda.validar(textos) if isinstance(textos, dict) else ["Textos inválidos."]
            if problemas:
                raise HTTPException(400, " ".join(problemas))
        opcoes = {}
        if isinstance(dados.get("tiktok"), dict):
            t = dados["tiktok"]
            opcoes["tiktok"] = {"privacidade": t.get("privacidade"), "comentarios": bool(t.get("comentarios")),
                                "dueto": bool(t.get("dueto")), "costura": bool(t.get("costura")),
                                "confirmado": bool(t.get("confirmado"))}
        try:
            resultado = agendador.agendar(USUARIO, itens, [int(c) for c in dados.get("contas", [])], horario=horario,
                                          distribuir=bool(dados.get("distribuir")), opcoes_por_rede=opcoes,
                                          textos_prontos=textos)
        except agendador.ErroAgenda as erro:
            raise HTTPException(400, str(erro))
        for c in resultado["criadas"]:
            c["quando"] = _local(c["quando"])
        return resultado

    # ---------- agenda ----------

    @app.get("/api/agenda")
    def api_agenda(dias: int = 14, passados: int = 3):
        agora = agendador.agora()
        desde = agendador.texto(agora - timedelta(days=max(0, min(passados, 60))))
        ate = agendador.texto(agora + timedelta(days=max(1, min(dias, 120))))
        lista = [_publicacao_json(p) for p in contas.listar_publicacoes(USUARIO, desde, ate)]
        return {"publicacoes": lista, "agora": _local(agendador.texto(agora)), "fuso": config.FUSO,
                "tem_contas": bool(contas.listar_contas(USUARIO))}

    @app.put("/api/publicacoes/{publicacao_id}")
    def api_editar(publicacao_id: int, dados: dict = Body(...)):
        p = _publicacao_do_dono(publicacao_id)
        if p["estado"] not in ("agendada", "falhou"):
            raise HTTPException(409, "Só dá para editar o que ainda não foi publicado.")
        campos = {}
        if "titulo" in dados:
            titulo = str(dados["titulo"]).strip()
            if not titulo or len(titulo) > 100:
                raise HTTPException(400, "O título precisa ter de 1 a 100 caracteres.")
            campos["titulo"] = titulo
        if "legenda" in dados:
            texto = str(dados["legenda"])
            rede = contas.ler_conta(p["conta_id"])["rede"]
            if len(texto) > REDES[rede]["legenda_max"]:
                raise HTTPException(400, f"A legenda passa do limite de {REDES[rede]['legenda_max']} caracteres.")
            campos["legenda"] = texto
        if "horario" in dados:
            quando = _de_local(dados["horario"])
            if quando < agendador.agora() + timedelta(minutes=1):
                raise HTTPException(400, "Escolha um horário no futuro.")
            campos["agendada_para"] = agendador.texto(quando)
        contas.atualizar_publicacao(publicacao_id, **campos)
        return {"ok": True}

    @app.post("/api/publicacoes/{publicacao_id}/cancelar")
    def api_cancelar(publicacao_id: int):
        p = _publicacao_do_dono(publicacao_id)
        if p["estado"] not in ("agendada", "falhou"):
            raise HTTPException(409, "Esta publicação não pode mais ser cancelada.")
        contas.atualizar_publicacao(publicacao_id, estado="cancelada")
        return {"ok": True}

    @app.post("/api/publicacoes/{publicacao_id}/agora")
    def api_agora(publicacao_id: int):
        """Poe para publicar ja (o publicador pega em ate meio minuto). Serve tambem para tentar de novo."""
        p = _publicacao_do_dono(publicacao_id)
        if p["estado"] not in ("agendada", "falhou"):
            raise HTTPException(409, "Esta publicação já saiu ou está saindo.")
        conta = contas.ler_conta(p["conta_id"])
        if conta["estado"] != "conectada" or not conta["ativa"]:
            raise HTTPException(409, "A conta está pausada ou precisa ser conectada de novo.")
        contas.atualizar_publicacao(publicacao_id, estado="agendada", agendada_para=agendador.texto(agendador.agora()),
                                    proxima_tentativa=None, tentativas=0, erro=None)
        return {"ok": True}

    @app.get("/api/publicacoes/{publicacao_id}/miniatura.jpg")
    def api_miniatura(publicacao_id: int):
        p = _publicacao_do_dono(publicacao_id)
        video = config.caminho_absoluto(p["arquivo"])
        if not video.exists():
            raise HTTPException(404)
        imagem = config.PASTA_DADOS / "miniaturas_agenda" / f"{publicacao_id}.jpg"
        if not imagem.exists():
            imagem.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", "1.5", "-i", str(video), "-frames:v", "1",
                            "-vf", "scale=180:-2", "-q:v", "5", str(imagem)], capture_output=True)
            if not imagem.exists():
                raise HTTPException(404)
        return FileResponse(imagem, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})
