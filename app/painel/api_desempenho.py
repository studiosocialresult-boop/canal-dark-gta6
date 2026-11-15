"""Rotas do painel para a Fase 8: a tela Desempenho (quanto cada post rendeu)."""
from fastapi import FastAPI, HTTPException, Request

from app import config
from app.desempenho import coletor, relatorio

USUARIO = config.USUARIO_PADRAO


def registrar(app: FastAPI, paginas, contexto) -> None:
    @app.get("/desempenho")
    def pagina_desempenho(request: Request):
        return paginas.TemplateResponse(request, "desempenho.html", contexto(request, "desempenho"))

    @app.get("/api/desempenho")
    def api_desempenho(dias: str = "7", medida: str = "visualizacoes", conta_id: str = ""):
        try:
            dias_n = int(dias)
        except ValueError:
            raise HTTPException(400, "Período inválido. Use 7, 30 ou 90 dias.")
        if dias_n not in relatorio.PERIODOS:
            raise HTTPException(400, "Período inválido. Use 7, 30 ou 90 dias.")
        if medida not in relatorio.MEDIDAS:
            raise HTTPException(400, "Medida inválida. Use visualizações, curtidas ou comentários.")
        try:
            conta = int(conta_id) if conta_id else None
        except ValueError:
            raise HTTPException(400, "Conta inválida.")
        return relatorio.montar(USUARIO, dias_n, medida, conta)

    @app.post("/api/desempenho/atualizar")
    def api_atualizar():
        return coletor.rodar()
