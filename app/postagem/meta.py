"""Meta: login unico (Facebook Login) que conecta Paginas do Facebook e o Instagram ligado a elas.

Instagram Reels: "Instagram API com Facebook Login" (graph.facebook.com + rupload.facebook.com),
com o token da Pagina. Fluxo: cria o container (upload resumable), envia o arquivo, espera ficar
pronto e publica. Limite oficial: ate 100 posts por 24 h (a propria conta informa o limite real).

Facebook Reels: inicia o envio, manda o arquivo e finaliza como publicado. Limite: 30 por 24 h;
o video precisa ter de 3 a 90 segundos.

Tokens: o token de Pagina obtido de um token de usuario de longa duracao nao expira (pode ser
invalidado se a senha mudar ou o acesso for retirado). Conferido na documentacao em 13/11/2026.
"""
import os
import time
from pathlib import Path
from urllib.parse import urlencode

from app import config
from app.postagem.redes import Credenciais, ErroPostagem, Resultado, TEMPO_LIMITE_ENVIO, chamar, json_ou_vazio

GRAPH = f"https://graph.facebook.com/{config.VERSAO_META}"
RUPLOAD = "https://rupload.facebook.com"
ESCOPOS = ["pages_show_list", "pages_read_engagement", "pages_manage_posts",
           "instagram_basic", "instagram_content_publish", "business_management"]
ESPERA_PROCESSAMENTO_S = 600
INTERVALO_CONSULTA_S = 10
_dormir = time.sleep          # trocado nos testes


def _app() -> tuple[str, str]:
    app_id, segredo = os.getenv("META_APP_ID"), os.getenv("META_APP_SECRET")
    if not (app_id and segredo):
        raise ErroPostagem("Faltam META_APP_ID e META_APP_SECRET no arquivo .env.")
    return app_id, segredo


def _erro_da_meta(resposta, contexto: str) -> ErroPostagem:
    erro = json_ou_vazio(resposta).get("error", {}) or {}
    codigo = erro.get("code")
    mensagem = (erro.get("error_user_msg") or erro.get("message") or "").strip()
    if codigo == 190 or resposta.status_code == 401:
        return ErroPostagem(f"O acesso à Meta venceu ou foi retirado ({contexto}). Conecte a conta de novo.", reconectar=True)
    if codigo in (4, 17, 32, 341, 613) or erro.get("is_transient"):
        return ErroPostagem(f"A Meta pediu para esperar ({contexto}): limite de uso atingido. Tento de novo mais tarde.",
                            temporario=True)
    if codigo in (10, 200) or (isinstance(codigo, int) and 200 <= codigo < 300):
        return ErroPostagem(f"A Meta negou a permissão ({contexto}). Conecte de novo e aceite todas as permissões.",
                            reconectar=True)
    return ErroPostagem(f"A Meta recusou ({contexto}): {mensagem[:220] or resposta.status_code}")


# ---------- login ----------

def endereco_de_login(retorno: str, estado: str) -> str:
    app_id, _ = _app()
    return f"https://www.facebook.com/{config.VERSAO_META}/dialog/oauth?" + urlencode({
        "client_id": app_id, "redirect_uri": retorno, "state": estado, "response_type": "code",
        "scope": ",".join(ESCOPOS)})


def concluir_login(codigo: str, retorno: str) -> list[dict]:
    """Devolve as contas para guardar: cada Pagina (facebook) e o Instagram profissional ligado a ela."""
    app_id, segredo = _app()
    curto = chamar("GET", f"{GRAPH}/oauth/access_token", rede="facebook", params={
        "client_id": app_id, "redirect_uri": retorno, "client_secret": segredo, "code": codigo})
    if curto.status_code != 200 or "access_token" not in json_ou_vazio(curto):
        raise _erro_da_meta(curto, "login")
    longo = chamar("GET", f"{GRAPH}/oauth/access_token", rede="facebook", params={
        "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": segredo,
        "fb_exchange_token": json_ou_vazio(curto)["access_token"]})
    if longo.status_code != 200 or "access_token" not in json_ou_vazio(longo):
        raise _erro_da_meta(longo, "login")
    paginas = chamar("GET", f"{GRAPH}/me/accounts", rede="facebook", params={
        "access_token": json_ou_vazio(longo)["access_token"], "limit": 100,
        "fields": "id,name,access_token,picture{url},instagram_business_account{id,username,profile_picture_url}"})
    if paginas.status_code != 200:
        raise _erro_da_meta(paginas, "lista de Páginas")
    contas = []
    for pagina in json_ou_vazio(paginas).get("data", []):
        if not pagina.get("access_token"):
            continue
        contas.append({"rede": "facebook", "id_externo": pagina["id"], "nome": pagina.get("name", "Página"),
                       "foto": ((pagina.get("picture") or {}).get("data") or {}).get("url"),
                       "credenciais": {"page_id": pagina["id"], "page_token": pagina["access_token"]}})
        instagram = pagina.get("instagram_business_account")
        if instagram and instagram.get("id"):
            contas.append({"rede": "instagram", "id_externo": instagram["id"],
                           "nome": "@" + instagram.get("username", "instagram"), "foto": instagram.get("profile_picture_url"),
                           "credenciais": {"ig_id": instagram["id"], "page_id": pagina["id"],
                                           "page_token": pagina["access_token"]}})
    if not contas:
        raise ErroPostagem("Nenhuma Página do Facebook foi liberada no login. Conecte de novo e marque a sua Página.")
    return contas


# ---------- envio do arquivo (rupload, comum ao Instagram e ao Facebook) ----------

def _enviar_arquivo(url: str, token: str, arquivo: Path, rede: str) -> None:
    tamanho = arquivo.stat().st_size
    with arquivo.open("rb") as video:
        resposta = chamar("POST", url, rede=rede, data=video, timeout=TEMPO_LIMITE_ENVIO, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(tamanho)})
    if resposta.status_code != 200 or not json_ou_vazio(resposta).get("success", False):
        raise _erro_da_meta(resposta, "envio do vídeo")


# ---------- Instagram Reels ----------

def publicar_instagram(credenciais: Credenciais, arquivo: Path, titulo: str, legenda: str,
                       opcoes: dict | None = None) -> Resultado:
    token, ig_id = credenciais["page_token"], credenciais["ig_id"]
    criar = chamar("POST", f"{GRAPH}/{ig_id}/media", rede="instagram", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": legenda[:2200], "access_token": token})
    dados = json_ou_vazio(criar)
    if criar.status_code != 200 or "id" not in dados:
        raise _erro_da_meta(criar, "criar o Reel")
    container = dados["id"]
    _enviar_arquivo(dados.get("uri") or f"{RUPLOAD}/ig-api-upload/{config.VERSAO_META}/{container}", token, arquivo,
                    "instagram")

    limite = time.monotonic() + ESPERA_PROCESSAMENTO_S
    while True:
        estado = chamar("GET", f"{GRAPH}/{container}", rede="instagram",
                        params={"fields": "status_code,status", "access_token": token})
        codigo = json_ou_vazio(estado).get("status_code")
        if codigo == "FINISHED":
            break
        if codigo in ("ERROR", "EXPIRED"):
            raise ErroPostagem(f"O Instagram não aceitou o vídeo: {json_ou_vazio(estado).get('status') or codigo}.")
        if time.monotonic() > limite:
            raise ErroPostagem("O Instagram demorou demais para processar o vídeo. Tento de novo mais tarde.", temporario=True)
        _dormir(INTERVALO_CONSULTA_S)

    publicar = chamar("POST", f"{GRAPH}/{ig_id}/media_publish", rede="instagram",
                      data={"creation_id": container, "access_token": token})
    media_id = json_ou_vazio(publicar).get("id")
    if publicar.status_code != 200 or not media_id:
        raise _erro_da_meta(publicar, "publicar o Reel")
    link = json_ou_vazio(chamar("GET", f"{GRAPH}/{media_id}", rede="instagram",
                                params={"fields": "permalink", "access_token": token})).get("permalink")
    return Resultado(id_externo=media_id, url=link)


def limite_instagram(credenciais: Credenciais) -> tuple[int, int] | None:
    """(usados, total) nas ultimas 24 h, como a propria Meta informa. None se nao conseguir ler."""
    resposta = chamar("GET", f"{GRAPH}/{credenciais['ig_id']}/content_publishing_limit", rede="instagram",
                      params={"fields": "quota_usage,config", "access_token": credenciais["page_token"]})
    dados = (json_ou_vazio(resposta).get("data") or [{}])[0]
    if "quota_usage" not in dados:
        return None
    return dados["quota_usage"], (dados.get("config") or {}).get("quota_total", 50)


# ---------- Facebook Reels ----------

def publicar_facebook(credenciais: Credenciais, arquivo: Path, titulo: str, legenda: str,
                      opcoes: dict | None = None) -> Resultado:
    token, pagina = credenciais["page_token"], credenciais["page_id"]
    inicio = chamar("POST", f"{GRAPH}/{pagina}/video_reels", rede="facebook",
                    data={"upload_phase": "start", "access_token": token})
    dados = json_ou_vazio(inicio)
    if inicio.status_code != 200 or "video_id" not in dados:
        raise _erro_da_meta(inicio, "iniciar o Reel")
    video_id = dados["video_id"]
    _enviar_arquivo(dados.get("upload_url") or f"{RUPLOAD}/video-upload/{config.VERSAO_META}/{video_id}", token, arquivo,
                    "facebook")
    fim = chamar("POST", f"{GRAPH}/{pagina}/video_reels", rede="facebook", data={
        "video_id": video_id, "upload_phase": "finish", "video_state": "PUBLISHED",
        "description": legenda[:2200], "title": titulo[:100], "access_token": token})
    if fim.status_code != 200 or not json_ou_vazio(fim).get("success", False):
        raise _erro_da_meta(fim, "publicar o Reel")

    # A publicacao termina em segundo plano: confere se o processamento nao falhou.
    limite = time.monotonic() + ESPERA_PROCESSAMENTO_S
    while time.monotonic() < limite:
        estado = json_ou_vazio(chamar("GET", f"{GRAPH}/{video_id}", rede="facebook",
                                      params={"fields": "status", "access_token": token})).get("status", {})
        situacao = estado.get("video_status")
        if situacao in ("error", "upload_failed", "expired"):
            detalhe = ((estado.get("processing_phase") or {}).get("errors") or [{}])[0].get("message", situacao)
            raise ErroPostagem(f"O Facebook não aceitou o vídeo: {detalhe}.")
        if situacao == "ready" or (estado.get("publishing_phase") or {}).get("status") == "complete":
            break
        _dormir(INTERVALO_CONSULTA_S)
    return Resultado(id_externo=video_id, url=f"https://www.facebook.com/reel/{video_id}")
