"""TikTok: login (Login Kit) e postagem direta pela Content Posting API (envio do arquivo em pedacos).

Regras oficiais (conferidas em 13/11/2026):
- Antes de postar, consultar o criador (creator_info) e usar uma privacidade que ele permite.
- O dono escolhe a privacidade (sem valor padrao) e liga ou nao comentarios, dueto e costura; e
  confirma o envio. Por isso o TikTok nunca e agendado pelo modo automatico.
- App sem auditoria: so publica como privado (SELF_ONLY), e a conta precisa ser privada.
- Token de acesso dura 2 horas; o de renovacao, 180 dias, e muda a cada renovacao (guardar o novo).
"""
import math
import os
import time
from pathlib import Path
from urllib.parse import urlencode

from app.postagem.redes import Credenciais, ErroPostagem, Resultado, TEMPO_LIMITE_ENVIO, chamar, json_ou_vazio

URL_LOGIN = "https://www.tiktok.com/v2/auth/authorize/"
URL_TOKEN = "https://open.tiktokapis.com/v2/oauth/token/"
URL_USUARIO = "https://open.tiktokapis.com/v2/user/info/"
URL_CRIADOR = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
URL_INICIAR = "https://open.tiktokapis.com/v2/post/publish/video/init/"
URL_SITUACAO = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
ESCOPOS = ["user.info.basic", "video.publish"]
MB = 1024 * 1024
PEDACO = 10 * MB              # entre 5 e 64 MB, como a documentacao exige
PRIVACIDADES = ("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY")
ESPERA_S = 600
_dormir = time.sleep

MENSAGENS = {
    "unaudited_client_can_only_post_to_private_accounts":
        "O app ainda não foi auditado pelo TikTok: só dá para postar em conta privada, como 'Somente eu'.",
    "privacy_level_option_mismatch": "Essa privacidade não está disponível para esta conta do TikTok.",
    "spam_risk_too_many_posts": "O TikTok limitou os posts desta conta por hoje. Tente amanhã.",
    "spam_risk_user_banned_from_posting": "O TikTok bloqueou esta conta de postar.",
    "reached_active_user_cap": "O app atingiu o limite de contas que podem postar hoje (app sem auditoria).",
    "access_token_invalid": "O acesso ao TikTok venceu. Conecte a conta de novo.",
    "scope_not_authorized": "A permissão de publicar não foi aceita. Conecte a conta de novo.",
}


def _app() -> tuple[str, str]:
    chave, segredo = os.getenv("TIKTOK_CLIENT_KEY"), os.getenv("TIKTOK_CLIENT_SECRET")
    if not (chave and segredo):
        raise ErroPostagem("Faltam TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET no arquivo .env.")
    return chave, segredo


def _erro(resposta, contexto: str) -> ErroPostagem:
    erro = json_ou_vazio(resposta).get("error", {}) or {}
    codigo = erro.get("code", "")
    mensagem = MENSAGENS.get(codigo) or f"O TikTok recusou ({contexto}): {erro.get('message') or codigo or resposta.status_code}"
    return ErroPostagem(mensagem, reconectar=codigo in ("access_token_invalid", "scope_not_authorized"),
                        temporario=codigo in ("rate_limit_exceeded", "spam_risk_too_many_posts"))


# ---------- login ----------

def endereco_de_login(retorno: str, estado: str) -> str:
    chave, _ = _app()
    return URL_LOGIN + "?" + urlencode({"client_key": chave, "scope": ",".join(ESCOPOS), "response_type": "code",
                                        "redirect_uri": retorno, "state": estado})


def _guardar_tokens(credenciais: Credenciais | None, dados: dict) -> dict:
    novos = {"access_token": dados["access_token"], "refresh_token": dados["refresh_token"],
             "open_id": dados.get("open_id"), "expira_em": time.time() + int(dados.get("expires_in", 7200)) - 120}
    if credenciais is not None:
        credenciais.atualizar(**novos)
    return novos


def concluir_login(codigo: str, retorno: str) -> list[dict]:
    chave, segredo = _app()
    resposta = chamar("POST", URL_TOKEN, rede="tiktok", data={
        "client_key": chave, "client_secret": segredo, "code": codigo, "grant_type": "authorization_code",
        "redirect_uri": retorno}, headers={"Content-Type": "application/x-www-form-urlencoded"})
    dados = json_ou_vazio(resposta)
    if resposta.status_code != 200 or "access_token" not in dados:
        raise ErroPostagem(f"O TikTok recusou o login: {dados.get('error_description') or dados.get('error') or resposta.status_code}.")
    tokens = _guardar_tokens(None, dados)
    usuario = json_ou_vazio(chamar("GET", URL_USUARIO, rede="tiktok", params={"fields": "open_id,display_name,avatar_url"},
                                   headers={"Authorization": f"Bearer {tokens['access_token']}"})).get("data", {}).get("user", {})
    return [{"rede": "tiktok", "id_externo": dados.get("open_id") or usuario.get("open_id"),
             "nome": usuario.get("display_name") or "Conta do TikTok", "foto": usuario.get("avatar_url"),
             "credenciais": tokens}]


def _token(credenciais: Credenciais) -> str:
    if time.time() < credenciais.get("expira_em", 0):
        return credenciais["access_token"]
    chave, segredo = _app()
    resposta = chamar("POST", URL_TOKEN, rede="tiktok", data={
        "client_key": chave, "client_secret": segredo, "grant_type": "refresh_token",
        "refresh_token": credenciais["refresh_token"]}, headers={"Content-Type": "application/x-www-form-urlencoded"})
    dados = json_ou_vazio(resposta)
    if resposta.status_code != 200 or "access_token" not in dados:
        raise ErroPostagem("O acesso ao TikTok venceu. Conecte a conta de novo.", reconectar=True)
    return _guardar_tokens(credenciais, dados)["access_token"]


# ---------- dados do criador (o painel mostra antes de postar) ----------

def info_do_criador(credenciais: Credenciais) -> dict:
    resposta = chamar("POST", URL_CRIADOR, rede="tiktok", json={}, headers={
        "Authorization": f"Bearer {_token(credenciais)}", "Content-Type": "application/json; charset=UTF-8"})
    dados = json_ou_vazio(resposta)
    if resposta.status_code != 200 or (dados.get("error") or {}).get("code", "ok") != "ok":
        raise _erro(resposta, "dados da conta")
    return dados.get("data", {})


def plano_de_pedacos(tamanho: int) -> tuple[int, int]:
    """(tamanho do pedaco, quantidade). Abaixo de 5 MB vai inteiro; o ultimo pedaco absorve o resto."""
    if tamanho < 5 * MB:
        return tamanho, 1
    return PEDACO, max(1, math.floor(tamanho / PEDACO))


# ---------- postagem ----------

def publicar(credenciais: Credenciais, arquivo: Path, titulo: str, legenda: str, opcoes: dict | None = None) -> Resultado:
    opcoes = opcoes or {}
    privacidade = opcoes.get("privacidade")
    if privacidade not in PRIVACIDADES:
        raise ErroPostagem("Escolha a privacidade do post no TikTok antes de publicar.")
    criador = info_do_criador(credenciais)
    if privacidade not in criador.get("privacy_level_options", []):
        raise ErroPostagem(MENSAGENS["privacy_level_option_mismatch"])
    token = _token(credenciais)
    tamanho = arquivo.stat().st_size
    pedaco, quantidade = plano_de_pedacos(tamanho)
    iniciar = chamar("POST", URL_INICIAR, rede="tiktok", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}, json={
        "post_info": {"title": legenda[:2200], "privacy_level": privacidade,
                      "disable_comment": not opcoes.get("comentarios", False) or bool(criador.get("comment_disabled")),
                      "disable_duet": not opcoes.get("dueto", False) or bool(criador.get("duet_disabled")),
                      "disable_stitch": not opcoes.get("costura", False) or bool(criador.get("stitch_disabled"))},
        "source_info": {"source": "FILE_UPLOAD", "video_size": tamanho, "chunk_size": pedaco,
                        "total_chunk_count": quantidade}})
    dados = json_ou_vazio(iniciar)
    if iniciar.status_code != 200 or (dados.get("error") or {}).get("code", "ok") != "ok":
        raise _erro(iniciar, "iniciar o post")
    publish_id, endereco = dados["data"]["publish_id"], dados["data"]["upload_url"]

    with arquivo.open("rb") as video:
        for numero in range(quantidade):
            inicio = numero * pedaco
            fim = tamanho - 1 if numero == quantidade - 1 else inicio + pedaco - 1
            video.seek(inicio)
            conteudo = video.read(fim - inicio + 1)
            resposta = chamar("PUT", endereco, rede="tiktok", data=conteudo, timeout=TEMPO_LIMITE_ENVIO, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(conteudo)),
                "Content-Range": f"bytes {inicio}-{fim}/{tamanho}"})
            if resposta.status_code not in (201, 206):
                raise ErroPostagem(f"O TikTok recusou um pedaço do vídeo (erro {resposta.status_code}).",
                                   temporario=resposta.status_code in (403, 416))

    limite = time.monotonic() + ESPERA_S
    while time.monotonic() < limite:
        situacao = chamar("POST", URL_SITUACAO, rede="tiktok", json={"publish_id": publish_id}, headers={
            "Authorization": f"Bearer {_token(credenciais)}", "Content-Type": "application/json; charset=UTF-8"})
        dados = json_ou_vazio(situacao).get("data", {})
        estado = dados.get("status")
        if estado == "PUBLISH_COMPLETE":
            ids = dados.get("publicaly_available_post_id") or []
            url = f"https://www.tiktok.com/video/{ids[0]}" if ids else None
            return Resultado(id_externo=str(ids[0]) if ids else publish_id, url=url,
                             observacao=None if ids else "Publicado. O link aparece depois da moderação do TikTok.")
        if estado == "FAILED":
            raise ErroPostagem(f"O TikTok não publicou: {dados.get('fail_reason', 'motivo não informado')}.",
                               temporario=dados.get("fail_reason") == "internal")
        _dormir(10)
    return Resultado(id_externo=publish_id, observacao="Enviado. O TikTok ainda está processando.")
