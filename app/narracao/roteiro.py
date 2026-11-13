"""Roteiro: escreve o texto que o narrador fala em um corte.

O texto segue o modo escolhido pelo cerebro:

- "narrado": narracao do comeco ao fim, dividida em blocos. Cada bloco e
  ancorado em uma frase do corte: a voz comeca quando aquela frase comeca no
  video. Assim a narracao acompanha a imagem.
- "original": no maximo um gancho curto, falado logo antes do corte.

As instrucoes da IA ficam em prompts/roteiro_narrado.md, roteiro_gancho.md e
roteiro_escrita.md (regras de escrita, usadas pelos dois).

Este modulo so escreve e guarda o texto. Gerar a voz e misturar no video e
trabalho de outro modulo.

Rodar sozinho, para um corte que ja esta no banco (gasta cerca de 1 centavo):
    python -m app.narracao.roteiro 3
"""
import re
import sys

from app import banco, config, ia
from app.cerebro.traduzir import NOMES_IDIOMA
from app.contratos import BlocoRoteiro, CorteProposto, Roteiro, Transcricao, VideoBaixado

log = config.criar_log("roteiro")

ESQUEMA = {
    "type": "object",
    "properties": {
        "blocos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frase_inicio": {"type": "integer"},
                    "texto": {"type": "string"},
                },
                "required": ["frase_inicio", "texto"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["blocos"],
    "additionalProperties": False,
}

# Sinais que a voz nao le ou le errado.
SINAIS_PROIBIDOS = re.compile(r"[\[\]\(\)\{\}#*…\"“”\n]|\.\.\.")
PESO_ALGARISMO = 5   # um algarismo e falado por extenso: conta como 5 caracteres
GANCHO_MAX_CARACTERES = int(config.GANCHO_MAX_S * config.NARRACAO_CPS_IDEAL)
# A IA recebe o tempo ja convertido em caracteres ("orcamento"), para so precisar somar.
FOLGA_PCT = int((config.NARRACAO_CPS_MAX / config.NARRACAO_CPS_IDEAL - 1) * 100)      # quanto pode passar
FALTA_MAX = int(config.NARRACAO_SILENCIO_MAX_S * config.NARRACAO_CPS_IDEAL)           # quanto pode faltar


def peso_fala(texto: str) -> int:
    """Tamanho do texto para a voz: caracteres com espacos; cada algarismo vale 5."""
    texto = texto.strip()
    return len(texto) + (PESO_ALGARISMO - 1) * sum(c.isdigit() for c in texto)


def estimar_duracao_s(texto: str) -> float:
    """Quanto tempo a voz leva para falar o texto, no ritmo confortavel."""
    return peso_fala(texto) / config.NARRACAO_CPS_IDEAL


def escrever_roteiro(corte: CorteProposto, transcricao: Transcricao, video: VideoBaixado, *,
                     usuario_id: int, video_id: int | None = None, cliente=None) -> Roteiro:
    """Pede o roteiro a IA e devolve ja conferido. Levanta ia.ErroIA se nao sair."""
    regras = ia.carregar_prompt("roteiro_escrita.md")
    if corte.modo == "narrado":
        sistema = ia.carregar_prompt(
            "roteiro_narrado.md",
            folga_pct=FOLGA_PCT,
            falta_max=FALTA_MAX,
            exemplo_max=125 + 125 * FOLGA_PCT // 100,
            exemplo_min=125 - FALTA_MAX,
            regras_de_escrita=regras,
        )
        validar = lambda d: validar_narrado(d, corte, transcricao)   # noqa: E731
        etapa = "roteiro_narrado"
    else:
        sistema = ia.carregar_prompt(
            "roteiro_gancho.md",
            gancho_max_caracteres=GANCHO_MAX_CARACTERES,
            gancho_alvo_caracteres=GANCHO_MAX_CARACTERES * 3 // 4,
            regras_de_escrita=regras,
        )
        validar = lambda d: validar_gancho(d, corte)                  # noqa: E731
        etapa = "roteiro_gancho"

    dados = ia.pedir_json(
        modelo=config.MODELO_CEREBRO,
        esforco=config.ESFORCO_CEREBRO,
        sistema=sistema,
        mensagem=montar_mensagem(corte, transcricao, video),
        esquema=ESQUEMA,
        validar=validar,
        etapa=etapa,
        usuario_id=usuario_id,
        video_id=video_id,
        cliente=cliente,
    )
    roteiro = Roteiro(
        modo=corte.modo,
        blocos=[BlocoRoteiro(b["frase_inicio"], b["texto"].strip()) for b in dados["blocos"]],
    )
    log.info("Roteiro (%s): %d bloco(s), %d caracteres, cerca de %.0f s de voz.",
             corte.modo, len(roteiro.blocos), len(roteiro.texto), estimar_duracao_s(roteiro.texto))
    return roteiro


def montar_mensagem(corte: CorteProposto, transcricao: Transcricao, video: VideoBaixado) -> str:
    """Monta o texto enviado a IA: dados do video, do corte, contexto e frases."""
    idioma = NOMES_IDIOMA.get(transcricao.idioma, transcricao.idioma)
    linhas = [
        f"Vídeo de origem: {video.titulo or '(sem título)'}",
        f"Canal de origem: {video.canal or '(desconhecido)'}",
        f"Idioma da fala: {idioma}",
        "",
        f"Título do corte: {corte.titulo}",
        f"Motivo da escolha: {corte.motivo}",
        f"Duração do corte: {corte.duracao_s:.1f} s",
    ]
    if corte.modo == "narrado":
        linhas.append(
            f"Narração inteira: perto de {int(corte.duracao_s * config.NARRACAO_CPS_IDEAL)} "
            f"caracteres somando todos os blocos."
        )

    primeira = max(corte.frase_inicio - config.CONTEXTO_ROTEIRO_FRASES, 0)
    contexto = transcricao.frases[primeira:corte.frase_inicio]
    linhas += ["", "Frases de contexto (ditas logo antes do corte; só para você entender o assunto):"]
    linhas += [f"- {f.texto}" for f in contexto] or ["- (o corte começa no início do vídeo)"]

    linhas += ["", "Frases do corte:"]
    frases = transcricao.frases[corte.frase_inicio:corte.frase_fim + 1]
    comecos = [max(f.inicio - corte.inicio, 0.0) for f in frases] + [corte.duracao_s]
    for posicao, frase in enumerate(frases):
        detalhe = f"começa em {comecos[posicao]:.1f} s"
        if corte.modo == "narrado":
            # Quanto texto de narracao cabe ate a frase seguinte comecar.
            orcamento = round((comecos[posicao + 1] - comecos[posicao]) * config.NARRACAO_CPS_IDEAL)
            detalhe += f", orçamento de {orcamento} caracteres"
        linhas.append(f"[{frase.id}] ({detalhe}) {frase.texto}")
    linhas.append(f"O corte termina em {corte.duracao_s:.1f} s.")
    return "\n".join(linhas)


def janelas(blocos: list[dict], corte: CorteProposto, transcricao: Transcricao) -> list[float]:
    """Tempo, em segundos, que cada bloco tem ate o proximo comecar (ou o corte acabar)."""
    comecos = [max(transcricao.frases[b["frase_inicio"]].inicio - corte.inicio, 0.0) for b in blocos]
    fins = comecos[1:] + [corte.duracao_s]
    return [fim - comeco for comeco, fim in zip(comecos, fins)]


def _problemas_de_texto(numero: int, texto: str) -> list[str]:
    if not texto.strip():
        return [f"O bloco {numero} está vazio."]
    if SINAIS_PROIBIDOS.search(texto):
        return [f"O bloco {numero} tem sinais que a voz não lê (colchetes, parênteses, aspas, "
                f"reticências, # ou *). Reescreva sem eles."]
    return []


def validar_narrado(dados: dict, corte: CorteProposto, transcricao: Transcricao) -> list[str]:
    """Confere as ancoras e se cada bloco cabe na janela dele. Devolve os problemas em texto."""
    blocos = dados.get("blocos", [])
    if not blocos:
        return ["A lista de blocos veio vazia. Este corte precisa de narração do começo ao fim."]

    problemas: list[str] = []
    ancoras = [b["frase_inicio"] for b in blocos]
    fora = [a for a in ancoras if not corte.frase_inicio <= a <= corte.frase_fim]
    if fora:
        return [f"Estas âncoras não são frases do corte: {fora}. "
                f"Use identificadores de {corte.frase_inicio} a {corte.frase_fim}."]
    if ancoras[0] != corte.frase_inicio:
        problemas.append(f"O primeiro bloco precisa ser ancorado na frase {corte.frase_inicio}, "
                         f"a primeira do corte.")
    if any(depois <= antes for antes, depois in zip(ancoras, ancoras[1:])):
        return problemas + ["As âncoras precisam estar em ordem crescente, uma frase diferente "
                            "para cada bloco."]

    for numero, (bloco, janela) in enumerate(zip(blocos, janelas(blocos, corte, transcricao)), start=1):
        erros_texto = _problemas_de_texto(numero, bloco["texto"])
        if erros_texto:
            problemas += erros_texto
            continue
        peso = peso_fala(bloco["texto"])
        maximo = int(janela * config.NARRACAO_CPS_MAX + 1e-6)
        sobra = janela - peso / config.NARRACAO_CPS_IDEAL
        orcamento = round(janela * config.NARRACAO_CPS_IDEAL)
        if peso > maximo:
            problemas.append(
                f"O bloco {numero} (frase {bloco['frase_inicio']}) tem {peso} caracteres, contando "
                f"cada algarismo como {PESO_ALGARISMO}. O orçamento das frases que ele cobre soma "
                f"{orcamento}, então cabem no máximo {maximo}. Encurte o texto ou ancore o bloco "
                f"seguinte mais tarde."
            )
        elif sobra > config.NARRACAO_SILENCIO_MAX_S:
            minimo = int((janela - config.NARRACAO_SILENCIO_MAX_S) * config.NARRACAO_CPS_IDEAL) + 1
            problemas.append(
                f"O bloco {numero} (frase {bloco['frase_inicio']}) tem {peso} caracteres para um "
                f"orçamento de {orcamento} e deixa cerca de {sobra:.0f} s sem voz. Ele precisa de "
                f"pelo menos {minimo} caracteres: aproveite mais detalhes do corte, sem inventar, "
                f"ou ancore o bloco seguinte mais cedo."
            )
    return problemas


def validar_gancho(dados: dict, corte: CorteProposto) -> list[str]:
    """Confere o gancho do modo "original": nenhum ou um bloco curto, na primeira frase."""
    blocos = dados.get("blocos", [])
    if not blocos:
        return []
    if len(blocos) > 1:
        return ["Neste corte só cabe um gancho: devolva um único bloco, ou a lista vazia."]
    bloco = blocos[0]
    problemas = _problemas_de_texto(1, bloco["texto"])
    if bloco["frase_inicio"] != corte.frase_inicio:
        problemas.append(f"O gancho precisa ser ancorado na frase {corte.frase_inicio}, "
                         f"a primeira do corte.")
    peso = peso_fala(bloco["texto"])
    if peso > GANCHO_MAX_CARACTERES:
        problemas.append(
            f"O gancho tem {peso} caracteres, contando cada algarismo como {PESO_ALGARISMO}, e o "
            f"máximo é {GANCHO_MAX_CARACTERES}. Encurte."
        )
    return problemas


def roteirizar_corte(corte_id: int, cliente=None) -> Roteiro:
    """Escreve e guarda no banco o roteiro de um corte que ja existe.

    E o ponto de entrada do pipeline e do botao "narrar" do painel.
    """
    linha = banco.ler_corte(corte_id)
    if linha is None:
        raise ValueError(f"O corte {corte_id} nao existe.")
    registro = banco.ler_video(linha["video_id"])
    caminho_transcricao = config.PASTA_TRANSCRICOES / f"{linha['video_id']}.json"
    if not caminho_transcricao.exists():
        raise ValueError(f"Nao achei a transcricao do video {linha['video_id']}.")
    transcricao = Transcricao.carregar(caminho_transcricao)

    corte = CorteProposto(
        frase_inicio=linha["frase_inicio"], frase_fim=linha["frase_fim"],
        inicio=linha["inicio_s"], fim=linha["fim_s"], nota=linha["nota"],
        motivo=linha["motivo"], titulo=linha["titulo"], modo=linha["modo"],
    )
    video = VideoBaixado(
        plataforma=registro["plataforma"], id_externo=registro["id_externo"], url=registro["url"],
        titulo=registro["titulo"] or "", canal=registro["canal"] or "",
        duracao_s=registro["duracao_s"] or 0.0,
        caminho=config.caminho_absoluto(registro["caminho_arquivo"] or ""),
    )
    roteiro = escrever_roteiro(corte, transcricao, video, usuario_id=linha["usuario_id"],
                               video_id=linha["video_id"], cliente=cliente)
    banco.salvar_roteiro(linha["usuario_id"], corte_id, roteiro)
    return roteiro


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("Uso: python -m app.narracao.roteiro <numero do corte>")
        sys.exit(1)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # o terminal do Windows nao mostra acentos sem isso
    banco.criar_tabelas()
    try:
        _roteiro = roteirizar_corte(int(sys.argv[1]))
    except (ia.ErroIA, ValueError) as _erro:
        print("Nao deu certo:", _erro)
        sys.exit(1)
    print()
    print(f"Roteiro do corte {sys.argv[1]} (modo {_roteiro.modo}):")
    if not _roteiro.blocos:
        print("  (sem gancho: a primeira fala do corte ja prende sozinha)")
    for _bloco in _roteiro.blocos:
        print(f"  [frase {_bloco.frase_inicio}] ~{estimar_duracao_s(_bloco.texto):.0f} s: {_bloco.texto}")
