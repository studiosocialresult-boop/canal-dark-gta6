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
from app.postagem.redes import Credenciais, ErroPostagem, Numeros, Resultado, TEMPO_LIMITE_ENVIO, chamar, json_ou_vazio

GRAPH = f"https://graph.facebook.com/{config.VERSAO_META}"
RUPLOAD = "https://rupload.facebook.com"
ESCOPOS = ["pages_show_list", "pages_read_engagement", "pages_manage_posts",
           "instagram_basic", "instagram_content_publish", "business_management"]
log = config.criar_log("meta")
CAMPOS_PAGINA = ("id,name,access_token,picture{url},"
                 "instagram_business_account{id,username,profile_picture_url}")
ESPERA_PROCESSAMENTO_S = 600
INTERVALO_CONSULTA_S = 10
TENTATIVAS_ENVIO_IG = 4       # o envio ao Instagram as vezes falha a toa; tenta de novo na hora
ESPERA_ENTRE_ENVIOS_S = 30
_dormir = time.sleep          # trocado nos testes


def _app() -> tuple[str, str]:
    app_id, segredo = os.getenv("META_APP_ID"), os.getenv("META_APP_SECRET")
    if not (app_id and segredo):
        raise ErroPostagem("Faltam META_APP_ID e META_APP_SECRET no arquivo .env.")
    return app_id, segredo


def _erro_da_meta(resposta, contexto: str) -> ErroPostagem:
    # O servidor de envio (rupload) responde num formato proprio: {"debug_info": {"type": ..., "message": ...}}.
    depuracao = json_ou_vazio(resposta).get("debug_info") or {}
    if depuracao.get("type") == "ProcessingFailedError":
        # Visto em 14/11/2026: o MESMO arquivo ora passa, ora volta com este erro. E instabilidade da Meta,
        # nao defeito do video; por isso conta como temporario (tenta de novo mais tarde).
        return ErroPostagem(f"A Meta falhou ao receber o vídeo ({contexto}): instabilidade do lado dela. "
                            "Tento de novo sozinho.", temporario=True)
    if depuracao.get("message"):
        return ErroPostagem(f"A Meta recusou ({contexto}): {str(depuracao['message'])[:220]}",
                            temporario=bool(depuracao.get("retriable")))
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
    """Apps criados na Meta a partir de 2026 usam o Login para Empresas: as permissoes ficam
    guardadas numa "configuracao" e o endereco leva o numero dela (config_id) no lugar da lista de
    escopos. Sem META_CONFIG_ID no .env, continua o login antigo por escopos (apps mais velhos)."""
    app_id, _ = _app()
    pedido = {"client_id": app_id, "redirect_uri": retorno, "state": estado, "response_type": "code"}
    config_id = (os.getenv("META_CONFIG_ID") or "").strip()
    if config_id:
        pedido |= {"config_id": config_id, "override_default_response_type": "true"}
    else:
        pedido["scope"] = ",".join(ESCOPOS)
    return f"https://www.facebook.com/{config.VERSAO_META}/dialog/oauth?" + urlencode(pedido)


def _paginas_liberadas(token: str) -> list[dict]:
    """Paginas que o dono liberou no login.

    /me/accounts lista as Paginas que a pessoa administra no proprio perfil. Paginas que pertencem a
    um portfolio empresarial (Gerenciador de Negocios) nao aparecem ali: elas sao procuradas pelo
    portfolio. Cada passo fica no log para o erro nao virar adivinhacao."""
    lista = chamar("GET", f"{GRAPH}/me/accounts", rede="facebook",
                   params={"access_token": token, "limit": 100, "fields": CAMPOS_PAGINA})
    if lista.status_code != 200:
        raise _erro_da_meta(lista, "lista de Páginas")
    paginas = json_ou_vazio(lista).get("data", [])
    log.info("Meta: /me/accounts devolveu %d Pagina(s) (%d ja com token).",
             len(paginas), sum(1 for p in paginas if p.get("access_token")))
    if paginas:
        return paginas

    negocios = chamar("GET", f"{GRAPH}/me/businesses", rede="facebook",
                      params={"access_token": token, "limit": 50, "fields": "id,name"})
    if negocios.status_code != 200:
        log.info("Meta: /me/businesses recusou (%s): sem a permissao business_management nao da para "
                 "procurar Paginas do portfolio.", negocios.status_code)
        return []
    achadas, vistas = [], set()
    for negocio in json_ou_vazio(negocios).get("data", []):
        for caminho in ("owned_pages", "client_pages"):
            resposta = chamar("GET", f"{GRAPH}/{negocio['id']}/{caminho}", rede="facebook",
                              params={"access_token": token, "limit": 100, "fields": CAMPOS_PAGINA})
            if resposta.status_code != 200:
                log.info("Meta: %s do portfolio %s recusado (%s).", caminho,
                         negocio.get("name", negocio["id"]), resposta.status_code)
                continue
            dados = json_ou_vazio(resposta).get("data", [])
            log.info("Meta: %s do portfolio %s: %d Pagina(s).", caminho,
                     negocio.get("name", negocio["id"]), len(dados))
            for pagina in dados:
                if pagina.get("id") not in vistas:
                    vistas.add(pagina["id"])
                    achadas.append(pagina)
    return achadas


def _token_da_pagina(pagina_id: str, token: str) -> str:
    """Token de publicacao da Pagina, quando a listagem nao trouxe (acontece pelo portfolio)."""
    resposta = chamar("GET", f"{GRAPH}/{pagina_id}", rede="facebook",
                      params={"access_token": token, "fields": "access_token"})
    if resposta.status_code != 200:
        log.info("Meta: nao consegui o token da Pagina %s (%s).", pagina_id, resposta.status_code)
        return ""
    return json_ou_vazio(resposta).get("access_token", "")


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
    token = json_ou_vazio(longo)["access_token"]
    contas = []
    for pagina in _paginas_liberadas(token):
        if not pagina.get("access_token"):
            pagina["access_token"] = _token_da_pagina(pagina["id"], token)
        if not pagina.get("access_token"):
            log.info("Meta: a Pagina %s veio sem token de publicacao.", pagina.get("name", pagina["id"]))
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
        raise ErroPostagem("Nenhuma Página do Facebook veio no login. Conecte de novo e marque a sua Página; se ela for de um portfólio empresarial, aceite também o acesso ao portfólio.")
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
    for tentativa in range(1, TENTATIVAS_ENVIO_IG + 1):
        criar = chamar("POST", f"{GRAPH}/{ig_id}/media", rede="instagram", data={
            "media_type": "REELS", "upload_type": "resumable", "caption": legenda[:2200], "access_token": token})
        dados = json_ou_vazio(criar)
        if criar.status_code != 200 or "id" not in dados:
            raise _erro_da_meta(criar, "criar o Reel")
        container = dados["id"]
        try:
            _enviar_arquivo(dados.get("uri") or f"{RUPLOAD}/ig-api-upload/{config.VERSAO_META}/{container}", token,
                            arquivo, "instagram")
            break
        except ErroPostagem as erro:
            # Falha passageira no envio: comeca de novo com um Reel novo (o anterior expira sozinho em 24 h).
            if not erro.temporario or tentativa == TENTATIVAS_ENVIO_IG:
                raise
            log.info("Instagram: envio falhou (tentativa %d de %d): %s", tentativa, TENTATIVAS_ENVIO_IG, erro)
            _dormir(ESPERA_ENTRE_ENVIOS_S)

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


# ---------- numeros (Fase 8) ----------
# Conferido na documentacao da Graph API v27.0 em 14/11/2026 (detalhes no plano.md, Fase 8):
# - Instagram: like_count, comments_count e total_views_count no proprio post pedem so instagram_basic e
#   pages_read_engagement (o app ja tem). Curtidas ocultas pelo dono nao vem (fica vazio).
# - Facebook: curtidas e comentarios pelos resumos das listas do video. Visualizacoes do Facebook ficam
#   em video_insights, que pede read_insights e pages_manage_engagement (o app nao tem): ficam vazias.
# - Varios posts numa chamada (?ids=...). A doc nao diz o que acontece quando um deles foi apagado: se o
#   lote for recusado, le um por um.

CAMPOS_NUMEROS_IG = "like_count,comments_count,total_views_count"
CAMPOS_NUMEROS_FB = "likes.summary(true).limit(0),comments.summary(true).limit(0)"
LOTE_META = 50
CODIGOS_DE_ESPERA = (4, 17, 32, 341, 613, 80001, 80002)


def ler_numeros_instagram(credenciais: Credenciais, ids: list[str]) -> dict[str, Numeros]:
    """Visualizacoes, curtidas e comentarios dos Reels. Id ausente do resultado = post apagado."""
    return _ler_numeros("instagram", credenciais, ids, CAMPOS_NUMEROS_IG, lambda o: Numeros(
        _inteiro(o.get("total_views_count")), _inteiro(o.get("like_count")), _inteiro(o.get("comments_count"))))


def ler_numeros_facebook(credenciais: Credenciais, ids: list[str]) -> dict[str, Numeros]:
    """Curtidas e comentarios dos Reels da Pagina (visualizacoes vazias). Id ausente = post apagado."""
    return _ler_numeros("facebook", credenciais, ids, CAMPOS_NUMEROS_FB, lambda o: Numeros(
        None, _total(o.get("likes")), _total(o.get("comments"))))


def _ler_numeros(rede: str, credenciais: Credenciais, ids: list[str], campos: str, converter) -> dict[str, Numeros]:
    if not ids:
        return {}
    token = credenciais["page_token"]
    numeros: dict[str, Numeros] = {}
    talvez_apagados: list[str] = []
    for inicio in range(0, len(ids), LOTE_META):
        lote = ids[inicio:inicio + LOTE_META]
        resposta = chamar("GET", f"{GRAPH}/", rede=rede, params={"ids": ",".join(lote), "fields": campos,
                                                                 "access_token": token})
        dados = json_ou_vazio(resposta)
        if resposta.status_code == 200 and all(isinstance(dados.get(i), dict) for i in lote):
            numeros.update({i: converter(dados[i]) for i in lote})
            continue
        if resposta.status_code == 200 or _vale_tentar_um_por_um(resposta, rede):
            # o lote nao veio inteiro (provavelmente um post apagado): pergunta um por um
            for post_id in lote:
                um = chamar("GET", f"{GRAPH}/{post_id}", rede=rede, params={"fields": campos, "access_token": token})
                if um.status_code == 200:
                    numeros[post_id] = converter(json_ou_vazio(um))
                elif _codigo(um) == (100, 33):
                    talvez_apagados.append(post_id)
                else:
                    raise _erro_leitura(um, rede)
            continue
        raise _erro_leitura(resposta, rede)
    if talvez_apagados and not numeros:
        # "nao existe" tambem aparece quando falta permissao: sem nenhum post lido, nao da para saber
        raise ErroPostagem(f"A Meta não devolveu nenhum post desta conta ({len(talvez_apagados)}). "
                           "Leio de novo mais tarde.")
    return numeros


def _vale_tentar_um_por_um(resposta, rede: str) -> bool:
    """Lote recusado: so desiste da conta inteira se o erro e de acesso vencido ou de espera."""
    erro = _erro_leitura(resposta, rede)
    return not (erro.reconectar or erro.temporario)


def _codigo(resposta) -> tuple:
    erro = json_ou_vazio(resposta).get("error") or {}
    return (erro.get("code"), erro.get("error_subcode")) if isinstance(erro, dict) else (None, None)


def _erro_leitura(resposta, rede: str) -> ErroPostagem:
    """Erros ao LER numeros. Diferente da postagem: falta de permissao aqui nao pede para reconectar
    (isso seguraria os posts agendados da conta); so o token vencido pede."""
    erro = json_ou_vazio(resposta).get("error") or {}
    erro = erro if isinstance(erro, dict) else {}
    codigo = erro.get("code")
    if codigo == 190 or resposta.status_code == 401:
        return ErroPostagem("O acesso à Meta venceu ou foi retirado. Conecte a conta de novo.", reconectar=True)
    if codigo in CODIGOS_DE_ESPERA or erro.get("is_transient"):
        return ErroPostagem("A Meta pediu para esperar (limite de uso). Leio os números mais tarde.", temporario=True)
    mensagem = str(erro.get("message") or resposta.status_code)[:200]
    return ErroPostagem(f"A Meta não deixou ler os números ({rede}, código {codigo}): {mensagem}")


def _inteiro(valor) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _total(lista) -> int | None:
    return _inteiro(((lista or {}).get("summary") or {}).get("total_count")) if isinstance(lista, dict) else None
