"""Cartao: desenha tudo o que fica em volta do video (faixas, frase, foto e nome).

Devolve uma imagem 1080x1920 transparente nas zonas de video e a posicao
dessas zonas. O ffmpeg coloca os videos nas zonas e esta imagem por cima.
Assim a previa do assistente e o video final saem da mesma conta.

Rodar sozinho, para ver um exemplo (gera dados/tmp/cartao_<layout>.png):
    python -m app.multiplicador.cartao
"""
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app import config as cfg
from app.multiplicador import modelos
from app.multiplicador.modelos import ALTURA, CORES, LARGURA, LAYOUTS

Retangulo = tuple[int, int, int, int]      # x, y, largura, altura

FONTES_NEGRITO = [
    "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
]
FONTES_NORMAL = [
    "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial.ttf",
]
_cache: dict = {}


def fonte(tamanho: int, negrito: bool = False) -> ImageFont.FreeTypeFont:
    chave = (tamanho, negrito)
    if chave not in _cache:
        for caminho in (FONTES_NEGRITO if negrito else FONTES_NORMAL):
            if Path(caminho).exists():
                _cache[chave] = ImageFont.truetype(caminho, tamanho)
                break
        else:
            _cache[chave] = ImageFont.load_default(tamanho)
    return _cache[chave]


def limpar_texto(texto: str) -> str:
    """Tira emojis e caracteres de controle: a fonte do cartao nao tem desenho para eles."""
    texto = re.sub(r"[\U00010000-\U0010FFFF\u200d\ufe0f]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def quebrar_linhas(texto: str, letra: ImageFont.FreeTypeFont, largura: int) -> list[str]:
    """Divide o texto em linhas que cabem na largura (nao corta palavras)."""
    linhas, atual = [], ""
    for palavra in texto.split(" "):
        teste = f"{atual} {palavra}".strip()
        if atual and letra.getlength(teste) > largura:
            linhas.append(atual)
            atual = palavra
        else:
            atual = teste
    if atual:
        linhas.append(atual)
    return linhas


def quebrar_equilibrado(texto: str, letra: ImageFont.FreeTypeFont, largura: int) -> list[str]:
    """Como quebrar_linhas, mas evita deixar uma palavra sozinha na ultima linha."""
    linhas = quebrar_linhas(texto, letra, largura)
    folga = largura
    while len(linhas) > 1 and len(linhas[-1].split(" ")) == 1 and folga > largura * 0.6:
        folga -= largura * 0.04
        tentativa = quebrar_linhas(texto, letra, int(folga))
        if len(tentativa) > len(linhas):
            break
        linhas = tentativa
    return linhas


def ajustar_texto(texto: str, tamanho_max: int, largura: int, altura_max: int, entrelinha: float):
    """Maior fonte (ate tamanho_max) em que o texto cabe em largura x altura_max."""
    tamanho = tamanho_max
    while True:
        letra = fonte(tamanho, True)
        linhas = quebrar_equilibrado(texto, letra, largura)
        altura_linha = int(tamanho * entrelinha)
        if len(linhas) * altura_linha <= altura_max or tamanho <= 28:
            return letra, linhas, altura_linha
        tamanho -= 2


def _cor_hex(valor: str | None, padrao: tuple) -> tuple:
    if valor and re.fullmatch(r"#[0-9a-fA-F]{6}", valor):
        return tuple(int(valor[i:i + 2], 16) for i in (1, 3, 5))
    return padrao


def _avatar(caminho: Path | None, nome: str, tamanho: int) -> Image.Image:
    """Foto redonda; sem foto, a inicial do nome sobre um degradê."""
    if caminho and Path(caminho).exists():
        try:
            foto = Image.open(caminho).convert("RGB")
            lado = min(foto.size)
            foto = foto.crop(((foto.width - lado) // 2, (foto.height - lado) // 2,
                              (foto.width + lado) // 2, (foto.height + lado) // 2))
            foto = foto.resize((tamanho, tamanho), Image.LANCZOS)
        except OSError:
            foto = None
    else:
        foto = None
    if foto is None:
        foto = Image.new("RGB", (tamanho, tamanho))
        pintor = ImageDraw.Draw(foto)
        for y in range(tamanho):                      # degrade na diagonal, nas cores da marca
            t = y / tamanho
            pintor.line([(0, y), (tamanho, y)], fill=(int(106 + 149 * t), int(69 + 10 * t), int(255 - 116 * t)))
        inicial = (limpar_texto(nome) or "?")[0].upper()
        letra = fonte(int(tamanho * 0.5), True)
        caixa = pintor.textbbox((0, 0), inicial, font=letra)
        pintor.text(((tamanho - (caixa[2] - caixa[0])) / 2 - caixa[0],
                     (tamanho - (caixa[3] - caixa[1])) / 2 - caixa[1]), inicial, font=letra, fill="white")
    # recorte redondo com borda suave (desenhado em escala maior e reduzido)
    mascara = Image.new("L", (tamanho * 4, tamanho * 4), 0)
    ImageDraw.Draw(mascara).ellipse((0, 0, tamanho * 4 - 1, tamanho * 4 - 1), fill=255)
    foto.putalpha(mascara.resize((tamanho, tamanho), Image.LANCZOS))
    return foto


def _perfil(imagem: Image.Image, pintor: ImageDraw.ImageDraw, config: dict, cores: dict,
            y: int, avatar: Path | None, alinh: str) -> int:
    """Desenha foto + nome + @ na altura y. Devolve a altura ocupada."""
    p = config["perfil"]
    tam = p["tam_avatar"]
    nome = limpar_texto(p["nome"]) or "Seu Nome"
    handle = "@" + limpar_texto(p["handle"]).lstrip("@") if limpar_texto(p["handle"]) else ""
    f_nome, f_handle = fonte(p["fonte_nome"], True), fonte(p["fonte_handle"])
    largura_texto = max(f_nome.getlength(nome), f_handle.getlength(handle))
    espaco = 24
    total = tam + espaco + largura_texto
    margem = config["texto"]["espaco_lateral"]
    x = margem if alinh == "esquerda" else (LARGURA - margem - total if alinh == "direita" else (LARGURA - total) / 2)
    imagem.alpha_composite(_avatar(avatar, nome, tam), (int(x), y))
    texto_x = int(x + tam + espaco)
    altura_bloco = f_nome.size + (f_handle.size + 6 if handle else 0)
    topo = y + (tam - altura_bloco) // 2
    pintor.text((texto_x, topo), nome, font=f_nome, fill=cores["texto"])
    if handle:
        pintor.text((texto_x, topo + f_nome.size + 6), handle, font=f_handle, fill=cores["suave"])
    return tam


def _frase(pintor: ImageDraw.ImageDraw, texto: str, config: dict, cores: dict, y: int,
           altura_max: int, alinh: str, centro_vertical: Retangulo | None = None) -> int:
    """Desenha a frase a partir de y (ou centrada em uma faixa). Devolve a altura usada."""
    t = config["texto"]
    margem = t["espaco_lateral"]
    letra, linhas, altura_linha = ajustar_texto(limpar_texto(texto) or " ", t["tamanho"],
                                                LARGURA - 2 * margem, altura_max, t["entrelinha"])
    cor = _cor_hex(t["cor"], cores["texto"])
    altura = len(linhas) * altura_linha
    if centro_vertical:
        _, faixa_y, _, faixa_h = centro_vertical
        y = faixa_y + (faixa_h - altura) // 2
    for i, linha in enumerate(linhas):
        largura = letra.getlength(linha)
        x = margem if alinh == "esquerda" else (LARGURA - margem - largura if alinh == "direita" else (LARGURA - largura) / 2)
        pintor.text((x, y + i * altura_linha), linha, font=letra, fill=cor)
    return altura


def compor(layout: str, config_salva: dict | None, frase: str, avatar: Path | None = None):
    """Monta o cartao. Devolve (imagem RGBA 1080x1920, {"video": retangulo, "video2": retangulo?})."""
    if layout not in LAYOUTS:
        raise ValueError(f"Layout desconhecido: {layout}")
    config = modelos.config_completa(config_salva)
    cores = CORES[config["perfil"]["tema"] if config["perfil"]["tema"] in CORES else "escuro"]
    imagem = Image.new("RGBA", (LARGURA, ALTURA), cores["fundo"] + (255,))
    pintor = ImageDraw.Draw(imagem)
    mostrar_perfil = modelos.perfil_visivel(layout, config)
    posicao = modelos.posicao_do_perfil(layout, config)
    margem = config["texto"]["espaco_lateral"]
    tam_avatar = config["perfil"]["tam_avatar"]
    minima = config["texto"]["faixa_minima"]
    zonas: dict[str, Retangulo] = {}
    alinh = modelos.alinhamento(layout, config)

    if layout == "cheio":
        zonas["video"] = (0, 0, LARGURA, ALTURA)

    elif layout == "post":
        y = 150
        if mostrar_perfil and posicao == "topo":
            y += _perfil(imagem, pintor, config, cores, y, avatar, alinh) + 36
        altura_frase = _frase(pintor, frase, config, cores, y, 640, alinh)
        y += max(altura_frase, minima) + 44
        rodape = 0
        if mostrar_perfil and posicao == "base":
            rodape = tam_avatar + 70
            _perfil(imagem, pintor, config, cores, ALTURA - rodape + 20, avatar, alinh)
        zonas["video"] = (0, y, LARGURA, ALTURA - y - max(rodape, 90))

    elif layout == "meme":
        topo = 110
        altura_frase = _frase(pintor, frase, config, cores, topo, 620, alinh)
        y = topo + max(altura_frase, minima) + 56
        rodape = (tam_avatar + 110) if (mostrar_perfil and posicao == "base") else 90
        if mostrar_perfil and posicao == "base":
            _perfil(imagem, pintor, config, cores, ALTURA - rodape + 36, avatar, alinh)
        elif mostrar_perfil:
            y += _perfil(imagem, pintor, config, cores, y, avatar, alinh) + 30
        zonas["video"] = (0, y, LARGURA, ALTURA - y - rodape)

    else:  # viral: video em cima, faixa com a frase, video embaixo
        faixa_h = max(minima, 250)
        letra_h = 250
        zona_h = (ALTURA - faixa_h) // 2
        faixa = (0, zona_h, LARGURA, faixa_h)
        _frase(pintor, frase, config, cores, 0, letra_h - 40, alinh, centro_vertical=faixa)
        zonas["video"] = (0, 0, LARGURA, zona_h)
        zonas["video2"] = (0, zona_h + faixa_h, LARGURA, ALTURA - zona_h - faixa_h)
        if mostrar_perfil:
            _perfil(imagem, pintor, config, cores, zona_h + faixa_h - tam_avatar // 2 - 70, avatar, alinh)

    # as zonas de video ficam transparentes: o ffmpeg coloca os videos por baixo
    for x, y, w, h in zonas.values():
        pintor.rectangle((x, y, x + w - 1, y + h - 1), fill=(0, 0, 0, 0))
    return imagem, zonas


if __name__ == "__main__":
    cfg.garantir_pastas()
    pasta = cfg.PASTA_DADOS / "tmp"
    pasta.mkdir(parents=True, exist_ok=True)
    exemplo = "A Rockstar anunciou um festival ao vivo em Miami para celebrar o lançamento do GTA 6"
    for _layout in LAYOUTS:
        _imagem, _zonas = compor(_layout, {}, exemplo)
        _fundo = Image.new("RGBA", (LARGURA, ALTURA), (60, 60, 70, 255))   # cinza no lugar do video
        _fundo.alpha_composite(_imagem)
        _fundo.convert("RGB").save(pasta / f"cartao_{_layout}.png")
        print(_layout, _zonas)
    print("Imagens em", pasta)
