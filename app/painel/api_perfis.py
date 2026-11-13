"""Rotas do painel para a tela Perfis (analisador de canais) e para a biblioteca de videos baixados."""
import subprocess

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from app import banco, config
from app.busca import perfil
from app.download import baixar
from app.multiplicador import repositorio

USUARIO = config.USUARIO_PADRAO
LIMITE_SELECAO = 60


def _urls_validas(urls) -> list[str]:
    if not isinstance(urls, list) or not urls:
        raise HTTPException(400, "Selecione pelo menos um vídeo.")
    if len(urls) > LIMITE_SELECAO:
        raise HTTPException(400, f"Selecione no máximo {LIMITE_SELECAO} vídeos de cada vez.")
    limpas = []
    for url in urls:
        try:
            baixar.identificar(str(url))
        except ValueError:
            raise HTTPException(400, "Um dos links não é de um vídeo do YouTube.")
        limpas.append(str(url))
    return limpas


def registrar(app: FastAPI, paginas, contexto) -> None:
    @app.get("/perfis")
    def pagina_perfis(request: Request):
        return paginas.TemplateResponse(request, "perfis.html", contexto(request, "perfis"))

    @app.post("/api/perfis/buscar")
    def api_buscar(dados: dict = Body(...)):
        try:
            return perfil.listar(str(dados.get("alvo", "")), str(dados.get("aba", "videos")))
        except perfil.ErroPerfil as erro:
            raise HTTPException(400, str(erro))

    @app.post("/api/perfis/enviar-cortes")
    def api_enviar_cortes(dados: dict = Body(...)):
        """Poe os videos escolhidos na fila de processamento (a mesma do "Novo corte")."""
        urls = _urls_validas(dados.get("urls"))
        na_fila = ja_processados = 0
        for url in urls:
            plataforma, id_externo = baixar.identificar(url)
            registro = banco.buscar_video(USUARIO, plataforma, id_externo)
            if (registro and registro["estado"] == "pronto") or banco.item_na_fila(USUARIO, "link", url):
                ja_processados += 1
                continue
            banco.enfileirar(USUARIO, "link", url, url)
            na_fila += 1
        return {"ok": True, "na_fila": na_fila, "ja_processados": ja_processados}

    @app.post("/api/perfis/baixar")
    def api_baixar(dados: dict = Body(...)):
        """Poe o download dos videos escolhidos na fila, para a biblioteca."""
        urls = _urls_validas(dados.get("urls"))
        titulos = dados.get("titulos") if isinstance(dados.get("titulos"), dict) else {}
        na_fila = ja_tem = 0
        for url in urls:
            plataforma, id_externo = baixar.identificar(url)
            existente = repositorio.buscar_na_biblioteca(USUARIO, plataforma, id_externo)
            if (existente and config.caminho_absoluto(existente["arquivo"]).exists()) or banco.item_na_fila(USUARIO, "baixar", url):
                ja_tem += 1
                continue
            banco.enfileirar(USUARIO, "baixar", url, str(titulos.get(url) or url)[:120])
            na_fila += 1
        return {"ok": True, "na_fila": na_fila, "ja_tem": ja_tem}

    # ---------- biblioteca ----------

    @app.get("/api/biblioteca")
    def api_biblioteca():
        itens = repositorio.listar_biblioteca(USUARIO)
        for i in itens:
            i["miniatura"] = f"/api/biblioteca/{i['id']}/miniatura.jpg"
        return {"itens": itens}

    @app.get("/api/biblioteca/{item_id}/miniatura.jpg")
    def api_biblioteca_miniatura(item_id: int):
        item = _item_do_dono(item_id)
        arquivo = config.caminho_absoluto(item["arquivo"])
        if not arquivo.exists():
            raise HTTPException(404)
        imagem = arquivo.with_suffix(".jpg")
        if not imagem.exists():
            resultado = subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", "1", "-i", str(arquivo), "-frames:v", "1",
                 "-vf", "scale=270:-2", "-q:v", "5", str(imagem)], capture_output=True)
            if resultado.returncode != 0 or not imagem.exists():
                raise HTTPException(404)
        return FileResponse(imagem, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    @app.delete("/api/biblioteca/{item_id}")
    def api_biblioteca_apagar(item_id: int):
        _item_do_dono(item_id)
        repositorio.excluir_da_biblioteca(item_id)
        return {"ok": True}


def _item_do_dono(item_id: int) -> dict:
    item = repositorio.ler_biblioteca(item_id)
    if item is None or item["usuario_id"] != USUARIO:
        raise HTTPException(404, "Vídeo não encontrado na biblioteca.")
    return item
