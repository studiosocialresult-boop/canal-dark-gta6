"""Servidor do painel: as paginas, a API que elas usam e a entrega dos videos.

Rodar (ou use o iniciar_painel.bat):
    python -m app.painel

O painel e de uso local: escuta so neste computador (127.0.0.1) e nao tem login.
Antes de colocar na VPS (Fase 7) ele precisa de protecao de acesso.
"""
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import banco, config
from app.download import baixar
from app.painel import fila

PASTA = Path(__file__).resolve().parent
USUARIO = config.USUARIO_PADRAO

# Estados em que um corte aparece na revisao.
ESTADOS_REVISAVEIS = ("renderizado", "aprovado", "descartado", "falhou", "proposto")
ESTADOS_QUE_O_DONO_ESCOLHE = ("renderizado", "aprovado", "descartado")

# Telas do menu. "fase" diz quando cada uma nasce; as que ainda nao existem avisam isso.
MENU = [
    {"id": "hoje", "nome": "Hoje", "icone": "sol", "fase": 6,
     "descricao": "O ranking do dia: os vídeos de GTA 6 que mais estão crescendo agora."},
    {"id": "cortes", "nome": "Cortes", "icone": "tesoura", "fase": 3, "descricao": ""},
    {"id": "templates", "nome": "Templates", "icone": "camadas", "fase": 4,
     "descricao": "Crie dezenas de vídeos de uma vez: um modelo de layout, várias frases e vídeos."},
    {"id": "perfis", "nome": "Perfis", "icone": "radar", "fase": 4,
     "descricao": "Analise um perfil ou canal e traga os posts mais vistos direto para os cortes."},
    {"id": "editor", "nome": "Editor", "icone": "lapis", "fase": 4,
     "descricao": "Ajuste rápido de um vídeo para o formato vertical."},
    {"id": "agenda", "nome": "Agenda", "icone": "calendario", "fase": 5,
     "descricao": "O calendário do que está agendado em cada conta, rede por rede."},
    {"id": "contas", "nome": "Contas", "icone": "plug", "fase": 5,
     "descricao": "Conecte YouTube, Instagram, TikTok e Facebook para publicar daqui."},
]

# Configuracoes que o dono pode mudar na tela: (chave, nome, ajuda, minimo, maximo, unidade).
CONFIGURACOES = [
    ("cortes_min", "Mínimo de cortes por vídeo", "A IA devolve menos se não achar trechos bons.", 1, 10, ""),
    ("cortes_max", "Máximo de cortes por vídeo", "Quantos cortes, no máximo, sairão de cada vídeo.", 1, 15, ""),
    ("duracao_min_s", "Duração mínima do corte", "Cortes mais curtos que isso são recusados.", 10, 90, "s"),
    ("duracao_max_s", "Duração máxima do corte", "Cortes mais longos que isso são recusados.", 15, 180, "s"),
    ("nota_minima_narracao", "Nota mínima para narrar sozinho",
     "Só cortes com nota igual ou maior ganham narração automática (a voz custa dinheiro).", 0, 100, ""),
]


def criar_app() -> FastAPI:
    config.garantir_pastas()
    banco.criar_tabelas()
    trabalhador = fila.Trabalhador()

    @asynccontextmanager
    async def ciclo_de_vida(_app):
        if os.getenv("CANAL_SEM_TRABALHADOR") != "1":
            trabalhador.start()
        yield
        trabalhador.parar()

    app = FastAPI(title="Canal Dark", docs_url=None, redoc_url=None, lifespan=ciclo_de_vida)
    app.mount("/estatico", StaticFiles(directory=PASTA / "estatico"), name="estatico")
    paginas = Jinja2Templates(directory=PASTA / "paginas")

    def contexto(request: Request, ativa: str, **extra) -> dict:
        return {"request": request, "menu": MENU, "ativa": ativa, **extra}

    # ---------- paginas ----------

    @app.get("/")
    def inicio():
        return RedirectResponse("/cortes")

    @app.get("/cortes")
    def pagina_cortes(request: Request):
        return paginas.TemplateResponse(request, "cortes.html", contexto(request, "cortes"))

    @app.get("/configuracoes")
    def pagina_configuracoes(request: Request):
        return paginas.TemplateResponse(request, "configuracoes.html", contexto(request, "configuracoes"))

    @app.get("/{tela}")
    def pagina_futura(request: Request, tela: str):
        item = next((m for m in MENU if m["id"] == tela), None)
        if item is None:
            raise HTTPException(404, "Esta página não existe.")
        return paginas.TemplateResponse(request, "em_breve.html", contexto(request, tela, item=item))

    # ---------- cortes ----------

    @app.get("/api/cortes")
    def api_cortes():
        return {"cortes": [_corte_json(l) for l in banco.listar_cortes(USUARIO)
                           if l["estado"] in ESTADOS_REVISAVEIS],
                "numeros": _numeros()}

    @app.get("/api/numeros")
    def api_numeros():
        return _numeros()

    @app.post("/api/cortes/{corte_id}/estado")
    def api_estado(corte_id: int, dados: dict = Body(...)):
        estado = dados.get("estado")
        if estado not in ESTADOS_QUE_O_DONO_ESCOLHE:
            raise HTTPException(400, "Estado inválido.")
        _corte_do_dono(corte_id)
        banco.atualizar_corte(corte_id, estado=estado)
        return {"ok": True}

    @app.post("/api/cortes/estado")
    def api_estado_em_massa(dados: dict = Body(...)):
        estado, ids = dados.get("estado"), dados.get("ids") or []
        if estado not in ESTADOS_QUE_O_DONO_ESCOLHE or not isinstance(ids, list):
            raise HTTPException(400, "Pedido inválido.")
        for corte_id in ids:
            _corte_do_dono(int(corte_id))
            banco.atualizar_corte(int(corte_id), estado=estado)
        return {"ok": True, "total": len(ids)}

    @app.post("/api/cortes/{corte_id}/narrar")
    def api_narrar(corte_id: int):
        corte = _corte_do_dono(corte_id)
        if not corte["caminho_arquivo"]:
            raise HTTPException(400, "Este corte ainda não foi montado.")
        if not os.getenv("ELEVENLABS_API_KEY"):
            raise HTTPException(400, "Falta a chave da ElevenLabs no arquivo .env.")
        if banco.item_na_fila(USUARIO, "narrar", str(corte_id)):
            raise HTTPException(409, "Este corte já está na fila para narrar.")
        item_id = banco.enfileirar(USUARIO, "narrar", str(corte_id), corte["titulo"])
        return {"ok": True, "item": item_id}

    @app.get("/miniatura/{corte_id}.jpg")
    def miniatura(corte_id: int):
        corte = _corte_do_dono(corte_id)
        if not corte["caminho_arquivo"]:
            raise HTTPException(404)
        video = config.caminho_absoluto(corte["caminho_arquivo"])
        if not video.exists():
            raise HTTPException(404)
        imagem = video.with_suffix(".jpg")
        if not imagem.exists() or imagem.stat().st_mtime < video.stat().st_mtime:
            _gerar_miniatura(video, imagem)
        return FileResponse(imagem, headers={"Cache-Control": "no-cache"})

    @app.get("/midia/{caminho:path}")
    def midia(caminho: str):
        arquivo = (config.PASTA_DADOS / caminho).resolve()
        if not arquivo.is_relative_to(config.PASTA_CORTES.resolve()) or not arquivo.is_file():
            raise HTTPException(404)
        return FileResponse(arquivo, headers={"Cache-Control": "no-cache"})

    # ---------- fila ----------

    @app.get("/api/fila")
    def api_fila():
        itens = [_item_json(i) for i in banco.listar_fila(USUARIO)]
        return {"itens": itens, "ativos": sum(1 for i in itens if i["estado"] in ("aguardando", "processando"))}

    @app.post("/api/links")
    def api_link(dados: dict = Body(...)):
        url = str(dados.get("url", "")).strip()
        try:
            plataforma, id_externo = baixar.identificar(url)
        except ValueError:
            raise HTTPException(400, "Esse link não parece ser de um vídeo do YouTube. Cole o endereço "
                                     "completo, como https://www.youtube.com/watch?v=…")
        registro = banco.buscar_video(USUARIO, plataforma, id_externo)
        if registro and registro["estado"] == "pronto":
            raise HTTPException(409, "Este vídeo já foi processado. Os cortes dele estão na lista.")
        if banco.item_na_fila(USUARIO, "link", url):
            raise HTTPException(409, "Este link já está na fila.")
        item_id = banco.enfileirar(USUARIO, "link", url, url)
        return {"ok": True, "item": item_id, "plataforma": plataforma}

    # ---------- configuracoes ----------

    @app.get("/api/configuracoes")
    def api_configuracoes():
        valores = [{"chave": c, "nome": n, "ajuda": a, "minimo": mi, "maximo": ma, "unidade": u,
                    "valor": banco.ler_config(USUARIO, c)} for c, n, a, mi, ma, u in CONFIGURACOES]
        return {"valores": valores, "sistema": _sistema()}

    @app.put("/api/configuracoes")
    def api_salvar_configuracoes(dados: dict = Body(...)):
        limites = {c: (mi, ma) for c, _n, _a, mi, ma, _u in CONFIGURACOES}
        novos = {}
        for chave, valor in dados.items():
            if chave not in limites:
                raise HTTPException(400, f"Configuração desconhecida: {chave}")
            try:
                valor = int(valor)
            except (TypeError, ValueError):
                raise HTTPException(400, "Use só números inteiros.")
            minimo, maximo = limites[chave]
            if not minimo <= valor <= maximo:
                raise HTTPException(400, f"O valor deve ficar entre {minimo} e {maximo}.")
            novos[chave] = valor
        atual = {c: banco.ler_config(USUARIO, c) for c in limites} | novos
        if atual["cortes_min"] > atual["cortes_max"]:
            raise HTTPException(400, "O mínimo de cortes não pode passar do máximo.")
        if atual["duracao_min_s"] >= atual["duracao_max_s"]:
            raise HTTPException(400, "A duração mínima precisa ser menor que a máxima.")
        for chave, valor in novos.items():
            banco.salvar_config(USUARIO, chave, valor)
        return {"ok": True}

    @app.exception_handler(HTTPException)
    async def erro_http(_request, erro: HTTPException):
        return JSONResponse({"erro": erro.detail}, status_code=erro.status_code)

    return app


# ---------- ajudantes ----------

def _corte_do_dono(corte_id: int):
    corte = banco.ler_corte(corte_id)
    if corte is None or corte["usuario_id"] != USUARIO:
        raise HTTPException(404, "Corte não encontrado.")
    return corte


def _corte_json(l) -> dict:
    arquivo = l["caminho_arquivo"]
    return {
        "id": l["id"], "video_id": l["video_id"], "titulo": l["titulo"], "nota": l["nota"],
        "modo": l["modo"], "estado": l["estado"], "motivo": l["motivo"], "erro": l["erro"],
        "duracao_s": round(l["fim_s"] - l["inicio_s"], 1),
        "canal": l["video_canal"] or "", "video_titulo": l["video_titulo"] or "",
        "video_url": l["video_url"], "plataforma": l["video_plataforma"],
        "narracao": l["narracao_estado"], "custo_usd": round(l["custo_usd"], 3),
        "criado_em": l["criado_em"],
        "midia": f"/midia/{arquivo}" if arquivo else None,
        "miniatura": f"/miniatura/{l['id']}.jpg" if arquivo else None,
    }


def _numeros() -> dict:
    n = banco.numeros_do_painel(USUARIO)
    estados = n["estados"]
    return {
        "revisar": estados.get("renderizado", 0), "aprovados": estados.get("aprovado", 0),
        "descartados": estados.get("descartado", 0), "falhas": estados.get("falhou", 0),
        "cortes_hoje": n["cortes_hoje"], "videos": n["videos_prontos"],
        "gasto_usd": round(n["gasto_usd"], 2), "gasto_hoje_usd": round(n["gasto_hoje_usd"], 2),
    }


def _item_json(i) -> dict:
    rotulo = i["rotulo"]
    if i["tipo"] == "link":
        try:
            plataforma, id_externo = baixar.identificar(i["alvo"])
            video = banco.buscar_video(i["usuario_id"], plataforma, id_externo)
            if video and video["titulo"]:
                rotulo = video["titulo"]
        except ValueError:
            pass
    return {"id": i["id"], "tipo": i["tipo"], "rotulo": rotulo, "estado": i["estado"],
            "progresso": i["progresso"], "resultado": i["resultado"],
            "criado_em": i["criado_em"], "iniciado_em": i["iniciado_em"],
            "terminado_em": i["terminado_em"]}


def _sistema() -> dict:
    """O que esta pronto no computador: chaves, programas e login do YouTube."""
    return {
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY")),
        "cookies": config.ARQUIVO_COOKIES.exists(),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "deno": shutil.which("deno") is not None,
        "voz_id": config.VOZ_ID,
        "modelo_cerebro": config.MODELO_CEREBRO,
        "modelo_rapido": config.MODELO_RAPIDO,
    }


def _gerar_miniatura(video: Path, imagem: Path) -> None:
    resultado = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", "1.5", "-i", str(video),
         "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", str(imagem)],
        capture_output=True, text=True)
    if resultado.returncode != 0 or not imagem.exists():
        raise HTTPException(500, "Não consegui gerar a miniatura.")


app = criar_app()
