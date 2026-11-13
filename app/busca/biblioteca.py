"""Biblioteca: baixa videos escolhidos na tela Perfis para usar nos templates e no editor.

Os arquivos ficam em dados/biblioteca/ e sao registrados na tabela `biblioteca`.
Quem pede o download e a fila do painel (tipo "baixar").
"""
from app import config
from app.download import baixar
from app.multiplicador import repositorio

log = config.criar_log("biblioteca")


def baixar_para_biblioteca(url: str, usuario_id: int) -> str:
    """Baixa um video para a biblioteca. Devolve o texto de resultado para a fila."""
    plataforma, id_externo = baixar.identificar(url)
    existente = repositorio.buscar_na_biblioteca(usuario_id, plataforma, id_externo)
    if existente and config.caminho_absoluto(existente["arquivo"]).exists():
        return "Já estava na biblioteca"
    video = baixar.baixar(url, config.PASTA_BIBLIOTECA)
    repositorio.registrar_na_biblioteca(
        usuario_id, video.plataforma, video.id_externo, video.url, video.titulo, video.canal,
        video.duracao_s, config.caminho_relativo(video.caminho))
    log.info("Na biblioteca: %s", video.titulo)
    return f"Baixado: {video.titulo}"
