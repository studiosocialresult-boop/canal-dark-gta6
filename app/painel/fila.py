"""Trabalhador da fila: processa, um por vez, o que foi pedido no painel.

Roda em uma thread dentro do proprio painel. Cada item da tabela `fila` e um
link para processar, um corte para narrar ou um lote de videos de um template. O que falha fica marcado como
"falhou" com a mensagem, sem derrubar o painel nem os itens seguintes.
"""
import threading
import time

from app import banco, config, pipeline
from app.download import baixar
from app.busca import biblioteca
from app.multiplicador import lote

log = config.criar_log("fila")

ESPERA_S = 1.5


def _agora() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def _resumo_do_link(item) -> str:
    """Texto final de um link processado: quantos cortes saíram, ou o que deu errado."""
    plataforma, id_externo = baixar.identificar(item["alvo"])
    video = banco.buscar_video(item["usuario_id"], plataforma, id_externo)
    if video is None:
        return "Não consegui processar este link."
    if video["estado"] == "falhou":
        raise RuntimeError(video["erro"] or "O processamento falhou.")
    total = len(banco.cortes_do_video(video["id"]))
    if total == 0:
        return "A IA não achou trechos bons neste vídeo."
    return f"{total} corte{'s' if total != 1 else ''} para revisar"


def executar(item) -> str:
    """Faz o trabalho de um item da fila e devolve o texto de resultado."""
    def avisar(texto: str) -> None:
        banco.atualizar_fila(item["id"], progresso=texto)

    if item["tipo"] == "link":
        pipeline.processar_link(item["alvo"], item["usuario_id"], progresso=avisar)
        return _resumo_do_link(item)
    if item["tipo"] == "narrar":
        pipeline.narrar_e_renderizar(int(item["alvo"]), progresso=avisar)
        return "Narração pronta"
    if item["tipo"] == "baixar":
        avisar("Baixando o vídeo")
        return biblioteca.baixar_para_biblioteca(item["alvo"], item["usuario_id"])
    if item["tipo"] == "lote":
        return lote.processar_template(int(item["alvo"]), progresso=avisar)
    raise ValueError(f"Tipo de item desconhecido: {item['tipo']}")


def processar_proximo() -> bool:
    """Processa o item mais antigo que esta aguardando. Devolve False se a fila estava vazia."""
    item = banco.proximo_da_fila()
    if item is None:
        return False
    log.info("Fila: comecando o item %d (%s).", item["id"], item["tipo"])
    banco.atualizar_fila(item["id"], estado="processando", iniciado_em=_agora(), progresso="Começando")
    try:
        resultado = executar(item)
    except Exception as erro:
        log.error("Fila: o item %d falhou: %s", item["id"], erro)
        banco.atualizar_fila(item["id"], estado="falhou", progresso=None,
                             resultado=str(erro)[:300], terminado_em=_agora())
    else:
        banco.atualizar_fila(item["id"], estado="pronto", progresso=None,
                             resultado=resultado, terminado_em=_agora())
    return True


class Trabalhador(threading.Thread):
    """Thread que fica olhando a fila e processando o que chegar."""

    def __init__(self):
        super().__init__(name="trabalhador-da-fila", daemon=True)
        self._parar = threading.Event()

    def run(self) -> None:
        banco.retomar_fila()
        while not self._parar.is_set():
            try:
                if not processar_proximo():
                    self._parar.wait(ESPERA_S)
            except Exception as erro:          # nunca deixa a thread morrer
                log.error("Fila: erro inesperado: %s", erro)
                self._parar.wait(ESPERA_S * 4)

    def parar(self) -> None:
        self._parar.set()
