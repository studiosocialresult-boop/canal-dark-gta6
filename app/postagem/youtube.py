"""YouTube Shorts: login (OAuth do Google) e envio do video pela YouTube Data API v3.

Envio pelo protocolo "resumable" oficial: abre uma sessao, manda o arquivo em
pedacos (multiplos de 256 KB) e, se a conexao cair, pergunta ao YouTube quanto
ja chegou e continua dali. Custa 1 unidade da cota "Video Uploads" (100 envios
por dia), conforme a documentacao em 13/11/2026.

Atencao (Google): com o app em "modo de teste", o acesso concedido expira em 7
dias. Para rodar sozinho na VPS, o app precisa ser publicado no Google Cloud.
"""
import os
from pathlib import Path
from urllib.parse import urlencode

from app.postagem.redes import Credenciais, ErroPostagem, Resultado, chamar, json_ou_vazio, TEMPO_LIMITE_ENVIO

URL_LOGIN = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_CANAIS = "https://www.googleapis.com/youtube/v3/channels"
URL_ENVIO = "https://www.googleapis.com/upload/youtube/v3/videos"
ESCOPOS = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
PEDACO = 8 * 1024 * 1024          # 8 MB: multiplo de 256 KB, como o protocolo exige
TENTATIVAS_DE_RETOMADA = 5


def _cliente() -> tuple[str, str]:
    cliente, segredo = os.getenv("YOUTUBE_CLIENT_ID"), os.getenv("YOUTUBE_CLIENT_SECRET")
    if not (cliente and segredo):
        raise ErroPostagem("Faltam YOUTUBE_CLIENT_ID e YOUTUBE_CLIENT_SECRET no arquivo .env.")
    return cliente, segredo


# ---------- login ----------

def endereco_de_login(retorno: str, estado: str) -> str:
    cliente, _ = _cliente()
    return URL_LOGIN + "?" + urlencode({
        "client_id": cliente, "redirect_uri": retorno, "response_type": "code", "scope": " ".join(ESCOPOS),
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": estado})


def concluir_login(codigo: str, retorno: str) -> list[dict]:
    """Troca o codigo do login por tokens e devolve a conta (canal) para guardar."""
    cliente, segredo = _cliente()
    resposta = chamar("POST", URL_TOKEN, rede="youtube", data={
        "code": codigo, "client_id": cliente, "client_secret": segredo, "redirect_uri": retorno,
        "grant_type": "authorization_code"})
    dados = json_ou_vazio(resposta)
    if resposta.status_code != 200 or "access_token" not in dados:
        raise ErroPostagem(f"O Google recusou o login: {dados.get('error_description') or dados.get('error') or resposta.status_code}.")
    if not dados.get("refresh_token"):
        raise ErroPostagem("O Google não devolveu o acesso permanente. Remova o acesso do app na sua conta Google e conecte de novo.")
    canal = chamar("GET", URL_CANAIS, rede="youtube", params={"part": "snippet", "mine": "true"},
                   headers={"Authorization": f"Bearer {dados['access_token']}"})
    itens = json_ou_vazio(canal).get("items", [])
    if canal.status_code != 200 or not itens:
        raise ErroPostagem("Esta conta Google não tem um canal do YouTube.")
    snippet = itens[0]["snippet"]
    return [{"rede": "youtube", "id_externo": itens[0]["id"], "nome": snippet.get("title", "Canal"),
             "foto": (snippet.get("thumbnails", {}).get("default") or {}).get("url"),
             "credenciais": {"access_token": dados["access_token"], "refresh_token": dados["refresh_token"]}}]


def _renovar(credenciais: Credenciais) -> str:
    cliente, segredo = _cliente()
    resposta = chamar("POST", URL_TOKEN, rede="youtube", data={
        "client_id": cliente, "client_secret": segredo, "refresh_token": credenciais["refresh_token"],
        "grant_type": "refresh_token"})
    dados = json_ou_vazio(resposta)
    if resposta.status_code != 200 or "access_token" not in dados:
        raise ErroPostagem("O acesso ao YouTube venceu ou foi retirado. Conecte a conta de novo.", reconectar=True)
    credenciais.atualizar(access_token=dados["access_token"])
    return dados["access_token"]


# ---------- envio ----------

def publicar(credenciais: Credenciais, arquivo: Path, titulo: str, legenda: str, opcoes: dict | None = None) -> Resultado:
    """Envia o video como Short publico. Renova o token sozinho se precisar."""
    token = _renovar(credenciais)            # o token de acesso dura ~1 hora: sempre comeca com um novo
    tamanho = arquivo.stat().st_size
    corpo = {
        "snippet": {"title": titulo[:100], "description": legenda[:5000], "categoryId": "20"},   # 20 = Games
        "status": {"privacyStatus": (opcoes or {}).get("privacidade", "public"), "selfDeclaredMadeForKids": False},
    }
    sessao = chamar("POST", URL_ENVIO, rede="youtube", params={"uploadType": "resumable", "part": "snippet,status"},
                    json=corpo, headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Length": str(tamanho),
                                         "X-Upload-Content-Type": "video/mp4"})
    if sessao.status_code in (401, 403):
        _explicar(sessao)
    endereco = sessao.headers.get("Location")
    if sessao.status_code != 200 or not endereco:
        _explicar(sessao)

    enviado = 0
    retomadas = 0
    with arquivo.open("rb") as video:
        while enviado < tamanho:
            video.seek(enviado)
            pedaco = video.read(PEDACO)
            fim = enviado + len(pedaco) - 1
            try:
                resposta = chamar("PUT", endereco, rede="youtube", data=pedaco, timeout=TEMPO_LIMITE_ENVIO,
                                  headers={"Authorization": f"Bearer {token}", "Content-Length": str(len(pedaco)),
                                           "Content-Range": f"bytes {enviado}-{fim}/{tamanho}"})
            except ErroPostagem:
                retomadas += 1
                if retomadas > TENTATIVAS_DE_RETOMADA:
                    raise
                enviado = _quanto_chegou(endereco, token, tamanho)
                continue
            if resposta.status_code in (200, 201):
                video_id = json_ou_vazio(resposta).get("id")
                if not video_id:
                    raise ErroPostagem("O YouTube terminou o envio mas não devolveu o vídeo.", temporario=True)
                return Resultado(id_externo=video_id, url=f"https://www.youtube.com/shorts/{video_id}")
            if resposta.status_code == 308:
                enviado = _proximo_byte(resposta)
                continue
            if resposta.status_code == 404:
                raise ErroPostagem("A sessão de envio do YouTube expirou. Vou começar de novo.", temporario=True)
            _explicar(resposta)
    raise ErroPostagem("O envio terminou sem resposta do YouTube.", temporario=True)


def _proximo_byte(resposta) -> int:
    """No 308 o YouTube diz ate onde recebeu (Range: bytes=0-N). Sem Range, nada chegou."""
    faixa = resposta.headers.get("Range")
    return int(faixa.rsplit("-", 1)[1]) + 1 if faixa else 0


def _quanto_chegou(endereco: str, token: str, tamanho: int) -> int:
    resposta = chamar("PUT", endereco, rede="youtube", headers={
        "Authorization": f"Bearer {token}", "Content-Length": "0", "Content-Range": f"bytes */{tamanho}"})
    if resposta.status_code == 308:
        return _proximo_byte(resposta)
    if resposta.status_code == 404:
        raise ErroPostagem("A sessão de envio do YouTube expirou. Vou começar de novo.", temporario=True)
    _explicar(resposta)


def _explicar(resposta) -> None:
    erro = json_ou_vazio(resposta).get("error", {})
    motivo = (erro.get("errors") or [{}])[0].get("reason", "") if isinstance(erro, dict) else ""
    mensagem = erro.get("message", "") if isinstance(erro, dict) else ""
    if resposta.status_code == 401:
        raise ErroPostagem("O acesso ao YouTube venceu. Conecte a conta de novo.", reconectar=True)
    if motivo in ("quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded"):
        raise ErroPostagem("O limite diário de envios do YouTube acabou. Tento de novo mais tarde.", temporario=True)
    if motivo in ("forbidden", "insufficientPermissions"):
        raise ErroPostagem("O YouTube negou a permissão de enviar vídeos. Conecte a conta de novo e aceite as permissões.",
                           reconectar=True)
    raise ErroPostagem(f"O YouTube recusou o vídeo ({resposta.status_code} {motivo}): {mensagem[:200]}".strip())
