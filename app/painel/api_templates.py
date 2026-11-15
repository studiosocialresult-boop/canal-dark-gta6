"""Rotas do painel para Templates: paginas, assistente (dados, midias, frases, previa) e geracao."""
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app import banco, config, ia
from app.multiplicador import frases as modulo_frases
from app.multiplicador import modelos, renderizar, repositorio

USUARIO = config.USUARIO_PADRAO
EXTENSOES_VIDEO = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
EXTENSOES_IMAGEM = {".png", ".jpg", ".jpeg", ".webp"}
LIMITE_VIDEO = 2 * 1024 ** 3
LIMITE_IMAGEM = 8 * 1024 ** 2
FRASE_DE_EXEMPLO = "Sua frase aparece aqui"
PASSOS = ["Perfil", "Zonas", "Mídia", "Frases", "Estilo", "Variações", "Gerar"]


def _template_do_dono(template_id: int) -> dict:
    template = repositorio.ler_template(template_id)
    if template is None or template["usuario_id"] != USUARIO:
        raise HTTPException(404, "Template não encontrado.")
    return template


def _estado(t: dict, na_fila: bool) -> str:
    if na_fila or t.get("n_saidas") and t["n_prontas"] + t["n_falhas"] < t["n_saidas"]:
        return "gerando"
    if t["n_saidas"] and t["n_prontas"] == t["n_saidas"]:
        return "concluido"
    return "pronto" if t["n_midias"] and t["n_frases"] else "rascunho"


def _json_template(t: dict, na_fila: bool = False) -> dict:
    return {
        "id": t["id"], "nome": t["nome"], "layout": t["layout"], "layout_nome": modelos.LAYOUTS[t["layout"]]["nome"],
        "passo": t["passo"], "estado": _estado(t, na_fila), "atualizado_em": t["atualizado_em"],
        "n_midias": t["n_midias"], "n_frases": t["n_frases"], "n_saidas": t["n_saidas"],
        "n_prontas": t["n_prontas"], "n_falhas": t["n_falhas"],
        "capa": f"/api/templates/{t['id']}/previa.jpg?v={t['atualizado_em'].replace(' ', '')}-{t['n_midias']}-{t['n_frases']}",
    }


def _resumo(template_id: int) -> dict:
    midias, frases = repositorio.combinacoes(template_id)
    existentes = {(s["midia_id"], s["frase_id"]) for s in repositorio.listar_saidas(template_id)}
    cruzamento = [(m["id"], f["id"]) for m, f in repositorio.cruzamento(template_id)]
    return {"midias": len(midias), "frases": len(frases), "total": len(cruzamento),
            "novas": sum(1 for c in cruzamento if c not in existentes),
            "ja_existem": sum(1 for c in cruzamento if c in existentes)}


def _url_do_avatar(t: dict) -> str | None:
    """Endereco da foto do perfil (com a data do arquivo, para o navegador nao mostrar a antiga)."""
    caminho = t["config"].get("perfil", {}).get("avatar")
    if not caminho:
        return None
    arquivo = config.caminho_absoluto(caminho)
    return f"/api/templates/{t['id']}/avatar?v={arquivo.stat().st_mtime_ns}" if arquivo.exists() else None


def _ajuste_automatico(template: dict) -> None:
    """No Editor, um video horizontal comeca em "caber inteiro": preencher a tela vertical cortaria
    mais de dois tercos da imagem. O dono pode trocar depois (so vale para quem ainda nao mexeu)."""
    if template["layout"] != "cheio":
        return
    for midia in repositorio.listar_midias(template["id"]):
        if midia["ajuste"] != "preencher" or midia["zoom"] != 1 or midia["pos_x"] != 50 or midia["pos_y"] != 50:
            continue
        try:
            arquivo, _inicio, _dur = renderizar.resolver_midia(midia)
        except renderizar.ErroRender:
            continue
        largura, altura = renderizar.dimensoes(arquivo)
        if largura > altura > 0:
            repositorio.atualizar_midia(midia["id"], ajuste="caber")


def _midia_json(m: dict) -> dict:
    arquivo = None
    if m["origem"] == "corte" and m["corte_id"]:
        arquivo = f"/miniatura/{m['corte_id']}.jpg"
    return {**m, "miniatura": arquivo}


async def _gravar_corpo(request: Request, destino: Path, limite: int) -> int:
    """Grava o corpo da requisicao no disco, aos poucos, recusando o que passar do limite."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destino.open("wb") as arquivo:
        async for pedaco in request.stream():
            total += len(pedaco)
            if total > limite:
                arquivo.close()
                destino.unlink(missing_ok=True)
                raise HTTPException(413, "O arquivo é grande demais.")
            arquivo.write(pedaco)
    if total == 0:
        destino.unlink(missing_ok=True)
        raise HTTPException(400, "Nenhum arquivo foi enviado.")
    return total


def _nome_seguro(nome: str, padrao: str) -> str:
    nome = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(nome or padrao).name).strip("._") or padrao
    return nome[:80]


def registrar(app: FastAPI, paginas, contexto) -> None:
    """Liga as rotas de Templates no app. Precisa rodar antes da rota generica das telas futuras."""

    # ---------- paginas ----------

    @app.get("/templates")
    def pagina_lista(request: Request):
        return paginas.TemplateResponse(request, "templates.html", contexto(request, "templates"))

    @app.get("/templates/{template_id}")
    def pagina_assistente(request: Request, template_id: int):
        template = _template_do_dono(template_id)
        return paginas.TemplateResponse(request, "assistente.html", contexto(
            request, "templates", template_id=template["id"], passos=PASSOS))

    @app.get("/editor")
    def pagina_editor(request: Request):
        return paginas.TemplateResponse(request, "editor.html", contexto(request, "editor"))

    @app.get("/editor/{template_id}")
    def pagina_ajuste(request: Request, template_id: int):
        template = _template_do_dono(template_id)
        if template["layout"] != "cheio":
            raise HTTPException(404, "Esse ajuste não existe.")
        return paginas.TemplateResponse(request, "ajuste.html", contexto(request, "editor", template_id=template["id"]))

    @app.get("/api/editor")
    def api_editor():
        return {"ajustes": [_json_template(t) for t in repositorio.listar_templates(USUARIO, editor=True)]}

    # ---------- templates ----------

    @app.get("/api/templates")
    def api_lista():
        ativos = {i["alvo"] for i in banco.listar_fila(USUARIO, 100)
                  if i["tipo"] == "lote" and i["estado"] in ("aguardando", "processando")}
        return {"templates": [_json_template(t, str(t["id"]) in ativos) for t in repositorio.listar_templates(USUARIO)],
                "layouts": [{"id": k, **{c: v[c] for c in ("nome", "descricao")}} for k, v in modelos.layouts_visiveis().items()]}

    @app.post("/api/templates")
    def api_criar(dados: dict = Body(...)):
        layout = dados.get("layout")
        if layout not in modelos.LAYOUTS:
            raise HTTPException(400, "Escolha um dos 3 modelos de layout.")
        template_id = repositorio.criar_template(USUARIO, layout, str(dados.get("nome") or "Novo template"))
        # Um perfil salvo recente ja vem aplicado, para nao digitar tudo de novo.
        perfis = repositorio.listar_perfis(USUARIO)
        if perfis:
            repositorio.atualizar_template(template_id, config_nova={"perfil": perfis[0]["dados"]})
        return {"id": template_id}

    @app.get("/api/templates/{template_id}")
    def api_ler(template_id: int):
        t = _template_do_dono(template_id)
        return {
            "id": t["id"], "nome": t["nome"], "layout": t["layout"], "passo": t["passo"],
            "layouts": {k: v["nome"] for k, v in modelos.layouts_visiveis().items()},
            "config": modelos.config_completa(t["config"]),
            "avatar_url": _url_do_avatar(t),
            "padroes_do_layout": {"alinhamento": modelos.LAYOUTS[t["layout"]]["alinhamento_padrao"],
                                  "posicao": modelos.LAYOUTS[t["layout"]]["perfil_padrao"],
                                  "mostrar": modelos.LAYOUTS[t["layout"]]["mostra_perfil"]},
            "zonas_de_video": modelos.LAYOUTS[t["layout"]]["zonas_de_video"],
            "midias": [_midia_json(m) for m in repositorio.listar_midias(t["id"])],
            "frases": [f for f in repositorio.listar_frases(t["id"]) if f["origem"] != "avulsa"],
            "resumo": _resumo(t["id"]),
            "contagem": repositorio.contagem_saidas(t["id"]),
        }

    @app.put("/api/templates/{template_id}")
    def api_salvar(template_id: int, dados: dict = Body(...)):
        _template_do_dono(template_id)
        campos = {}
        if "nome" in dados:
            campos["nome"] = str(dados["nome"])[:80]
        if "layout" in dados:
            if dados["layout"] not in modelos.LAYOUTS:
                raise HTTPException(400, "Layout inválido.")
            campos["layout"] = dados["layout"]
        if "passo" in dados:
            campos["passo"] = max(1, min(int(dados["passo"]), len(PASSOS)))
        nova = dados.get("config")
        if nova is not None:
            _validar_config(nova)
        repositorio.atualizar_template(template_id, config_nova=nova, **campos)
        return {"ok": True, "resumo": _resumo(template_id)}

    @app.delete("/api/templates/{template_id}")
    def api_excluir(template_id: int):
        _template_do_dono(template_id)
        if banco.item_na_fila(USUARIO, "lote", str(template_id)):
            raise HTTPException(409, "Este template está gerando vídeos agora. Espere terminar.")
        repositorio.excluir_template(template_id)
        return {"ok": True}

    # ---------- previa ----------

    @app.get("/api/templates/{template_id}/previa.jpg")
    def api_previa(template_id: int, frase: str = "", midia: int | None = None):
        t = _template_do_dono(template_id)
        midias, frases = repositorio.combinacoes(t["id"])
        escolhida = repositorio.ler_midia(midia) if midia else (midias[0] if midias else None)
        if escolhida and escolhida["template_id"] != t["id"]:
            raise HTTPException(404)
        do_video = repositorio.frases_da_midia(frases, escolhida["id"] if escolhida else None)
        texto = " ".join(frase.split()) or (do_video[0]["texto"] if do_video else FRASE_DE_EXEMPLO)
        try:
            imagem = renderizar.previa(t, texto[:300], escolhida)
        except renderizar.ErroRender as erro:
            raise HTTPException(422, str(erro))
        return FileResponse(imagem, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

    # ---------- foto do perfil ----------

    @app.post("/api/templates/{template_id}/avatar")
    async def api_avatar(request: Request, template_id: int, nome: str = "foto.png"):
        _template_do_dono(template_id)
        extensao = Path(nome).suffix.lower()
        if extensao not in EXTENSOES_IMAGEM:
            raise HTTPException(400, "Use uma imagem PNG, JPG ou WEBP.")
        destino = repositorio.pasta_do_template(template_id) / f"avatar{extensao}"
        await _gravar_corpo(request, destino, LIMITE_IMAGEM)
        try:
            from PIL import Image
            with Image.open(destino) as imagem:
                imagem.verify()
        except Exception:
            destino.unlink(missing_ok=True)
            raise HTTPException(400, "Esse arquivo não parece ser uma imagem válida.")
        for outro in destino.parent.glob("avatar.*"):
            if outro != destino:
                outro.unlink(missing_ok=True)
        repositorio.atualizar_template(template_id, config_nova={"perfil": {"avatar": config.caminho_relativo(destino)}})
        return {"ok": True}

    @app.get("/api/templates/{template_id}/avatar")
    def api_ver_avatar(template_id: int):
        t = _template_do_dono(template_id)
        caminho = t["config"].get("perfil", {}).get("avatar")
        if not caminho or not config.caminho_absoluto(caminho).exists():
            raise HTTPException(404)
        return FileResponse(config.caminho_absoluto(caminho))

    @app.delete("/api/templates/{template_id}/avatar")
    def api_tirar_avatar(template_id: int):
        t = _template_do_dono(template_id)
        caminho = t["config"].get("perfil", {}).get("avatar")
        if caminho:
            config.caminho_absoluto(caminho).unlink(missing_ok=True)
        repositorio.atualizar_template(template_id, config_nova={"perfil": {"avatar": None}})
        return {"ok": True}

    # ---------- midias ----------

    @app.post("/api/templates/{template_id}/midias")
    def api_add_cortes(template_id: int, dados: dict = Body(...)):
        _template_do_dono(template_id)
        zona = 2 if dados.get("zona") == 2 else 1
        ids = [int(i) for i in dados.get("cortes", [])]
        biblioteca = [int(i) for i in dados.get("biblioteca", [])]
        for corte_id in ids:
            corte = banco.ler_corte(corte_id)
            if corte is None or corte["usuario_id"] != USUARIO:
                raise HTTPException(404, "Corte não encontrado.")
        for item_id in biblioteca:
            item = repositorio.ler_biblioteca(item_id)
            if item is None or item["usuario_id"] != USUARIO:
                raise HTTPException(404, "Vídeo não encontrado na biblioteca.")
        novos = repositorio.adicionar_cortes(template_id, ids, zona) if ids else 0
        novos += repositorio.adicionar_da_biblioteca(template_id, biblioteca, zona) if biblioteca else 0
        _ajuste_automatico(repositorio.ler_template(template_id))
        return {"ok": True, "novos": novos}

    @app.post("/api/templates/{template_id}/upload")
    async def api_upload(request: Request, template_id: int, nome: str = "video.mp4", zona: int = 1):
        _template_do_dono(template_id)
        extensao = Path(nome).suffix.lower()
        if extensao not in EXTENSOES_VIDEO:
            raise HTTPException(400, "Use um vídeo MP4, MOV, WEBM ou MKV.")
        seguro = _nome_seguro(nome, "video.mp4")
        destino = repositorio.pasta_do_template(template_id) / "midias" / f"{banco_agora()}_{seguro}"
        await _gravar_corpo(request, destino, LIMITE_VIDEO)
        try:
            renderizar.duracao_do_arquivo(destino)
        except renderizar.ErroRender:
            destino.unlink(missing_ok=True)
            raise HTTPException(400, "Esse arquivo não parece ser um vídeo válido.")
        midia_id = repositorio.adicionar_arquivo(
            template_id, config.caminho_relativo(destino), Path(seguro).stem, zona=2 if zona == 2 else 1)
        _ajuste_automatico(repositorio.ler_template(template_id))
        return {"ok": True, "id": midia_id}

    @app.put("/api/templates/{template_id}/midias/{midia_id}")
    def api_midia(template_id: int, midia_id: int, dados: dict = Body(...)):
        _template_do_dono(template_id)
        _midia_do_template(template_id, midia_id)
        try:
            repositorio.atualizar_midia(midia_id, **dados)
        except (KeyError, ValueError, TypeError) as erro:
            raise HTTPException(400, str(erro))
        return {"ok": True, "resumo": _resumo(template_id)}

    @app.put("/api/templates/{template_id}/midias")
    def api_midias_em_massa(template_id: int, dados: dict = Body(...)):
        _template_do_dono(template_id)
        zona = 2 if dados.get("zona") == 2 else 1
        for m in repositorio.listar_midias(template_id):
            if m["zona"] == zona:
                repositorio.atualizar_midia(m["id"], selecionada=bool(dados.get("selecionada")))
        return {"ok": True, "resumo": _resumo(template_id)}

    @app.delete("/api/templates/{template_id}/midias/{midia_id}")
    def api_tirar_midia(template_id: int, midia_id: int):
        _template_do_dono(template_id)
        _midia_do_template(template_id, midia_id)
        repositorio.excluir_midia(midia_id)
        return {"ok": True, "resumo": _resumo(template_id)}

    @app.get("/api/templates/{template_id}/midias/{midia_id}/arquivo")
    def api_arquivo_midia(template_id: int, midia_id: int):
        _template_do_dono(template_id)
        midia = _midia_do_template(template_id, midia_id)
        try:
            arquivo, _inicio, _dur = renderizar.resolver_midia(midia)
        except renderizar.ErroRender as erro:
            raise HTTPException(404, str(erro))
        return FileResponse(arquivo)

    @app.get("/api/templates/{template_id}/midias/{midia_id}/miniatura.jpg")
    def api_miniatura_midia(template_id: int, midia_id: int):
        _template_do_dono(template_id)
        midia = _midia_do_template(template_id, midia_id)
        pasta = repositorio.pasta_do_template(template_id) / "miniaturas"
        imagem = pasta / f"midia_{midia_id}.jpg"
        if not imagem.exists():
            try:
                arquivo, inicio, _dur = renderizar.resolver_midia(midia)
            except renderizar.ErroRender as erro:
                raise HTTPException(404, str(erro))
            pasta.mkdir(parents=True, exist_ok=True)
            resultado = subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{(inicio or 0) + 1.0:.2f}", "-i", str(arquivo),
                 "-frames:v", "1", "-vf", "scale=270:-2", "-q:v", "5", str(imagem)], capture_output=True)
            if resultado.returncode != 0 or not imagem.exists():
                raise HTTPException(404, "Não consegui gerar a miniatura.")
        return FileResponse(imagem, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    # ---------- frases ----------

    @app.post("/api/templates/{template_id}/frases")
    def api_add_frases(template_id: int, dados: dict = Body(...)):
        _template_do_dono(template_id)
        textos = [str(t) for t in dados.get("textos", [])][:200]
        if any(len(t) > 240 for t in textos):
            raise HTTPException(400, "Cada frase pode ter no máximo 240 caracteres.")
        midia_id = _midia_da_frase(template_id, dados.get("midia_id"))
        return {"ok": True, "novas": repositorio.adicionar_frases(template_id, textos, str(dados.get("origem", "manual")), midia_id),
                "resumo": _resumo(template_id)}

    @app.post("/api/templates/{template_id}/frases/gerar-por-video")
    def api_gerar_frases_por_video(template_id: int, dados: dict = Body(...)):
        """A IA le o titulo de cada video e escreve as frases dele. Um video com problema nao derruba os outros."""
        _template_do_dono(template_id)
        try:
            quantidade = int(dados.get("quantidade", 3))
        except (TypeError, ValueError):
            raise HTTPException(400, "Quantidade inválida.")
        alvo = _midia_da_frase(template_id, dados.get("midia_id"))
        midias = [m for m in repositorio.listar_midias(template_id) if m["selecionada"] and m["zona"] == 1]
        if alvo is not None:
            midias = [m for m in midias if m["id"] == alvo]
        if not midias:
            raise HTTPException(400, "Escolha os vídeos primeiro, no passo Mídia.")
        resultado, erros = [], []
        for m in midias:
            try:
                sugestoes = modulo_frases.gerar_para_video(
                    m["corte_titulo"] or m["rotulo"], m.get("corte_motivo"), quantidade, usuario_id=USUARIO)
            except (ValueError, ia.ErroIA) as erro:
                erros.append({"midia_id": m["id"], "rotulo": m["rotulo"], "erro": str(erro)})
                continue
            novas = repositorio.adicionar_frases(template_id, sugestoes, "ia", m["id"])
            resultado.append({"midia_id": m["id"], "novas": novas})
        if not resultado:
            raise HTTPException(502, erros[0]["erro"] if erros else "A IA não entregou frases.")
        return {"ok": True, "videos": resultado, "erros": erros, "resumo": _resumo(template_id)}

    @app.post("/api/templates/{template_id}/frases/gerar")
    def api_gerar_frases(template_id: int, dados: dict = Body(...)):
        _template_do_dono(template_id)
        try:
            sugestoes = modulo_frases.gerar_variacoes(
                str(dados.get("base", "")), int(dados.get("quantidade", 5)), usuario_id=USUARIO)
        except ValueError as erro:
            raise HTTPException(400, str(erro))
        except ia.ErroIA as erro:
            raise HTTPException(502, str(erro))
        return {"sugestoes": sugestoes}

    @app.put("/api/templates/{template_id}/frases/{frase_id}")
    def api_frase(template_id: int, frase_id: int, dados: dict = Body(...)):
        _template_do_dono(template_id)
        _frase_do_template(template_id, frase_id)
        repositorio.atualizar_frase(frase_id, texto=dados.get("texto"),
                                    selecionada=dados.get("selecionada"))
        return {"ok": True, "resumo": _resumo(template_id)}

    @app.put("/api/templates/{template_id}/frases")
    def api_frases_em_massa(template_id: int, dados: dict = Body(...)):
        _template_do_dono(template_id)
        for f in repositorio.listar_frases(template_id):
            repositorio.atualizar_frase(f["id"], selecionada=bool(dados.get("selecionada")))
        return {"ok": True, "resumo": _resumo(template_id)}

    @app.delete("/api/templates/{template_id}/frases/{frase_id}")
    def api_tirar_frase(template_id: int, frase_id: int):
        _template_do_dono(template_id)
        _frase_do_template(template_id, frase_id)
        repositorio.excluir_frase(frase_id)
        return {"ok": True, "resumo": _resumo(template_id)}

    # ---------- gerar ----------

    @app.post("/api/templates/{template_id}/gerar")
    def api_gerar(template_id: int):
        t = _template_do_dono(template_id)
        resumo = _resumo(template_id)
        if resumo["total"] == 0:
            raise HTTPException(400, "Escolha pelo menos um vídeo e uma frase.")
        if banco.item_na_fila(USUARIO, "lote", str(template_id)):
            raise HTTPException(409, "Este template já está na fila.")
        novas, _ja = repositorio.gerar_saidas(template_id)
        if novas == 0 and repositorio.contagem_saidas(template_id)["aguardando"] == 0:
            raise HTTPException(409, "Todos esses vídeos já foram gerados.")
        banco.enfileirar(USUARIO, "lote", str(template_id),
                         f"Editor: {t['nome']}" if t["layout"] == "cheio" else f"Template: {t['nome']}")
        return {"ok": True, "novas": novas}

    @app.get("/api/templates/{template_id}/saidas")
    def api_saidas(template_id: int):
        _template_do_dono(template_id)
        saidas = repositorio.listar_saidas(template_id)
        for s in saidas:
            s["url"] = f"/api/templates/{template_id}/saidas/{s['id']}.mp4" if s["estado"] == "pronto" else None
        return {"saidas": saidas, "contagem": repositorio.contagem_saidas(template_id)}

    @app.get("/api/templates/{template_id}/saidas/{saida_id}.mp4")
    def api_arquivo_saida(template_id: int, saida_id: int, baixar: int = 0):
        _template_do_dono(template_id)
        saida = repositorio.ler_saida(saida_id)
        if saida is None or saida["template_id"] != template_id or saida["estado"] != "pronto":
            raise HTTPException(404)
        arquivo = config.caminho_absoluto(saida["arquivo"])
        if not arquivo.exists():
            raise HTTPException(404)
        pasta = repositorio.pasta_do_template(template_id).resolve()
        if not arquivo.resolve().is_relative_to(pasta):
            raise HTTPException(404)
        nome = f"{_nome_seguro(repositorio.ler_template(template_id)['nome'], 'template')}_{saida_id}.mp4"
        return FileResponse(arquivo, media_type="video/mp4", filename=nome if baixar else None,
                            headers={"Cache-Control": "no-cache"})

    @app.get("/api/templates/{template_id}/saidas/{saida_id}/miniatura.jpg")
    def api_miniatura_saida(template_id: int, saida_id: int):
        """Um quadro do video pronto, para o cartao do corte (gerado uma vez e guardado)."""
        _template_do_dono(template_id)
        saida = repositorio.ler_saida(saida_id)
        if saida is None or saida["template_id"] != template_id or saida["estado"] != "pronto" or not saida["arquivo"]:
            raise HTTPException(404)
        arquivo = config.caminho_absoluto(saida["arquivo"])
        imagem = repositorio.pasta_do_template(template_id) / "miniaturas" / f"saida_{saida_id}.jpg"
        if not imagem.exists():
            if not arquivo.exists():
                raise HTTPException(404)
            imagem.parent.mkdir(parents=True, exist_ok=True)
            resultado = subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", "1.5", "-i", str(arquivo),
                 "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", str(imagem)], capture_output=True)
            if resultado.returncode != 0 or not imagem.exists():
                raise HTTPException(404, "Não consegui gerar a miniatura.")
        return FileResponse(imagem, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/templates/{template_id}/saidas.zip")
    def api_zip(template_id: int):
        template = _template_do_dono(template_id)
        prontas = [s for s in repositorio.listar_saidas(template_id) if s["estado"] == "pronto" and s["arquivo"]]
        pasta = repositorio.pasta_do_template(template_id).resolve()
        prontas = [s for s in prontas if (config.caminho_absoluto(s["arquivo"]).resolve().is_relative_to(pasta)
                                          and config.caminho_absoluto(s["arquivo"]).exists())]
        if not prontas:
            raise HTTPException(404, "Ainda não há vídeos prontos para baixar.")
        temporario = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        temporario.close()
        nome = _nome_seguro(template["nome"], "template")
        with zipfile.ZipFile(temporario.name, "w", zipfile.ZIP_STORED) as arquivo:     # mp4 ja e comprimido
            for numero, s in enumerate(prontas, start=1):
                arquivo.write(config.caminho_absoluto(s["arquivo"]), f"{nome}_{numero:02d}.mp4")
        return FileResponse(temporario.name, media_type="application/zip", filename=f"{nome}.zip",
                            background=BackgroundTask(lambda: Path(temporario.name).unlink(missing_ok=True)))

    @app.delete("/api/templates/{template_id}/saidas")
    def api_limpar_saidas(template_id: int):
        _template_do_dono(template_id)
        if banco.item_na_fila(USUARIO, "lote", str(template_id)):
            raise HTTPException(409, "Este template está gerando vídeos agora. Espere terminar.")
        return {"ok": True, "apagados": repositorio.apagar_saidas(template_id)}

    # ---------- janela do corte: "Postar com template" ----------

    def _corte_do_dono(corte_id: int):
        corte = banco.ler_corte(corte_id)
        if corte is None or corte["usuario_id"] != USUARIO:
            raise HTTPException(404, "Corte não encontrado.")
        return corte

    def _template_para_corte(template_id: int) -> dict:
        t = _template_do_dono(template_id)
        if t["layout"] == "cheio":
            raise HTTPException(404, "Template não encontrado.")
        return t

    @app.post("/api/cortes/{corte_id}/modelo/frases")
    def api_frases_do_corte(corte_id: int, dados: dict = Body(default={})):
        """A frase do gancho: a IA le o titulo do corte (e o motivo da escolha) e escreve as opcoes."""
        corte = _corte_do_dono(corte_id)
        try:
            quantidade = int(dados.get("quantidade", 3))
            frases = modulo_frases.gerar_para_video(corte["titulo"], corte["motivo"], quantidade, usuario_id=USUARIO)
        except (TypeError, ValueError) as erro:
            raise HTTPException(400, str(erro))
        except ia.ErroIA as erro:
            raise HTTPException(502, str(erro))
        if frases:
            banco.atualizar_corte(corte_id, frase_gancho=frases[0])
        return {"frases": frases}

    @app.post("/api/cortes/{corte_id}/modelo/frase-auto")
    def api_frase_auto(corte_id: int):
        """A frase do gancho ja pronta: devolve a guardada ou, na primeira vez, a IA escreve uma e guarda."""
        corte = _corte_do_dono(corte_id)
        try:
            frase, nova = modulo_frases.frase_do_corte(corte, usuario_id=USUARIO)
        except (TypeError, ValueError) as erro:
            raise HTTPException(400, str(erro))
        except ia.ErroIA as erro:
            raise HTTPException(502, str(erro))
        return {"frase": frase, "nova": nova}

    @app.post("/api/cortes/preparar")
    def api_preparar_cortes(dados: dict = Body(...)):
        """Varios cortes de uma vez: cada um ganha a frase do gancho e o video no template (pela fila)."""
        t = _template_para_corte(int(dados.get("template_id") or 0))
        ids = [int(i) for i in dados.get("cortes") or []]
        if not ids:
            raise HTTPException(400, "Escolha pelo menos um corte.")
        enfileirados = pulados = 0
        for corte_id in dict.fromkeys(ids):
            corte = _corte_do_dono(corte_id)
            alvo = f"{corte_id}:{t['id']}"
            if (not corte["caminho_arquivo"] or corte["estado"] in ("falhou", "descartado")
                    or banco.item_na_fila(USUARIO, "preparar", alvo)):
                pulados += 1
                continue
            banco.enfileirar(USUARIO, "preparar", alvo, f"Preparar ({t['nome']}): {corte['titulo'][:50]}")
            enfileirados += 1
        return {"ok": True, "enfileirados": enfileirados, "pulados": pulados}

    @app.get("/api/cortes/{corte_id}/modelo/previa.jpg")
    def api_previa_do_corte(corte_id: int, template_id: int, frase: str = ""):
        """Como o corte fica neste template, sem gravar nada."""
        corte = _corte_do_dono(corte_id)
        t = _template_para_corte(template_id)
        if not corte["caminho_arquivo"]:
            raise HTTPException(404, "Este corte ainda não tem vídeo.")
        provisoria = {"id": -corte_id, "template_id": t["id"], "origem": "corte", "corte_id": corte_id,
                      "arquivo": None, "rotulo": corte["titulo"], "zona": 1, "ajuste": "preencher", "zoom": 1.0,
                      "pos_x": 50.0, "pos_y": 50.0, "selecionada": 1, "com_legenda": 1, "avulsa": 1}
        texto = " ".join(frase.split())[:300] or FRASE_DE_EXEMPLO
        try:
            imagem = renderizar.previa(t, texto, provisoria)
        except renderizar.ErroRender as erro:
            raise HTTPException(422, str(erro))
        return FileResponse(imagem, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=60"})

    @app.post("/api/cortes/{corte_id}/modelo/gerar")
    def api_gerar_do_corte(corte_id: int, dados: dict = Body(...)):
        """Gera o video deste corte com a frase escolhida, no template escolhido (pela fila)."""
        corte = _corte_do_dono(corte_id)
        t = _template_para_corte(int(dados.get("template_id") or 0))
        texto = " ".join(str(dados.get("frase", "")).split())
        if not texto:
            raise HTTPException(400, "Escreva a frase do gancho.")
        if len(texto) > 240:
            raise HTTPException(400, "A frase pode ter no máximo 240 caracteres.")
        if not corte["caminho_arquivo"]:
            raise HTTPException(400, "Este corte ainda não tem vídeo.")
        saida, ja_existia = repositorio.criar_saida_avulsa(t["id"], corte_id, texto)
        if saida["estado"] == "pronto":
            return {"ok": True, "saida_id": saida["id"], "ja_existia": True}
        if not banco.item_na_fila(USUARIO, "lote", str(t["id"])):
            banco.enfileirar(USUARIO, "lote", str(t["id"]), f"Template {t['nome']}: {corte['titulo'][:40]}")
        return {"ok": True, "saida_id": saida["id"], "ja_existia": ja_existia}

    @app.get("/api/cortes/{corte_id}/modelo/saidas")
    def api_saidas_do_corte(corte_id: int):
        """Os videos ja feitos (ou sendo feitos) com este corte, em qualquer template."""
        _corte_do_dono(corte_id)
        saidas = repositorio.saidas_do_corte(corte_id, USUARIO)
        # Um video pode ter ficado esperando se a fila acabou de fechar o template: poe de novo na fila.
        for tid in {s["template_id"] for s in saidas if s["estado"] == "aguardando"}:
            if not banco.item_na_fila(USUARIO, "lote", str(tid)):
                nome = next(s["template"] for s in saidas if s["template_id"] == tid)
                banco.enfileirar(USUARIO, "lote", str(tid), f"Template {nome}")
        for s in saidas:
            s["url"] = f"/api/templates/{s['template_id']}/saidas/{s['id']}.mp4" if s["estado"] == "pronto" else None
        return {"saidas": [{k: s[k] for k in ("id", "template_id", "template", "frase", "estado", "erro", "url")}
                           for s in saidas]}

    # ---------- perfis de pagina salvos ----------

    @app.get("/api/perfis-pagina")
    def api_perfis():
        return {"perfis": repositorio.listar_perfis(USUARIO)}

    @app.post("/api/templates/{template_id}/perfil-salvo")
    def api_salvar_perfil(template_id: int, dados: dict = Body(...)):
        t = _template_do_dono(template_id)
        perfil = dict(modelos.config_completa(t["config"])["perfil"])
        perfil["avatar"] = None          # a foto pertence ao template; o perfil salvo guarda so texto e estilo
        rotulo = str(dados.get("rotulo") or perfil["nome"])[:60]
        return {"ok": True, "id": repositorio.salvar_perfil(USUARIO, rotulo, perfil)}

    @app.post("/api/templates/{template_id}/perfil-salvo/{perfil_id}")
    def api_aplicar_perfil(template_id: int, perfil_id: int):
        _template_do_dono(template_id)
        perfil = next((p for p in repositorio.listar_perfis(USUARIO) if p["id"] == perfil_id), None)
        if perfil is None:
            raise HTTPException(404, "Perfil não encontrado.")
        dados = {k: v for k, v in perfil["dados"].items() if k != "avatar"}
        repositorio.atualizar_template(template_id, config_nova={"perfil": dados})
        return {"ok": True}

    @app.delete("/api/perfis-pagina/{perfil_id}")
    def api_excluir_perfil(perfil_id: int):
        if not any(p["id"] == perfil_id for p in repositorio.listar_perfis(USUARIO)):
            raise HTTPException(404, "Perfil não encontrado.")
        repositorio.excluir_perfil(perfil_id)
        return {"ok": True}


def banco_agora() -> str:
    import time
    return time.strftime("%Y%m%d%H%M%S")


def _midia_do_template(template_id: int, midia_id: int) -> dict:
    midia = repositorio.ler_midia(midia_id)
    if midia is None or midia["template_id"] != template_id:
        raise HTTPException(404, "Vídeo não encontrado neste template.")
    return midia


def _midia_da_frase(template_id: int, valor) -> int | None:
    """Confere que o video informado e deste template. Sem valor: a frase vale para todos os videos."""
    if valor in (None, "", 0):
        return None
    try:
        midia = repositorio.ler_midia(int(valor))
    except (TypeError, ValueError):
        raise HTTPException(400, "Vídeo inválido.")
    if midia is None or midia["template_id"] != template_id:
        raise HTTPException(404, "Vídeo não encontrado neste template.")
    return midia["id"]


def _frase_do_template(template_id: int, frase_id: int) -> dict:
    frase = repositorio.ler_frase(frase_id)
    if frase is None or frase["template_id"] != template_id:
        raise HTTPException(404, "Frase não encontrada neste template.")
    return frase


LIMITES_CONFIG = {
    ("perfil", "tam_avatar"): (40, 260), ("perfil", "fonte_nome"): (20, 80), ("perfil", "fonte_handle"): (16, 70),
    ("texto", "tamanho"): (28, 120), ("texto", "espaco_lateral"): (16, 200), ("texto", "faixa_minima"): (0, 700),
}
VALORES_CONFIG = {
    ("perfil", "tema"): {"escuro", "claro"},
    ("perfil", "alinhamento"): {None, "esquerda", "centro", "direita"},
    ("perfil", "posicao"): {None, "topo", "base"},
    ("video", "fundo"): {"desfocado", "solido"},
}


def _validar_config(nova: dict) -> None:
    """Recusa valores fora do que o cartao sabe desenhar (a prévia e o vídeo final não quebram)."""
    if not isinstance(nova, dict):
        raise HTTPException(400, "Configuração inválida.")
    for secao, valores in nova.items():
        if secao not in modelos.CONFIG_PADRAO or not isinstance(valores, dict):
            raise HTTPException(400, f"Seção desconhecida: {secao}.")
        for chave, valor in valores.items():
            if chave not in modelos.CONFIG_PADRAO[secao]:
                raise HTTPException(400, f"Opção desconhecida: {secao}.{chave}.")
            if (secao, chave) in LIMITES_CONFIG:
                minimo, maximo = LIMITES_CONFIG[(secao, chave)]
                if not isinstance(valor, (int, float)) or isinstance(valor, bool) or not minimo <= valor <= maximo:
                    raise HTTPException(400, f"{chave} deve ficar entre {minimo} e {maximo}.")
            if (secao, chave) in VALORES_CONFIG and valor not in VALORES_CONFIG[(secao, chave)]:
                raise HTTPException(400, f"Valor inválido para {chave}.")
            if (secao, chave) == ("texto", "cor") and valor is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(valor)):
                raise HTTPException(400, "A cor precisa ser como #ff8800.")
            if (secao, chave) == ("perfil", "mostrar") and valor not in (None, True, False):
                raise HTTPException(400, "Valor inválido para mostrar.")
            if (secao, chave) in (("perfil", "nome"), ("perfil", "handle")) and (not isinstance(valor, str) or len(valor) > 60):
                raise HTTPException(400, f"{chave} deve ter até 60 caracteres.")
            if (secao, chave) == ("perfil", "avatar"):
                raise HTTPException(400, "A foto só pode ser trocada pelo envio de imagem.")
