"""Legenda: titulo, descricao e hashtags de um post, escritos pela IA (Haiku), com o credito da fonte.

O credito do video original e sempre acrescentado pelo sistema (nunca depende da IA).

Rodar sozinho, para um corte (gasta uma fracao de centavo):
    python -m app.postagem.legenda 3
"""
import re
import sys
import unicodedata

from app import banco, config, ia

ESQUEMA = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "descricao": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["titulo", "descricao", "hashtags"],
    "additionalProperties": False,
}
MAX_TITULO = 90


def _hashtag(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]", "", sem_acento)


def validar(dados: dict) -> list[str]:
    problemas = []
    titulo = dados.get("titulo", "").strip()
    if not titulo:
        problemas.append("O título está vazio.")
    elif len(titulo) > MAX_TITULO:
        problemas.append(f"O título tem {len(titulo)} caracteres; o máximo é {MAX_TITULO}.")
    if "#" in titulo:
        problemas.append("O título não pode ter hashtag.")
    if not dados.get("descricao", "").strip():
        problemas.append("A descrição está vazia.")
    elif len(dados["descricao"]) > 600:
        problemas.append("A descrição está longa demais: use de 1 a 3 frases curtas.")
    tags = [_hashtag(h) for h in dados.get("hashtags", []) if _hashtag(h)]
    if not 3 <= len(tags) <= 6:
        problemas.append(f"Vieram {len(tags)} hashtags válidas; use de 3 a 6.")
    return problemas


def credito(titulo_original: str, canal: str, url: str) -> str:
    if not url:
        return ""
    quem = f"{titulo_original} — {canal}" if canal and titulo_original else (canal or titulo_original or "vídeo original")
    return f"Fonte: {quem} ({url})"


def montar(dados: dict, fonte: str, rede: str) -> tuple[str, str]:
    """(titulo, legenda) no formato de cada rede, com hashtags e credito."""
    tags = " ".join("#" + _hashtag(h) for h in dados["hashtags"] if _hashtag(h))
    if rede == "youtube":
        tags = (tags + " #Shorts").strip()
    partes = [dados["descricao"].strip(), tags, fonte]
    if rede == "tiktok":                       # no TikTok o "titulo" do post e o texto inteiro
        partes.insert(0, dados["titulo"].strip())
    legenda = "\n\n".join(p for p in partes if p)
    return dados["titulo"].strip()[:100], legenda


def escrever(*, titulo: str, motivo: str = "", assunto: str = "", frase_na_tela: str = "", usuario_id: int,
             video_id: int | None = None, cliente=None) -> dict:
    """Pede a IA o titulo, a descricao e as hashtags. Devolve o dict ja conferido."""
    mensagem = "\n".join(linha for linha in [
        f"Título do editor: {titulo}",
        f"Por que foi escolhido: {motivo}" if motivo else "",
        f"Assunto falado: {assunto}" if assunto else "",
        f"Frase que aparece na tela: {frase_na_tela}" if frase_na_tela and frase_na_tela != "-" else "",
    ] if linha)
    return ia.pedir_json(
        modelo=config.MODELO_RAPIDO, esforco=config.ESFORCO_RAPIDO,
        sistema=ia.carregar_prompt("legenda_post.md"), mensagem=mensagem, esquema=ESQUEMA,
        validar=validar, etapa="legenda_post", usuario_id=usuario_id, video_id=video_id, cliente=cliente)


def sem_ia(titulo: str) -> dict:
    """Legenda simples, usada se a IA falhar (o post nao deixa de sair por causa disso)."""
    return {"titulo": titulo[:MAX_TITULO], "descricao": titulo, "hashtags": ["GTA6", "Rockstar", "games"]}


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("Uso: python -m app.postagem.legenda <numero do corte>")
        sys.exit(1)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    banco.criar_tabelas()
    _corte = banco.ler_corte(int(sys.argv[1]))
    _video = banco.ler_video(_corte["video_id"])
    _dados = escrever(titulo=_corte["titulo"], motivo=_corte["motivo"], usuario_id=1, video_id=_corte["video_id"])
    for _rede in ("youtube", "instagram", "tiktok"):
        _t, _l = montar(_dados, credito(_video["titulo"], _video["canal"], _video["url"]), _rede)
        print(f"--- {_rede}\nTítulo: {_t}\n{_l}\n")
