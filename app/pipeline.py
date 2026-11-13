"""Pipeline: a linha de montagem que transforma um link em cortes prontos.

    link -> download -> transcricao -> cerebro -> edicao -> cortes .mp4

Cada etapa grava o resultado no banco. Se algo falhar no meio, rodar de novo
com o mesmo link continua de onde parou, sem baixar, transcrever ou pagar a
IA duas vezes. Um video que ja ficou pronto nunca e reprocessado.

Rodar:
    python -m app.pipeline "https://www.youtube.com/watch?v=..."
"""
import sys
from pathlib import Path

from app import banco, config
from app.cerebro import escolher, traduzir
from app.contratos import CorteProposto, Transcricao, VideoBaixado
from app.download import baixar
from app.edicao import cortar
from app.transcricao import transcrever

log = config.criar_log("pipeline")


def processar_link(url: str, usuario_id: int = config.USUARIO_PADRAO) -> list[Path]:
    """Processa um video do comeco ao fim. Devolve os arquivos dos cortes gerados."""
    config.garantir_pastas()
    banco.criar_tabelas()

    try:
        plataforma, id_externo = baixar.identificar(url)
    except Exception as erro:
        log.error("Nao consegui reconhecer o link: %s", erro)
        return []

    registro = banco.buscar_video(usuario_id, plataforma, id_externo)
    if registro and registro["estado"] == "pronto":
        log.info("Este video ja foi processado antes. Nada a fazer.")
        return []
    video_id = registro["id"] if registro else banco.registrar_video(
        usuario_id, plataforma, id_externo, url)

    try:
        video = _etapa_download(video_id, url)
        transcricao = _etapa_transcricao(video_id, video)
        _etapa_cerebro(video_id, usuario_id, video, transcricao)
        arquivos = _etapa_edicao(video_id, usuario_id, video, transcricao)
    except Exception as erro:
        log.error("O video %d falhou: %s", video_id, erro)
        banco.atualizar_video(video_id, estado="falhou", erro=str(erro)[:500])
        return []

    banco.atualizar_video(video_id, estado="pronto", erro=None)
    log.info("Pronto: %d corte(s). Gasto com IA neste video: cerca de US$ %.4f.",
             len(arquivos), banco.custo_do_video(video_id))
    return arquivos


def _etapa_download(video_id: int, url: str) -> VideoBaixado:
    registro = banco.ler_video(video_id)
    if registro["caminho_arquivo"]:
        caminho = config.caminho_absoluto(registro["caminho_arquivo"])
        if caminho.exists():
            log.info("Download: video ja estava no disco.")
            return VideoBaixado(
                plataforma=registro["plataforma"], id_externo=registro["id_externo"],
                url=registro["url"], titulo=registro["titulo"] or "", canal=registro["canal"] or "",
                duracao_s=registro["duracao_s"] or 0.0, caminho=caminho,
            )
    log.info("Download: baixando o video...")
    video = baixar.baixar(url, config.PASTA_BRUTOS)
    banco.atualizar_video(
        video_id, titulo=video.titulo, canal=video.canal, duracao_s=video.duracao_s,
        caminho_arquivo=config.caminho_relativo(video.caminho), estado="baixado",
    )
    return video


def _etapa_transcricao(video_id: int, video: VideoBaixado) -> Transcricao:
    caminho = config.PASTA_TRANSCRICOES / f"{video_id}.json"
    if caminho.exists():
        log.info("Transcricao: ja existia, reaproveitando.")
        return Transcricao.carregar(caminho)
    log.info("Transcricao: ouvindo o video (pode demorar)...")
    transcricao = transcrever.transcrever(video.caminho)
    transcricao.salvar(caminho)
    banco.atualizar_video(
        video_id, idioma=transcricao.idioma,
        caminho_transcricao=config.caminho_relativo(caminho), estado="transcrito",
    )
    return transcricao


def _etapa_cerebro(video_id: int, usuario_id: int, video: VideoBaixado,
                   transcricao: Transcricao) -> None:
    if banco.ler_video(video_id)["estado"] == "analisado" or banco.cortes_do_video(video_id):
        log.info("Cerebro: os cortes ja tinham sido escolhidos.")
        return
    log.info("Cerebro: escolhendo os melhores momentos...")
    cortes = escolher.escolher_cortes(transcricao, video, usuario_id=usuario_id, video_id=video_id)
    for corte in cortes:
        banco.registrar_corte(usuario_id, video_id, corte)
    banco.atualizar_video(video_id, estado="analisado")


def _etapa_edicao(video_id: int, usuario_id: int, video: VideoBaixado,
                  transcricao: Transcricao) -> list[Path]:
    arquivos: list[Path] = []
    pendentes = [c for c in banco.cortes_do_video(video_id) if c["estado"] in ("proposto", "falhou")]
    for numero, linha in enumerate(pendentes, start=1):
        log.info("Edicao: montando corte %d de %d (%s)...", numero, len(pendentes), linha["titulo"])
        corte = CorteProposto(
            frase_inicio=linha["frase_inicio"], frase_fim=linha["frase_fim"],
            inicio=linha["inicio_s"], fim=linha["fim_s"], nota=linha["nota"],
            motivo=linha["motivo"], titulo=linha["titulo"], modo=linha["modo"],
        )
        destino = config.PASTA_CORTES / str(video_id) / f"corte_{linha['id']}.mp4"
        try:
            frases = transcricao.frases[corte.frase_inicio:corte.frase_fim + 1]
            if transcricao.idioma != "pt":
                frases = traduzir.traduzir_frases(
                    frases, transcricao.idioma, usuario_id=usuario_id, video_id=video_id)
            cortar.gerar_corte(video.caminho, corte, frases, destino)
        except Exception as erro:
            # Um corte com problema nao derruba os outros.
            log.error("Edicao: o corte %d falhou: %s", linha["id"], erro)
            banco.atualizar_corte(linha["id"], estado="falhou", erro=str(erro)[:500])
            continue
        banco.atualizar_corte(
            linha["id"], estado="renderizado", erro=None,
            caminho_arquivo=config.caminho_relativo(destino),
        )
        arquivos.append(destino)
    return arquivos


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Uso: python -m app.pipeline "link do video"')
        sys.exit(1)
    _arquivos = processar_link(sys.argv[1])
    print()
    if _arquivos:
        print("Cortes gerados:")
        for _arquivo in _arquivos:
            print("  ", _arquivo)
    else:
        print("Nenhum corte gerado. Veja as mensagens acima.")
