"""Rotas do painel para a area "Chaves e integracoes" (Configuracoes).

As chaves vao para o .env de onde o painel roda. A resposta nunca traz o valor de uma chave.
"""
from urllib.parse import urlparse

from fastapi import Body, FastAPI, HTTPException, Request

from app import avisos, chaves, config


def _mesma_origem(request: Request) -> None:
    """Recusa pedidos vindos de outro site aberto no mesmo navegador."""
    origem = request.headers.get("origin")
    if origem and urlparse(origem).netloc != request.headers.get("host"):
        raise HTTPException(403, "Pedido recusado.")


def registrar(app: FastAPI) -> None:
    @app.get("/api/chaves")
    def api_chaves():
        base = config.URL_PAINEL.rstrip("/")
        return {"chaves": chaves.estado(),
                "retornos": {r: f"{base}/contas/retorno/{r}" for r in ("youtube", "meta", "tiktok")}}

    @app.put("/api/chaves")
    def api_salvar_chave(request: Request, dados: dict = Body(...)):
        _mesma_origem(request)
        try:
            chaves.salvar(str(dados.get("nome", "")), str(dados.get("valor") or ""))
        except chaves.ErroChave as erro:
            raise HTTPException(400, str(erro))
        return {"ok": True}

    @app.post("/api/chaves/telegram/descobrir")
    def api_descobrir(request: Request):
        _mesma_origem(request)
        try:
            avisos.descobrir_chat()
        except chaves.ErroChave as erro:
            raise HTTPException(400, str(erro))
        return {"ok": True}

    @app.post("/api/chaves/telegram/testar")
    def api_testar(request: Request):
        _mesma_origem(request)
        if not avisos.testar():
            raise HTTPException(400, "Não consegui mandar. Confira o token e clique em “Descobrir conversa”.")
        return {"ok": True}
