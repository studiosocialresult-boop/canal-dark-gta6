"""Testes da base da Fase 1. Nao usam internet nem gastam credito de API.

Rodar:
    .venv\\Scripts\\python.exe -m unittest discover testes -v
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

# Os testes usam uma pasta de dados temporaria, para nunca mexer no banco de verdade.
_PASTA_TEMPORARIA = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["CANAL_PASTA_DADOS"] = _PASTA_TEMPORARIA.name

from app import banco, config, ia  # noqa: E402
from app.cerebro import escolher  # noqa: E402
from app.contratos import Frase, Palavra, Transcricao, VideoBaixado  # noqa: E402
from app.transcricao import frases as modulo_frases  # noqa: E402


def transcricao_falsa(quantidade: int = 30, duracao_frase: float = 5.0) -> Transcricao:
    """Uma transcricao inventada: frases de 5 segundos, uma colada na outra."""
    lista = []
    for i in range(quantidade):
        inicio = i * duracao_frase
        texto = f"Esta e a frase numero {i} do video."
        lista.append(Frase(i, inicio, inicio + duracao_frase - 0.2, texto,
                           modulo_frases.repartir_tempo(texto, inicio, inicio + duracao_frase - 0.2)))
    return Transcricao("pt", quantidade * duracao_frase, lista)


def resposta_falsa(dados: dict):
    """Imita o formato de uma resposta da API da Anthropic."""
    return SimpleNamespace(
        stop_reason="end_turn",
        stop_details=None,
        content=[SimpleNamespace(type="text", text=json.dumps(dados))],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )


class ClienteFalso:
    """Cliente de mentira: devolve as respostas preparadas, uma por chamada."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []
        self.messages = self

    def stream(self, **parametros):
        self.chamadas.append(parametros)
        return _Fluxo(self.respostas.pop(0))


class _Fluxo:
    def __init__(self, resposta):
        self.resposta = resposta

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_final_message(self):
        return self.resposta


def corte(inicio, fim, nota=80, modo="narrado", titulo="Detalhe do trailer que ninguem viu"):
    return {"frase_inicio": inicio, "frase_fim": fim, "motivo": "Gancho forte e desfecho claro.",
            "nota": nota, "modo": modo, "titulo": titulo}


class TesteFrases(unittest.TestCase):
    def test_quebra_na_pontuacao(self):
        palavras = modulo_frases.repartir_tempo(
            "O trailer saiu hoje. Ninguem esperava isso! Sera que o mapa e maior?", 0.0, 9.0)
        resultado = modulo_frases.montar_frases(palavras)
        self.assertEqual([f.texto for f in resultado],
                         ["O trailer saiu hoje.", "Ninguem esperava isso!", "Sera que o mapa e maior?"])
        self.assertEqual([f.id for f in resultado], [0, 1, 2])

    def test_numero_com_ponto_nao_quebra(self):
        palavras = modulo_frases.repartir_tempo("O jogo custa 3.5 bilhoes de dolares.", 0.0, 4.0)
        self.assertEqual(len(modulo_frases.montar_frases(palavras)), 1)

    def test_pausa_longa_quebra_sem_pontuacao(self):
        palavras = [Palavra("olha", 0.0, 0.4), Palavra("isso", 0.4, 0.8),
                    Palavra("caramba", 3.0, 3.6)]
        self.assertEqual(len(modulo_frases.montar_frases(palavras)), 2)

    def test_fala_sem_pontuacao_tem_limite(self):
        palavras = [Palavra("palavra", i * 0.5, i * 0.5 + 0.45) for i in range(200)]
        resultado = modulo_frases.montar_frases(palavras)
        self.assertGreater(len(resultado), 1)
        self.assertTrue(all(f.fim - f.inicio <= 26 for f in resultado))

    def test_repartir_tempo_cobre_a_frase(self):
        palavras = modulo_frases.repartir_tempo("uma frase traduzida qualquer", 10.0, 14.0)
        self.assertEqual(palavras[0].inicio, 10.0)
        self.assertEqual(palavras[-1].fim, 14.0)
        self.assertTrue(all(a.fim <= b.inicio + 0.001 for a, b in zip(palavras, palavras[1:])))


class TesteDownload(unittest.TestCase):
    def test_reconhece_links_do_youtube(self):
        from app.download import baixar
        esperado = ("youtube", "jNQXAC9IVRw")
        for link in ("https://www.youtube.com/watch?v=jNQXAC9IVRw&t=5s",
                     "https://youtu.be/jNQXAC9IVRw?si=abc",
                     "https://www.youtube.com/shorts/jNQXAC9IVRw",
                     "https://m.youtube.com/watch?v=jNQXAC9IVRw",
                     "https://www.youtube.com/live/jNQXAC9IVRw"):
            self.assertEqual(baixar.identificar(link), esperado, link)

    def test_recusa_link_desconhecido(self):
        from app.download import baixar
        for link in ("https://exemplo.com/video", "https://www.youtube.com/@canal", "texto solto"):
            with self.assertRaises(ValueError):
                baixar.identificar(link)


class TesteTranscricaoReal(unittest.TestCase):
    """Usa o video de exemplo em testes/ e o modelo de voz local. Pula se nao houver o video."""
    VIDEO = Path(__file__).parent / "exemplo_zoo.mp4"

    @unittest.skipUnless(VIDEO.exists(), "video de exemplo ausente")
    def test_transcreve_video_de_exemplo(self):
        from app.transcricao import transcrever
        resultado = transcrever.transcrever(self.VIDEO)
        self.assertEqual(resultado.idioma, "en")
        self.assertGreaterEqual(len(resultado.frases), 2)
        self.assertIn("elephants", " ".join(f.texto for f in resultado.frases).lower())
        for frase in resultado.frases:
            self.assertLess(frase.inicio, frase.fim)


class TesteEdicao(unittest.TestCase):
    def test_legenda_usa_tempo_do_corte(self):
        from app.edicao import cortar
        palavras = modulo_frases.repartir_tempo("Olha que coisa incrível.", 100.0, 102.0)
        ass = cortar.gerar_ass([Frase(0, 100.0, 102.0, "", palavras)], 99.5, 5.0)
        dialogos = [l for l in ass.splitlines() if l.startswith("Dialogue")]
        self.assertTrue(dialogos[0].startswith("Dialogue: 0,0:00:00.50,"))   # 100.0 - 99.5
        self.assertIn("OLHA", ass)

    def test_grupos_cabem_na_tela(self):
        from app.edicao import cortar
        texto = "uma frase bem comprida para conferir se a legenda quebra em grupos pequenos"
        grupos = cortar._agrupar(modulo_frases.repartir_tempo(texto, 0.0, 6.0))
        for grupo in grupos:
            if len(grupo) > 1:
                self.assertLessEqual(len(" ".join(p.texto for p in grupo)), cortar.MAX_CARACTERES_GRUPO)

    def test_chaves_nao_viram_comando(self):
        from app.edicao import cortar
        palavras = [Palavra("{\\b1}oi", 0.0, 1.0)]
        ass = cortar.gerar_ass([Frase(0, 0.0, 1.0, "", palavras)], 0.0, 2.0)
        self.assertNotIn("{\\b1}", ass)

    @unittest.skipUnless((Path(__file__).parent / "exemplo_zoo.mp4").exists(), "video de exemplo ausente")
    def test_gera_mp4_vertical(self):
        import subprocess
        from app.contratos import CorteProposto
        from app.edicao import cortar
        palavras = modulo_frases.repartir_tempo("Um teste de legenda.", 5.0, 7.0)
        corte = CorteProposto(0, 0, 4.5, 8.5, 80, "teste", "teste", "original")
        destino = Path(_PASTA_TEMPORARIA.name) / "pasta com espaco" / "corte teste.mp4"
        cortar.gerar_corte(Path(__file__).parent / "exemplo_zoo.mp4", corte,
                           [Frase(0, 5.0, 7.0, "", palavras)], destino)
        saida = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of", "default=nw=1:nk=1", str(destino)],
            capture_output=True, text=True).stdout.split()
        self.assertEqual(saida[:2], ["1080", "1920"])
        self.assertAlmostEqual(float(saida[2]), 4.0, delta=0.15)


class TesteTraducao(unittest.TestCase):
    def setUp(self):
        banco.criar_tabelas()
        self.frases = [Frase(7, 10.0, 13.0, "Here we are.", []),
                       Frase(8, 13.5, 16.0, "It looks amazing!", [])]

    def test_traduz_mantendo_tempos_e_ids(self):
        from app.cerebro import traduzir
        cliente = ClienteFalso([resposta_falsa({"traducoes": [
            {"id": 7, "texto": "Chegamos."}, {"id": 8, "texto": "Parece incrível!"}]})])
        resultado = traduzir.traduzir_frases(self.frases, "en", usuario_id=1, cliente=cliente)
        self.assertEqual([(f.id, f.inicio, f.fim, f.texto) for f in resultado],
                         [(7, 10.0, 13.0, "Chegamos."), (8, 13.5, 16.0, "Parece incrível!")])
        self.assertEqual(resultado[1].palavras[0].inicio, 13.5)
        self.assertEqual(resultado[1].palavras[-1].fim, 16.0)
        self.assertEqual(cliente.chamadas[0]["model"], config.MODELO_RAPIDO)
        self.assertIn("inglês", cliente.chamadas[0]["system"])

    def test_traducao_faltando_gera_nova_tentativa(self):
        from app.cerebro import traduzir
        cliente = ClienteFalso([
            resposta_falsa({"traducoes": [{"id": 7, "texto": "Chegamos."}]}),
            resposta_falsa({"traducoes": [{"id": 7, "texto": "Chegamos."},
                                          {"id": 8, "texto": "Parece incrível!"}]}),
        ])
        resultado = traduzir.traduzir_frases(self.frases, "en", usuario_id=1, cliente=cliente)
        self.assertEqual(len(cliente.chamadas), 2)
        self.assertIn("Faltou", cliente.chamadas[1]["messages"][-1]["content"])
        self.assertEqual(len(resultado), 2)

    def test_validacao(self):
        from app.cerebro import traduzir
        self.assertEqual(traduzir.validar_traducoes(
            {"traducoes": [{"id": 1, "texto": "a"}]}, [1]), [])
        problemas = traduzir.validar_traducoes(
            {"traducoes": [{"id": 1, "texto": " "}, {"id": 1, "texto": "b"}, {"id": 9, "texto": "c"}]}, [1, 2])
        self.assertEqual(len(problemas), 4)


class TestePipelineCompleto(unittest.TestCase):
    """Link -> cortes, com download falso e IA simulada. Usa transcricao e ffmpeg de verdade."""
    VIDEO = Path(__file__).parent / "exemplo_zoo.mp4"

    @unittest.skipUnless(VIDEO.exists(), "video de exemplo ausente")
    def test_do_link_ao_corte_e_nao_reprocessa(self):
        from unittest import mock
        from app import pipeline
        from app.cerebro import escolher, traduzir
        from app.download import baixar

        link = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
        # No uso real o download grava dentro de dados/brutos; o teste imita isso.
        import shutil
        config.garantir_pastas()
        copia = config.PASTA_BRUTOS / "youtube_jNQXAC9IVRw.mp4"
        shutil.copy(self.VIDEO, copia)
        video = VideoBaixado("youtube", "jNQXAC9IVRw", link, "Me at the zoo", "jawed", 19.0, copia)
        cliente = ClienteFalso([
            resposta_falsa({"cortes": [corte(1, 1, nota=88, titulo="Elefantes de tromba longa")]}),
        ])

        cerebro_original = escolher.escolher_cortes

        def cerebro_com_cliente_falso(*args, **kwargs):
            return cerebro_original(*args, **kwargs, cliente=cliente)

        def traducao_falsa(frases, idioma, **kwargs):
            return [Frase(f.id, f.inicio, f.fim, "Tradução de teste.",
                          modulo_frases.repartir_tempo("Tradução de teste.", f.inicio, f.fim))
                    for f in frases]

        banco.salvar_config(1, "duracao_min_s", 5)           # o video de exemplo e curto
        self.addCleanup(banco.salvar_config, 1, "duracao_min_s", 20)

        with mock.patch.object(baixar, "baixar", return_value=video), \
             mock.patch.object(escolher, "escolher_cortes", side_effect=cerebro_com_cliente_falso), \
             mock.patch.object(traduzir, "traduzir_frases", side_effect=traducao_falsa) as traduz:
            arquivos = pipeline.processar_link(link)
            self.assertEqual(len(arquivos), 1)
            self.assertTrue(arquivos[0].exists())
            traduz.assert_called_once()                       # o video e em ingles

            registro = banco.buscar_video(1, "youtube", "jNQXAC9IVRw")
            self.assertEqual(registro["estado"], "pronto")
            self.assertEqual(registro["canal"], "jawed")      # a fonte ficou registrada
            cortes = banco.cortes_do_video(registro["id"])
            self.assertEqual(cortes[0]["estado"], "renderizado")
            self.assertEqual(cortes[0]["modo"], "narrado")

            self.assertEqual(pipeline.processar_link(link), [])   # segunda vez: nada a fazer


class TesteBanco(unittest.TestCase):
    def setUp(self):
        banco.criar_tabelas()

    def test_video_repetido_nao_duplica(self):
        primeiro = banco.registrar_video(1, "youtube", "abc123", "https://exemplo/abc123")
        segundo = banco.registrar_video(1, "youtube", "abc123", "https://exemplo/abc123")
        self.assertEqual(primeiro, segundo)

    def test_configuracao_padrao_e_alterada(self):
        self.assertEqual(banco.ler_config(1, "nota_minima_narracao"), 70)
        banco.salvar_config(1, "nota_minima_narracao", 80)
        self.assertEqual(banco.ler_config(1, "nota_minima_narracao"), 80)
        banco.salvar_config(1, "nota_minima_narracao", 70)

    def test_campo_desconhecido_e_recusado(self):
        video_id = banco.registrar_video(1, "youtube", "campo", "https://exemplo/campo")
        with self.assertRaises(KeyError):
            banco.atualizar_video(video_id, coluna_inventada="x")

    def test_transcricao_salva_e_carrega(self):
        original = transcricao_falsa(3)
        caminho = Path(_PASTA_TEMPORARIA.name) / "transcricoes" / "teste.json"
        original.salvar(caminho)
        self.assertEqual(Transcricao.carregar(caminho), original)


class TesteCerebro(unittest.TestCase):
    def setUp(self):
        banco.criar_tabelas()
        self.transcricao = transcricao_falsa()
        self.frases = {f.id: f for f in self.transcricao.frases}
        self.video = VideoBaixado("youtube", "xyz", "https://exemplo/xyz", "Trailer 3 analisado",
                                  "Canal Exemplo", 150.0, Path("nao_usado.mp4"))

    def validar(self, *cortes):
        return escolher.validar_cortes({"cortes": list(cortes)}, self.frases, 20, 75)

    def test_resposta_correta_passa(self):
        self.assertEqual(self.validar(corte(0, 5), corte(10, 16)), [])

    def test_frase_inexistente(self):
        self.assertIn("não existe", self.validar(corte(0, 999))[0])

    def test_duracao_fora_da_faixa(self):
        self.assertIn("menos que o mínimo", self.validar(corte(0, 1))[0])
        self.assertIn("mais que o máximo", self.validar(corte(0, 25))[0])

    def test_sobreposicao(self):
        self.assertTrue(any("sobrepõem" in p for p in self.validar(corte(0, 6), corte(5, 12))))

    def test_prompt_carrega_sem_variavel_sobrando(self):
        texto = ia.carregar_prompt("cerebro.md", cortes_min=3, cortes_max=5,
                                   duracao_min_s=20, duracao_max_s=75)
        self.assertIn("entre 20 e 75 segundos", texto)

    def test_resposta_invalida_gera_nova_tentativa(self):
        video_id = banco.registrar_video(1, "youtube", "xyz", "https://exemplo/xyz")
        cliente = ClienteFalso([
            resposta_falsa({"cortes": [corte(0, 999)]}),                      # errada
            resposta_falsa({"cortes": [corte(10, 16, nota=70), corte(0, 5, nota=91, modo="original")]}),
        ])
        cortes = escolher.escolher_cortes(self.transcricao, self.video, video_id=video_id,
                                          cliente=cliente)
        self.assertEqual(len(cliente.chamadas), 2)
        self.assertIn("não existe", cliente.chamadas[1]["messages"][-1]["content"])
        self.assertEqual([c.nota for c in cortes], [91, 70])           # do melhor para o pior
        self.assertEqual(cortes[0].modo, "original")
        self.assertEqual(cortes[0].inicio, 0.0)                         # nao comeca antes do video
        self.assertAlmostEqual(cortes[0].fim, 30.0, places=2)           # respiro ate a frase seguinte
        self.assertEqual(cliente.chamadas[0]["model"], config.MODELO_CEREBRO)
        self.assertGreater(banco.custo_do_video(video_id), 0)           # as 2 chamadas foram registradas

    def test_desiste_sem_quebrar_depois_de_tres_erros(self):
        cliente = ClienteFalso([resposta_falsa({"cortes": [corte(0, 999)]})] * 3)
        with self.assertRaises(ia.ErroIA):
            escolher.escolher_cortes(self.transcricao, self.video, cliente=cliente)

    def test_video_longo_e_dividido_em_partes(self):
        longas = [Frase(i, i * 5.0, i * 5.0 + 4.8, "x" * 1000) for i in range(400)]
        partes = escolher.dividir_em_partes(longas)
        self.assertEqual(len(partes), 3)
        self.assertEqual(sum(len(p) for p in partes), 400)


if __name__ == "__main__":
    unittest.main()
