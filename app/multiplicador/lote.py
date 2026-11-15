"""Lote: gera, um por um, todos os videos pendentes de um template.

E o que a fila do painel chama quando o dono clica em "Gerar". Cada video e
independente: se um falhar, ele fica marcado e os outros seguem.
"""
from app import banco, config
from app.multiplicador import frases, renderizar, repositorio

log = config.criar_log("lote")


def processar_template(template_id: int, progresso=None) -> str:
    """Renderiza o que esta aguardando neste template. Devolve um resumo para a fila."""
    avisar = progresso or (lambda _texto: None)
    repositorio.reiniciar_renderizacoes_interrompidas()
    total = repositorio.contagem_saidas(template_id)["total"]
    while True:
        saida = repositorio.proxima_saida(template_id)
        if saida is None:
            break
        feitos = repositorio.contagem_saidas(template_id)
        avisar(f"Renderizando vídeo {feitos['pronto'] + feitos['falhou'] + 1} de {total}")
        try:
            renderizar.renderizar_saida(saida["id"])
        except Exception as erro:                      # um video com problema nao derruba o lote
            log.error("Video %d falhou: %s", saida["id"], erro)
    contagem = repositorio.contagem_saidas(template_id)
    prontos = contagem["pronto"]
    if contagem["falhou"]:
        return f"{prontos} prontos, {contagem['falhou']} com falha"
    return f"{prontos} vídeo pronto" if prontos == 1 else f"{prontos} vídeos prontos"


def preparar_corte(alvo: str, usuario_id: int, progresso=None) -> str:
    """Deixa um corte pronto para agendar: frase do gancho (a guardada ou uma nova) e o video no template.

    `alvo` e "corte_id:template_id" (item "preparar" da fila)."""
    avisar = progresso or (lambda _texto: None)
    corte_id, template_id = (int(x) for x in alvo.split(":"))
    corte, template = banco.ler_corte(corte_id), repositorio.ler_template(template_id)
    if corte is None or template is None:
        raise ValueError("O corte ou o template não existe mais.")
    if not corte["caminho_arquivo"]:
        raise ValueError("Este corte ainda não tem vídeo.")
    avisar("Escrevendo a frase do gancho")
    frase, _nova = frases.frase_do_corte(corte, usuario_id=usuario_id)
    saida, _ja = repositorio.criar_saida_avulsa(template_id, corte_id, frase)
    if saida["estado"] != "pronto":
        avisar("Gerando o vídeo no template")
        renderizar.renderizar_saida(saida["id"])
    return "Pronto para agendar"
