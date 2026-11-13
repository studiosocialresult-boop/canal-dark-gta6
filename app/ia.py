"""Ajudante unico para falar com a API da Anthropic.

Regra do projeto: a IA sempre devolve JSON validado. Se a resposta vier
errada, este modulo explica o problema para a IA e pede de novo. Depois de
algumas tentativas ele desiste com um ErroIA, que o pipeline trata sem quebrar.

Toda chamada e registrada na tabela uso_api, para medir o custo por corte.

Rodar sozinho faz um teste minimo de conexao (gasta uma fracao de centavo):
    python -m app.ia
"""
import json
import time

import anthropic

from app import banco, config

log = config.criar_log("ia")


class ErroIA(Exception):
    """A IA nao conseguiu entregar uma resposta valida."""


def carregar_prompt(nome: str, **variaveis) -> str:
    """Le um arquivo de prompts/ e troca cada {{nome}} pelo valor informado."""
    texto = (config.PASTA_PROMPTS / nome).read_text(encoding="utf-8")
    for chave, valor in variaveis.items():
        texto = texto.replace("{{" + chave + "}}", str(valor))
    if "{{" in texto:
        raise ValueError(f"O prompt {nome} ficou com variavel sem preencher.")
    return texto


def criar_cliente() -> anthropic.Anthropic:
    try:
        return anthropic.Anthropic()
    except anthropic.AnthropicError as erro:
        raise ErroIA(
            "Nao encontrei a chave da API da Anthropic. Confira o ANTHROPIC_API_KEY no arquivo .env."
        ) from erro


def pedir_json(*, modelo: str, esforco: str, sistema: str, mensagem: str, esquema: dict,
               etapa: str, usuario_id: int, video_id: int | None = None, validar=None,
               tentativas: int = 3, max_tokens: int = 16000, espera_s: float = 20.0,
               cliente=None) -> dict:
    """Envia um pedido a IA e devolve o JSON da resposta, ja conferido.

    esquema: formato obrigatorio da resposta (JSON Schema).
    validar: funcao opcional que recebe o JSON e devolve uma lista de problemas
             em texto. Lista vazia significa que a resposta esta boa.
    """
    cliente = cliente or criar_cliente()
    mensagens = [{"role": "user", "content": mensagem}]

    for tentativa in range(1, tentativas + 1):
        try:
            with cliente.messages.stream(
                model=modelo,
                max_tokens=max_tokens,
                system=sistema,
                messages=mensagens,
                output_config={
                    "effort": esforco,
                    "format": {"type": "json_schema", "schema": esquema},
                },
            ) as fluxo:
                resposta = fluxo.get_final_message()
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as erro:
            raise ErroIA("A chave da API da Anthropic foi recusada. Confira o arquivo .env.") from erro
        except anthropic.BadRequestError as erro:
            raise ErroIA(f"A API da Anthropic rejeitou o pedido ({etapa}): {erro.message}") from erro
        except (anthropic.RateLimitError, anthropic.InternalServerError,
                anthropic.APIConnectionError) as erro:
            log.warning("%s: falha temporaria na API (tentativa %d de %d): %s",
                        etapa, tentativa, tentativas, type(erro).__name__)
            if tentativa < tentativas:
                time.sleep(espera_s * tentativa)
            continue
        except anthropic.APIStatusError as erro:
            raise ErroIA(f"Erro da API da Anthropic ({etapa}): {erro.status_code}") from erro

        _registrar_uso(resposta, modelo, etapa, usuario_id, video_id)

        if resposta.stop_reason == "refusal":
            detalhes = getattr(resposta, "stop_details", None)
            categoria = getattr(detalhes, "category", None) or "sem categoria"
            raise ErroIA(f"A IA se recusou a analisar este conteudo ({etapa}; categoria: {categoria}).")

        if resposta.stop_reason == "max_tokens":
            log.warning("%s: resposta cortada por tamanho (tentativa %d de %d).",
                        etapa, tentativa, tentativas)
            continue

        texto = next((b.text for b in resposta.content if b.type == "text"), "")
        try:
            dados = json.loads(texto)
            problemas = validar(dados) if validar else []
        except json.JSONDecodeError:
            problemas = ["A resposta nao era um JSON valido."]

        if not problemas:
            return dados

        log.warning("%s: resposta invalida (tentativa %d de %d): %s",
                    etapa, tentativa, tentativas, " | ".join(problemas))
        # Devolve a resposta inteira para a IA (inclusive o raciocinio) e explica o que corrigir.
        mensagens.append({"role": "assistant", "content": resposta.content})
        mensagens.append({"role": "user", "content": (
            "Sua resposta tem estes problemas:\n- " + "\n- ".join(problemas) +
            "\n\nCorrija e devolva o JSON completo de novo."
        )})

    raise ErroIA(f"A IA nao entregou uma resposta valida em {tentativas} tentativas ({etapa}).")


def _registrar_uso(resposta, modelo: str, etapa: str, usuario_id: int, video_id: int | None) -> None:
    uso = resposta.usage
    entrada = (
        (getattr(uso, "input_tokens", 0) or 0)
        + (getattr(uso, "cache_read_input_tokens", 0) or 0)
        + (getattr(uso, "cache_creation_input_tokens", 0) or 0)
    )
    saida = getattr(uso, "output_tokens", 0) or 0
    preco_entrada, preco_saida = config.PRECOS_USD_POR_MILHAO.get(modelo, (0.0, 0.0))
    custo = (entrada * preco_entrada + saida * preco_saida) / 1_000_000
    banco.registrar_uso_api(
        usuario_id, "anthropic", etapa, video_id=video_id, modelo=modelo,
        tokens_entrada=entrada, tokens_saida=saida, custo_usd=custo,
    )
    log.info("%s: %d tokens de entrada, %d de saida (cerca de US$ %.4f).",
             etapa, entrada, saida, custo)


if __name__ == "__main__":
    banco.criar_tabelas()
    _resposta = pedir_json(
        modelo=config.MODELO_RAPIDO,
        esforco=config.ESFORCO_RAPIDO,
        sistema="Responda em portugues do Brasil.",
        mensagem="Diga 'conexao funcionando' no campo mensagem.",
        esquema={
            "type": "object",
            "properties": {"mensagem": {"type": "string"}},
            "required": ["mensagem"],
            "additionalProperties": False,
        },
        etapa="teste_conexao",
        usuario_id=config.USUARIO_PADRAO,
    )
    print("Resposta da IA:", _resposta["mensagem"])
