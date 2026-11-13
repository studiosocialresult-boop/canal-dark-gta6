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
from unittest import mock  # noqa: E402
from app.contratos import (BlocoRoteiro, CorteProposto, Frase, Palavra, Roteiro,  # noqa: E402
                           Transcricao, VideoBaixado)
from app.narracao import roteiro as modulo_roteiro  # noqa: E402
from app.narracao import voz as modulo_voz  # noqa: E402
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

        banco.criar_tabelas()
        banco.salvar_config(1, "duracao_min_s", 5)           # o video de exemplo e curto
        self.addCleanup(banco.salvar_config, 1, "duracao_min_s", 20)

        with mock.patch.object(baixar, "baixar", return_value=video), \
             mock.patch.object(escolher, "escolher_cortes", side_effect=cerebro_com_cliente_falso), \
             mock.patch.object(traduzir, "traduzir_frases", side_effect=traducao_falsa) as traduz, \
             mock.patch.object(modulo_roteiro, "roteirizar_corte") as roteiriza:
            arquivos = pipeline.processar_link(link)
            roteiriza.assert_called_once()                    # nota 88: ganha roteiro
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


def texto_de(tamanho: int) -> str:
    """Um texto qualquer com exatamente o tamanho pedido."""
    return ("palavra " * (tamanho // 8 + 1))[:tamanho - 1].rstrip() + "."


class TesteRoteiro(unittest.TestCase):
    """Roteiro da narracao: validacao das ancoras e do tempo, com IA simulada."""

    def setUp(self):
        banco.criar_tabelas()
        self.transcricao = transcricao_falsa()          # frases de 5 s
        self.video = VideoBaixado("youtube", "xyz", "https://exemplo/xyz", "Trailer 3 analisado",
                                  "Canal Exemplo", 150.0, Path("nao_usado.mp4"))
        # Frases 2 a 9: de 10 s a 50 s do video, 40 s de corte.
        self.corte = CorteProposto(2, 9, 9.85, 50.1, 80, "Gancho e desfecho.", "Titulo", "narrado")
        self.gancho = CorteProposto(2, 9, 9.85, 50.1, 80, "Reacao.", "Titulo", "original")

    def blocos(self, *pares):
        return {"blocos": [{"frase_inicio": a, "texto": t} for a, t in pares]}

    def bom(self):
        return self.blocos((2, texto_de(130)), (4, texto_de(130)), (6, texto_de(130)), (8, texto_de(130)))

    def validar(self, dados):
        return modulo_roteiro.validar_narrado(dados, self.corte, self.transcricao)

    def test_roteiro_correto_passa(self):
        self.assertEqual(self.validar(self.bom()), [])

    def test_ancora_fora_do_corte(self):
        self.assertIn("não são frases do corte", self.validar(self.blocos((2, texto_de(130)), (15, "x")))[0])

    def test_primeiro_bloco_na_primeira_frase(self):
        dados = self.blocos((3, texto_de(130)), (5, texto_de(130)), (7, texto_de(130)))
        self.assertTrue(any("primeiro bloco" in p for p in self.validar(dados)))

    def test_ancoras_fora_de_ordem(self):
        dados = self.blocos((2, texto_de(130)), (6, texto_de(130)), (4, texto_de(130)))
        self.assertTrue(any("ordem crescente" in p for p in self.validar(dados)))

    def test_bloco_longo_demais(self):
        dados = self.bom()
        dados["blocos"][1]["texto"] = texto_de(200)      # janela de 10 s comporta 160
        problemas = self.validar(dados)
        self.assertEqual(len(problemas), 1)
        self.assertIn("no máximo 160", problemas[0])

    def test_bloco_curto_deixa_silencio(self):
        dados = self.bom()
        dados["blocos"][2]["texto"] = texto_de(30)       # 10 s de janela, 2 s de voz
        problemas = self.validar(dados)
        self.assertEqual(len(problemas), 1)
        self.assertIn("sem voz", problemas[0])

    def test_sinais_que_a_voz_nao_le(self):
        dados = self.bom()
        dados["blocos"][0]["texto"] = "[pausa] " + texto_de(120)
        self.assertTrue(any("sinais" in p for p in self.validar(dados)))

    def test_lista_vazia_no_modo_narrado(self):
        self.assertTrue(self.validar({"blocos": []}))

    def test_algarismo_pesa_mais(self):
        self.assertEqual(modulo_roteiro.peso_fala("209 gigas"), 9 + 3 * 4)

    def test_gancho(self):
        validar = lambda d: modulo_roteiro.validar_gancho(d, self.gancho)   # noqa: E731
        self.assertEqual(validar({"blocos": []}), [])                       # sem gancho e permitido
        self.assertEqual(validar(self.blocos((2, "O Speed descobre o lanche mais absurdo do jogo."))), [])
        self.assertTrue(validar(self.blocos((2, texto_de(110)))))           # longo demais
        self.assertTrue(validar(self.blocos((3, "Curto."))))                # ancora errada
        self.assertTrue(validar(self.blocos((2, "Um."), (4, "Dois."))))     # so cabe um

    def test_resposta_invalida_gera_nova_tentativa(self):
        ruim = self.bom()
        ruim["blocos"][0]["texto"] = texto_de(400)
        cliente = ClienteFalso([resposta_falsa(ruim), resposta_falsa(self.bom())])
        resultado = modulo_roteiro.escrever_roteiro(
            self.corte, self.transcricao, self.video, usuario_id=1, cliente=cliente)
        self.assertEqual(len(cliente.chamadas), 2)
        self.assertEqual([b.frase_inicio for b in resultado.blocos], [2, 4, 6, 8])
        self.assertIn("no máximo", cliente.chamadas[1]["messages"][-1]["content"])

    def test_prompts_carregam_e_mensagem_tem_contexto(self):
        for corte, resposta in ((self.corte, self.bom()), (self.gancho, {"blocos": []})):
            cliente = ClienteFalso([resposta_falsa(resposta)])
            modulo_roteiro.escrever_roteiro(corte, self.transcricao, self.video,
                                            usuario_id=1, cliente=cliente)
            chamada = cliente.chamadas[0]
            self.assertNotIn("{{", chamada["system"])
            self.assertIn("Fidelidade", chamada["system"])               # regras de escrita entraram
            mensagem = chamada["messages"][0]["content"]
            self.assertIn("frase numero 1 ", mensagem)                   # contexto antes do corte
            self.assertIn("[2] (começa em 0.2 s", mensagem)
            self.assertNotIn("[10]", mensagem)                           # nada depois do corte

    def test_roteiro_fica_guardado_no_banco(self):
        video_id = banco.registrar_video(1, "youtube", "roteiro01", "https://exemplo/roteiro01")
        banco.atualizar_video(video_id, titulo="Trailer", canal="Canal Exemplo")
        config.garantir_pastas()
        self.transcricao.salvar(config.PASTA_TRANSCRICOES / f"{video_id}.json")
        corte_id = banco.registrar_corte(1, video_id, self.corte)
        self.assertIsNone(banco.ler_narracao(corte_id))

        modulo_roteiro.roteirizar_corte(corte_id, cliente=ClienteFalso([resposta_falsa(self.bom())]))
        linha = banco.ler_narracao(corte_id)
        self.assertEqual(linha["estado"], "roteirizado")
        guardado = Roteiro.de_json(linha["roteiro"])
        self.assertEqual(guardado.modo, "narrado")
        self.assertEqual(len(guardado.blocos), 4)
        self.assertEqual(linha["caracteres"], len(guardado.texto))

    def test_pipeline_so_roteiriza_nota_alta_e_nao_quebra(self):
        from unittest import mock
        from app import pipeline
        video_id = banco.registrar_video(1, "youtube", "roteiro02", "https://exemplo/roteiro02")
        alto = banco.registrar_corte(1, video_id, self.corte)                      # nota 80
        baixo = CorteProposto(12, 16, 60.0, 85.0, 60, "Morno.", "Fraco", "narrado")
        banco.registrar_corte(1, video_id, baixo)
        with mock.patch.object(modulo_roteiro, "roteirizar_corte",
                               side_effect=ia.ErroIA("falhou")) as roteiriza:
            pipeline._etapa_roteiro(video_id, 1)                                   # nao levanta erro
        roteiriza.assert_called_once_with(alto)


def mp3_de_teste(segundos: float) -> bytes:
    """Um mp3 de verdade (um tom) com a duracao pedida, para testar sem a ElevenLabs."""
    import subprocess
    with tempfile.TemporaryDirectory() as pasta:
        arquivo = Path(pasta) / "tom.mp3"
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
                        "-i", f"sine=frequency=440:duration={segundos}", str(arquivo)], check=True)
        return arquivo.read_bytes()


def alinhamento_de(texto: str, segundos: float) -> dict:
    """Tempos por caractere inventados: as letras dividem o tempo por igual."""
    passo = segundos / len(texto)
    return {"characters": list(texto),
            "character_start_times_seconds": [i * passo for i in range(len(texto))],
            "character_end_times_seconds": [(i + 1) * passo for i in range(len(texto))]}


class TesteVoz(unittest.TestCase):
    def setUp(self):
        banco.criar_tabelas()
        self.transcricao = transcricao_falsa()          # frases de 5 s
        self.corte = CorteProposto(2, 9, 9.85, 50.1, 80, "Motivo.", "Titulo", "narrado")
        self.roteiro = Roteiro("narrado", [
            BlocoRoteiro(2, "Primeira parte da narracao."),
            BlocoRoteiro(4, "Segunda parte, que vem depois."),
            BlocoRoteiro(8, "Terceira e ultima."),
        ])

    def falsa(self, duracoes):
        """Troca a ElevenLabs por uma resposta de mentira, com a duracao de cada bloco."""
        fila = list(duracoes)

        def _pedir(texto, **_):
            segundos = fila.pop(0)
            return mp3_de_teste(segundos), alinhamento_de(texto, segundos)
        return mock.patch.object(modulo_voz, "_pedir_voz", side_effect=_pedir)

    def test_palavras_do_alinhamento(self):
        palavras = modulo_voz.palavras_do_alinhamento("Oi, GTA 6!", alinhamento_de("Oi, GTA 6!", 5.0))
        self.assertEqual([p.texto for p in palavras], ["Oi,", "GTA", "6!"])
        self.assertAlmostEqual(palavras[0].inicio, 0.0)
        self.assertAlmostEqual(palavras[-1].fim, 5.0)
        self.assertLess(palavras[0].fim, palavras[1].inicio + 0.01)

    def test_blocos_comecam_na_ancora(self):
        self.assertEqual(modulo_voz.posicionar([3.0, 3.0], [0.2, 10.2]), [0.2, 10.2])

    def test_bloco_que_estoura_empurra_o_proximo(self):
        inicios = modulo_voz.posicionar([8.0, 3.0], [0.0, 5.0])      # o primeiro termina em 8 s
        self.assertAlmostEqual(inicios[1], 8.0 + config.PAUSA_ENTRE_BLOCOS_S)

    def test_gera_faixa_e_tempos(self):
        pasta = config.PASTA_NARRACOES / "teste_voz"
        with self.falsa([3.0, 4.0, 2.0]):
            voz = modulo_voz.gerar_voz(self.roteiro, self.corte.inicio, self.transcricao, pasta)
        # ancoras: frase 2 = 0.2 s, frase 4 = 10.2 s, frase 8 = 30.1 s
        self.assertEqual([round(b.inicio, 1) for b in voz.blocos], [0.2, 10.2, 30.1])
        self.assertAlmostEqual(voz.duracao_s, 32.1, delta=0.1)
        self.assertTrue((pasta / "narracao.mp3").exists())
        self.assertAlmostEqual(modulo_voz._duracao_audio(pasta / "narracao.mp3"), 32.1, delta=0.4)
        # as palavras do segundo bloco comecam depois do inicio do bloco
        self.assertGreaterEqual(voz.blocos[1].palavras[0].inicio, 10.1)
        # salva e carrega igual
        recarregada = modulo_voz.Voz.carregar(pasta)
        self.assertEqual(len(recarregada.palavras), len(voz.palavras))
        self.assertEqual(recarregada.blocos[2].texto, "Terceira e ultima.")

    def test_gancho_comeca_no_zero(self):
        gancho = Roteiro("original", [BlocoRoteiro(2, "Um gancho curto.")])
        pasta = config.PASTA_NARRACOES / "teste_gancho"
        with self.falsa([2.5]):
            voz = modulo_voz.gerar_voz(gancho, self.corte.inicio, self.transcricao, pasta)
        self.assertEqual(voz.blocos[0].inicio, 0.0)
        self.assertAlmostEqual(voz.duracao_s, 2.5, delta=0.1)

    def test_corte_sem_roteiro_e_recusado(self):
        with self.assertRaises(modulo_voz.ErroVoz):
            modulo_voz.gerar_voz(Roteiro("narrado", []), 0.0, self.transcricao,
                                 config.PASTA_NARRACOES / "vazio")

    def test_narrar_corte_guarda_estado_e_custo(self):
        video_id = banco.registrar_video(1, "youtube", "voz01", "https://exemplo/voz01")
        config.garantir_pastas()
        self.transcricao.salvar(config.PASTA_TRANSCRICOES / f"{video_id}.json")
        corte_id = banco.registrar_corte(1, video_id, self.corte)
        banco.salvar_roteiro(1, corte_id, self.roteiro)
        with self.falsa([3.0, 4.0, 2.0]):
            modulo_voz.narrar_corte(corte_id)
        linha = banco.ler_narracao(corte_id)
        self.assertEqual(linha["estado"], "narrado")
        self.assertTrue(config.caminho_absoluto(linha["caminho_audio"]).exists())
        self.assertGreater(banco.custo_do_video(video_id), 0)

    def test_erro_de_plano_vira_mensagem_clara(self):
        resposta = SimpleNamespace(ok=False, status_code=402, text="paid_plan_required")
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "x"}), \
             mock.patch.object(modulo_voz.requests, "post", return_value=resposta):
            with self.assertRaises(modulo_voz.ErroVoz) as erro:
                modulo_voz._pedir_voz("texto")
        self.assertIn("plano pago", str(erro.exception))

    def test_narrar_corte_falho_fica_marcado(self):
        video_id = banco.registrar_video(1, "youtube", "voz02", "https://exemplo/voz02")
        config.garantir_pastas()
        self.transcricao.salvar(config.PASTA_TRANSCRICOES / f"{video_id}.json")
        corte_id = banco.registrar_corte(1, video_id, self.corte)
        banco.salvar_roteiro(1, corte_id, self.roteiro)
        with mock.patch.object(modulo_voz, "_pedir_voz", side_effect=modulo_voz.ErroVoz("sem caracteres")):
            with self.assertRaises(modulo_voz.ErroVoz):
                modulo_voz.narrar_corte(corte_id)
        self.assertEqual(banco.ler_narracao(corte_id)["estado"], "falhou")


class TesteMixagem(unittest.TestCase):
    """Mixagem da narracao no video, com ffmpeg de verdade e a voz de mentira."""
    VIDEO = Path(__file__).parent / "exemplo_zoo.mp4"      # 19 s

    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="mix_", dir=config.PASTA_DADOS))
        (self.pasta / "narracao.mp3").write_bytes(mp3_de_teste(6.0))

    def voz(self, modo, fim):
        palavras = [Palavra("um", 0.2, 0.6), Palavra("dois", 0.7, 1.2), Palavra("tres.", 1.3, fim)]
        return modulo_voz.Voz(modo, fim, [modulo_voz.BlocoVoz(2, "um dois tres.", 0.0, fim, palavras)])

    def duracao(self, arquivo):
        return modulo_voz._duracao_audio(arquivo)

    def streams(self, arquivo):
        import subprocess
        saida = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                                "-of", "csv=p=0", str(arquivo)], capture_output=True, text=True).stdout
        return sorted(saida.split())

    @unittest.skipUnless(VIDEO.exists(), "video de exemplo ausente")
    def test_narrado_mantem_a_duracao_do_corte(self):
        from app.edicao import cortar
        corte = CorteProposto(0, 0, 4.5, 12.5, 80, "m", "t", "narrado")      # 8 s
        saida = cortar.gerar_corte(self.VIDEO, corte, [], self.pasta / "narrado.mp4",
                                   voz=self.voz("narrado", 5.0), arquivo_voz=self.pasta / "narracao.mp3")
        self.assertAlmostEqual(self.duracao(saida), 8.0, delta=0.3)
        self.assertEqual(self.streams(saida), ["audio", "video"])

    @unittest.skipUnless(VIDEO.exists(), "video de exemplo ausente")
    def test_narracao_que_passa_do_corte_segura_a_imagem(self):
        from app.edicao import cortar
        corte = CorteProposto(0, 0, 4.5, 7.5, 80, "m", "t", "narrado")       # 3 s, voz de 5 s
        saida = cortar.gerar_corte(self.VIDEO, corte, [], self.pasta / "longa.mp4",
                                   voz=self.voz("narrado", 5.0), arquivo_voz=self.pasta / "narracao.mp3")
        self.assertAlmostEqual(self.duracao(saida), 5.0 + cortar.CAUDA_APOS_NARRACAO_S, delta=0.3)

    @unittest.skipUnless(VIDEO.exists(), "video de exemplo ausente")
    def test_gancho_vem_antes_da_fala_original(self):
        from app.edicao import cortar
        corte = CorteProposto(0, 0, 8.0, 14.0, 80, "m", "t", "original")     # 6 s de fala original
        saida = cortar.gerar_corte(self.VIDEO, corte, [], self.pasta / "gancho.mp4",
                                   voz=self.voz("original", 3.0), arquivo_voz=self.pasta / "narracao.mp3")
        esperado = 3.0 + cortar.PAUSA_APOS_GANCHO_S + 6.0
        self.assertAlmostEqual(self.duracao(saida), esperado, delta=0.3)

    @unittest.skipUnless(VIDEO.exists(), "video de exemplo ausente")
    def test_gancho_no_inicio_do_video_segura_o_primeiro_quadro(self):
        from app.edicao import cortar
        corte = CorteProposto(0, 0, 1.0, 7.0, 80, "m", "t", "original")      # so 1 s antes do corte
        saida = cortar.gerar_corte(self.VIDEO, corte, [], self.pasta / "inicio.mp4",
                                   voz=self.voz("original", 3.0), arquivo_voz=self.pasta / "narracao.mp3")
        esperado = 3.0 + cortar.PAUSA_APOS_GANCHO_S + 6.0
        self.assertAlmostEqual(self.duracao(saida), esperado, delta=0.3)

    def test_legenda_da_narracao_usa_o_tempo_do_video_original(self):
        from app.edicao import cortar
        voz = self.voz("narrado", 2.0)
        frases = cortar._frases_da_voz(voz, origem=10.0)
        ass = cortar.gerar_ass(frases, 10.0, 8.0)
        self.assertIn("0:00:00.20", ass)                  # a primeira palavra entra em 0,2 s do corte
        self.assertIn("UM", ass)

    def test_pipeline_gera_voz_so_de_quem_tem_roteiro(self):
        from app import pipeline
        video_id = banco.registrar_video(1, "youtube", "mix01", "https://exemplo/mix01")
        com = banco.registrar_corte(1, video_id, CorteProposto(2, 9, 9.85, 50.1, 80, "m", "t", "narrado"))
        banco.registrar_corte(1, video_id, CorteProposto(12, 16, 60.0, 85.0, 60, "m", "t", "narrado"))
        banco.salvar_roteiro(1, com, Roteiro("narrado", [BlocoRoteiro(2, "Texto.")]))
        with mock.patch.object(modulo_voz, "narrar_corte", side_effect=modulo_voz.ErroVoz("sem saldo")) as narra:
            pipeline._etapa_voz(video_id)                 # nao levanta erro
        narra.assert_called_once_with(com)


class TestePainel(unittest.TestCase):
    """Painel: paginas, API, fila de trabalho e seguranca dos arquivos."""
    VIDEO = Path(__file__).parent / "exemplo_zoo.mp4"

    @classmethod
    def setUpClass(cls):
        os.environ["CANAL_SEM_TRABALHADOR"] = "1"       # o teste chama a fila na mao
        from fastapi.testclient import TestClient
        from app.painel import servidor
        cls.servidor = servidor
        cls.cliente = TestClient(servidor.criar_app())

    def setUp(self):
        banco.criar_tabelas()
        self.video_id = banco.registrar_video(1, "youtube", "painel01a12", "https://www.youtube.com/watch?v=painel01a12")
        banco.atualizar_video(self.video_id, titulo="Video de teste", canal="Canal Teste")
        self.corte_id = banco.registrar_corte(
            1, self.video_id, CorteProposto(2, 9, 10.0, 50.0, 80, "Motivo do teste.", "Titulo do teste", "narrado"))
        self.addCleanup(self._limpar)

    def _limpar(self):
        import sqlite3
        with sqlite3.connect(config.ARQUIVO_BANCO) as conexao:
            conexao.execute("DELETE FROM fila")
            conexao.execute("DELETE FROM narracoes")
            conexao.execute("DELETE FROM cortes WHERE video_id = ?", (self.video_id,))
            conexao.execute("DELETE FROM videos WHERE id = ?", (self.video_id,))

    def test_paginas_existem(self):
        for caminho in ("/cortes", "/configuracoes", "/hoje", "/templates", "/contas"):
            self.assertEqual(self.cliente.get(caminho).status_code, 200, caminho)
        self.assertEqual(self.cliente.get("/nao-existe").status_code, 404)
        self.assertEqual(self.cliente.get("/", follow_redirects=False).headers["location"], "/cortes")

    def test_lista_de_cortes_traz_fonte_e_numeros(self):
        dados = self.cliente.get("/api/cortes").json()
        corte = next(c for c in dados["cortes"] if c["id"] == self.corte_id)
        self.assertEqual(corte["canal"], "Canal Teste")
        self.assertEqual(corte["modo"], "narrado")
        self.assertIsNone(corte["narracao"])
        self.assertGreaterEqual(dados["numeros"]["revisar"], 0)

    def test_aprovar_descartar_e_validar(self):
        post = lambda c, **corpo: self.cliente.post(f"/api/cortes/{c}/estado", json=corpo)   # noqa: E731
        self.assertEqual(post(self.corte_id, estado="aprovado").status_code, 200)
        self.assertEqual(banco.ler_corte(self.corte_id)["estado"], "aprovado")
        self.assertEqual(post(self.corte_id, estado="postado").status_code, 400)       # estado que o dono nao escolhe
        self.assertEqual(post(999999, estado="aprovado").status_code, 404)
        em_massa = self.cliente.post("/api/cortes/estado", json={"ids": [self.corte_id], "estado": "descartado"})
        self.assertEqual(em_massa.json()["total"], 1)
        self.assertEqual(banco.ler_corte(self.corte_id)["estado"], "descartado")

    def test_link_novo_entra_na_fila_e_repetido_nao(self):
        link = "https://www.youtube.com/watch?v=fila0000001"
        self.assertEqual(self.cliente.post("/api/links", json={"url": link}).status_code, 200)
        repetido = self.cliente.post("/api/links", json={"url": link})
        self.assertEqual(repetido.status_code, 409)
        self.assertEqual(self.cliente.get("/api/fila").json()["ativos"], 1)

    def test_link_invalido_ou_ja_processado(self):
        for url in ("", "banana", "https://exemplo.com/x"):
            resposta = self.cliente.post("/api/links", json={"url": url})
            self.assertEqual(resposta.status_code, 400, url)
            self.assertIn("YouTube", resposta.json()["erro"])
        banco.atualizar_video(self.video_id, estado="pronto")
        resposta = self.cliente.post("/api/links", json={"url": "https://www.youtube.com/watch?v=painel01a12"})
        self.assertEqual(resposta.status_code, 409)

    def test_narrar_exige_chave_e_nao_duplica(self):
        banco.atualizar_corte(self.corte_id, estado="renderizado", caminho_arquivo="cortes/1/x.mp4")
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": ""}):
            self.assertEqual(self.cliente.post(f"/api/cortes/{self.corte_id}/narrar").status_code, 400)
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "chave"}):
            self.assertEqual(self.cliente.post(f"/api/cortes/{self.corte_id}/narrar").status_code, 200)
            self.assertEqual(self.cliente.post(f"/api/cortes/{self.corte_id}/narrar").status_code, 409)

    def test_configuracoes_validam_limites(self):
        put = lambda **corpo: self.cliente.put("/api/configuracoes", json=corpo)   # noqa: E731
        self.assertEqual(put(nota_minima_narracao=65).status_code, 200)
        self.assertEqual(banco.ler_config(1, "nota_minima_narracao"), 65)
        self.addCleanup(banco.salvar_config, 1, "nota_minima_narracao", 70)
        self.assertEqual(put(nota_minima_narracao=500).status_code, 400)
        self.assertEqual(put(nota_minima_narracao="abc").status_code, 400)
        self.assertEqual(put(chave_inventada=1).status_code, 400)
        self.assertEqual(put(cortes_min=9, cortes_max=2).status_code, 400)
        self.assertEqual(banco.ler_config(1, "cortes_min"), 3)             # nada foi salvo pela metade

    def test_sistema_nao_vaza_chaves(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-segredo-123"}):
            texto = self.cliente.get("/api/configuracoes").text
        self.assertNotIn("segredo", texto)

    @unittest.skipUnless(VIDEO.exists(), "video de exemplo ausente")
    def test_midia_miniatura_e_acesso_restrito(self):
        import shutil
        pasta = config.PASTA_CORTES / "painel"
        pasta.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.VIDEO, pasta / "corte_teste.mp4")
        banco.atualizar_corte(self.corte_id, estado="renderizado",
                              caminho_arquivo=config.caminho_relativo(pasta / "corte_teste.mp4"))
        self.assertEqual(self.cliente.get("/midia/cortes/painel/corte_teste.mp4").status_code, 200)
        miniatura = self.cliente.get(f"/miniatura/{self.corte_id}.jpg")
        self.assertEqual(miniatura.status_code, 200)
        self.assertEqual(miniatura.headers["content-type"], "image/jpeg")
        # so a pasta dos cortes e servida: nada de banco, chaves ou outras pastas
        for tentativa in ("/midia/canal.db", "/midia/%2e%2e/canal.db", "/midia/brutos/youtube_x.mp4",
                          "/midia/cortes/../canal.db"):
            self.assertEqual(self.cliente.get(tentativa).status_code, 404, tentativa)

    # ---------- trabalhador da fila ----------

    def test_fila_processa_link_e_resume(self):
        from app.painel import fila
        link = "https://www.youtube.com/watch?v=painel01a12"
        banco.atualizar_video(self.video_id, estado="analisado")
        item = banco.enfileirar(1, "link", link, link)
        with mock.patch.object(fila.pipeline, "processar_link") as processar:
            self.assertTrue(fila.processar_proximo())
            processar.assert_called_once()
            self.assertIn("progresso", processar.call_args.kwargs)
        linha = [i for i in banco.listar_fila(1) if i["id"] == item][0]
        self.assertEqual(linha["estado"], "pronto")
        self.assertEqual(linha["resultado"], "1 corte para revisar")
        self.assertFalse(fila.processar_proximo())                     # fila vazia

    def test_fila_marca_falha_sem_travar_os_proximos(self):
        from app.painel import fila
        ruim = banco.enfileirar(1, "narrar", str(self.corte_id), "ruim")
        bom = banco.enfileirar(1, "narrar", str(self.corte_id), "bom")
        efeitos = [RuntimeError("a ElevenLabs recusou"), Path("ok.mp4")]
        with mock.patch.object(fila.pipeline, "narrar_e_renderizar", side_effect=efeitos):
            fila.processar_proximo()
            fila.processar_proximo()
        estados = {i["id"]: (i["estado"], i["resultado"]) for i in banco.listar_fila(1)}
        self.assertEqual(estados[ruim], ("falhou", "a ElevenLabs recusou"))
        self.assertEqual(estados[bom][0], "pronto")

    def test_video_que_falhou_vira_item_falho_com_a_causa(self):
        from app.painel import fila
        banco.atualizar_video(self.video_id, estado="falhou", erro="O video tem restricao de idade.")
        banco.enfileirar(1, "link", "https://www.youtube.com/watch?v=painel01a12", "x")
        with mock.patch.object(fila.pipeline, "processar_link"):
            fila.processar_proximo()
        item = banco.listar_fila(1)[0]
        self.assertEqual(item["estado"], "falhou")
        self.assertIn("restricao de idade", item["resultado"])

    def test_painel_religado_retoma_o_que_estava_no_meio(self):
        item = banco.enfileirar(1, "link", "https://www.youtube.com/watch?v=retoma000001", "x")
        banco.atualizar_fila(item, estado="processando", progresso="Transcrevendo")
        banco.retomar_fila()
        linha = [i for i in banco.listar_fila(1) if i["id"] == item][0]
        self.assertEqual(linha["estado"], "aguardando")


class TesteTemplates(unittest.TestCase):
    """Templates: cartao, dados, frases (IA simulada), API do painel e lote de videos."""
    VIDEO = Path(__file__).parent / "exemplo_zoo.mp4"

    @classmethod
    def setUpClass(cls):
        os.environ["CANAL_SEM_TRABALHADOR"] = "1"
        from fastapi.testclient import TestClient
        from app.multiplicador import cartao, frases, lote, renderizar, repositorio
        from app.painel import servidor
        cls.cartao, cls.frases, cls.lote, cls.renderizar, cls.repo = cartao, frases, lote, renderizar, repositorio
        cls.cliente = TestClient(servidor.criar_app())

    def setUp(self):
        banco.criar_tabelas()
        self.ids = []
        self.addCleanup(lambda: [self.repo.excluir_template(i) for i in self.ids])

    def novo(self, layout="post"):
        template_id = self.repo.criar_template(1, layout, "Teste")
        self.ids.append(template_id)
        return template_id

    def png(self, lado=64):
        import io
        from PIL import Image
        arquivo = io.BytesIO()
        Image.new("RGB", (lado, lado), (200, 30, 90)).save(arquivo, "PNG")
        return arquivo.getvalue()

    # ---------- cartao ----------

    def test_cartao_tem_zonas_certas_em_cada_layout(self):
        for layout, zonas in (("post", {"video"}), ("meme", {"video"}), ("viral", {"video", "video2"})):
            imagem, achadas = self.cartao.compor(layout, {}, "Uma frase de teste para o cartao")
            self.assertEqual(imagem.size, (1080, 1920))
            self.assertEqual(set(achadas), zonas, layout)
            x, y, w, h = achadas["video"]
            self.assertEqual(imagem.getpixel((x + w // 2, y + h // 2))[3], 0, "zona do video fica transparente")
            self.assertTrue(0 <= y and y + h <= 1920 and h > 400, layout)

    def test_frase_longa_encolhe_e_nao_corta(self):
        longa = "Tudo que voce precisa saber sobre o GTA 6 em uma unica pagina feita para os fas mais exigentes " * 2
        curta = "GTA 6"
        _, zonas_longa = self.cartao.compor("meme", {}, longa)
        _, zonas_curta = self.cartao.compor("meme", {}, curta)
        self.assertGreaterEqual(zonas_longa["video"][1], zonas_curta["video"][1])      # faixa maior para frase maior
        letra, linhas, _ = self.cartao.ajustar_texto(longa, 64, 950, 620, 1.18)
        self.assertLessEqual(letra.size, 64)
        self.assertEqual(" ".join(linhas), " ".join(longa.split()))                    # nenhuma palavra perdida

    def test_ultima_linha_nao_fica_com_uma_palavra_so(self):
        letra = self.cartao.fonte(64, True)
        linhas = self.cartao.quebrar_equilibrado("A Rockstar anunciou um festival ao vivo em Miami para celebrar o GTA 6", letra, 900)
        self.assertGreaterEqual(len(linhas[-1].split()), 2)

    def test_emoji_e_removido_e_foto_invalida_nao_quebra(self):
        self.assertEqual(self.cartao.limpar_texto("GTA 6 \U0001F525 chegou"), "GTA 6 chegou")
        imagem, _ = self.cartao.compor("post", {"perfil": {"nome": "Teste"}}, "ok", avatar=Path("nao_existe.png"))
        self.assertEqual(imagem.size, (1080, 1920))

    # ---------- dados ----------

    def test_config_so_guarda_o_que_mudou_e_mescla(self):
        template_id = self.novo()
        self.repo.atualizar_template(template_id, config_nova={"perfil": {"nome": "Minha Pagina"}})
        self.repo.atualizar_template(template_id, config_nova={"perfil": {"handle": "minhapagina"}})
        salva = self.repo.ler_template(template_id)["config"]
        self.assertEqual(salva, {"perfil": {"nome": "Minha Pagina", "handle": "minhapagina"}})
        completa = self.renderizar.modelos.config_completa(salva)
        self.assertEqual(completa["perfil"]["tema"], "escuro")                      # padrao preservado

    def test_cruzamento_cria_n_x_m_sem_duplicar(self):
        template_id = self.novo()
        for i in range(3):
            self.repo.adicionar_arquivo(template_id, f"templates/x/v{i}.mp4", f"v{i}")
        self.repo.adicionar_frases(template_id, ["Frase um", "Frase dois", "frase DOIS", "  ", "Frase tres"])
        self.assertEqual(len(self.repo.listar_frases(template_id)), 3)             # vazia e repetida ficam de fora
        self.assertEqual(self.repo.gerar_saidas(template_id), (9, 0))
        self.assertEqual(self.repo.gerar_saidas(template_id), (0, 9))               # nada em dobro
        midia = self.repo.listar_midias(template_id)[0]
        self.repo.atualizar_midia(midia["id"], selecionada=False)
        self.assertEqual(len(self.repo.combinacoes(template_id)[0]) * 3, 6)
        self.assertEqual(self.repo.contagem_saidas(template_id)["total"], 9)

    def test_saida_que_falhou_volta_para_a_fila(self):
        template_id = self.novo()
        self.repo.adicionar_arquivo(template_id, "templates/x/v.mp4", "v")
        self.repo.adicionar_frases(template_id, ["Frase"])
        self.repo.gerar_saidas(template_id)
        saida = self.repo.proxima_saida(template_id)
        self.repo.atualizar_saida(saida["id"], estado="falhou", erro="x")
        self.assertEqual(self.repo.gerar_saidas(template_id), (0, 1))
        self.assertEqual(self.repo.ler_saida(saida["id"])["estado"], "aguardando")

    def test_midia_valida_ajustes(self):
        template_id = self.novo()
        midia = self.repo.adicionar_arquivo(template_id, "templates/x/v.mp4", "v")
        self.repo.atualizar_midia(midia, zoom=9, pos_x=-5)
        guardada = self.repo.ler_midia(midia)
        self.assertEqual((guardada["zoom"], guardada["pos_x"]), (4.0, 0.0))        # limitado
        with self.assertRaises(ValueError):
            self.repo.atualizar_midia(midia, ajuste="esticar")
        with self.assertRaises(KeyError):
            self.repo.atualizar_midia(midia, origem="corte")

    # ---------- frases com IA ----------

    def test_frases_da_ia_sao_conferidas(self):
        base = "A pagina perfeita para quem quer saber tudo do GTA 6"
        boas = {"frases": ["Quer saber tudo do GTA 6?", "Tudo do GTA 6 em um lugar"]}
        self.assertEqual(self.frases.validar_frases(boas, base, 2), [])
        self.assertTrue(self.frases.validar_frases(boas, base, 3))                              # faltou uma
        self.assertTrue(self.frases.validar_frases({"frases": ["Igual", "igual!"]}, base, 2))   # repetidas
        self.assertTrue(self.frases.validar_frases({"frases": ["x" * 200, "ok"]}, base, 2))      # longa
        self.assertTrue(self.frases.validar_frases({"frases": ["Olha isso \U0001F525", "ok"]}, base, 2))
        self.assertTrue(self.frases.validar_frases({"frases": [base, "outra"]}, base, 2))        # copia da base

    def test_gerar_variacoes_tenta_de_novo_se_vier_errado(self):
        base = "A pagina perfeita para quem quer saber tudo do GTA 6"
        cliente = ClienteFalso([resposta_falsa({"frases": ["So uma"]}),
                                resposta_falsa({"frases": ["Quer saber tudo do GTA 6?", "Tudo do GTA 6 em um lugar"]})])
        resultado = self.frases.gerar_variacoes(base, 2, usuario_id=1, cliente=cliente)
        self.assertEqual(len(resultado), 2)
        self.assertEqual(len(cliente.chamadas), 2)
        self.assertNotIn("{{", cliente.chamadas[0]["system"])
        with self.assertRaises(ValueError):
            self.frases.gerar_variacoes("curta", 3, usuario_id=1)
        with self.assertRaises(ValueError):
            self.frases.gerar_variacoes(base, 99, usuario_id=1)

    # ---------- API ----------

    def test_api_cria_e_valida_configuracao(self):
        r = self.cliente.post("/api/templates", json={"layout": "meme"})
        self.assertEqual(r.status_code, 200)
        template_id = r.json()["id"]
        self.ids.append(template_id)
        self.assertEqual(self.cliente.post("/api/templates", json={"layout": "inexistente"}).status_code, 400)
        put = lambda **cfg: self.cliente.put(f"/api/templates/{template_id}", json={"config": cfg})   # noqa: E731
        self.assertEqual(put(texto={"tamanho": 80}).status_code, 200)
        self.assertEqual(put(texto={"tamanho": 9999}).status_code, 400)
        self.assertEqual(put(texto={"cor": "vermelho"}).status_code, 400)
        self.assertEqual(put(perfil={"tema": "neon"}).status_code, 400)
        self.assertEqual(put(perfil={"avatar": "../../.env"}).status_code, 400)             # so pelo envio de imagem
        self.assertEqual(put(segredo={"a": 1}).status_code, 400)
        self.assertEqual(self.cliente.get("/api/templates/999999").status_code, 404)
        pagina = self.cliente.get(f"/templates/{template_id}")
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual(self.cliente.get("/templates").status_code, 200)

    def test_api_avatar_so_aceita_imagem(self):
        template_id = self.novo()
        ruim = self.cliente.post(f"/api/templates/{template_id}/avatar?nome=foto.png", content=b"isto nao e uma imagem")
        self.assertEqual(ruim.status_code, 400)
        errada = self.cliente.post(f"/api/templates/{template_id}/avatar?nome=script.exe", content=self.png())
        self.assertEqual(errada.status_code, 400)
        boa = self.cliente.post(f"/api/templates/{template_id}/avatar?nome=foto.png", content=self.png())
        self.assertEqual(boa.status_code, 200)
        dados = self.cliente.get(f"/api/templates/{template_id}").json()
        self.assertIsNotNone(dados["avatar_url"])
        self.assertEqual(self.cliente.get(f"/api/templates/{template_id}/avatar").status_code, 200)
        self.assertEqual(self.cliente.delete(f"/api/templates/{template_id}/avatar").status_code, 200)

    def test_api_frases_e_perfis_salvos(self):
        template_id = self.novo()
        r = self.cliente.post(f"/api/templates/{template_id}/frases", json={"textos": ["Primeira", "Segunda", "primeira"]})
        self.assertEqual(r.json()["novas"], 2)
        self.assertEqual(r.json()["resumo"]["frases"], 2)
        self.assertEqual(self.cliente.post(f"/api/templates/{template_id}/frases", json={"textos": ["x" * 300]}).status_code, 400)
        frase = self.repo.listar_frases(template_id)[0]
        self.cliente.put(f"/api/templates/{template_id}/frases/{frase['id']}", json={"selecionada": False})
        self.assertEqual(self.cliente.get(f"/api/templates/{template_id}").json()["resumo"]["frases"], 1)
        outro = self.novo()
        self.assertEqual(self.cliente.delete(f"/api/templates/{template_id}/frases/{self.repo.listar_frases(outro)[0]['id']}").status_code, 404) \
            if self.repo.listar_frases(outro) else None
        # perfil salvo
        self.cliente.put(f"/api/templates/{template_id}", json={"config": {"perfil": {"nome": "Pagina Salva", "handle": "salva"}}})
        salvo = self.cliente.post(f"/api/templates/{template_id}/perfil-salvo", json={"rotulo": "Minha"}).json()["id"]
        self.addCleanup(self.repo.excluir_perfil, salvo)
        self.cliente.put(f"/api/templates/{outro}", json={"config": {"perfil": {"nome": "Outro"}}})
        self.assertEqual(self.cliente.post(f"/api/templates/{outro}/perfil-salvo/{salvo}").status_code, 200)
        self.assertEqual(self.repo.ler_template(outro)["config"]["perfil"]["nome"], "Pagina Salva")

    @unittest.skipUnless(VIDEO.exists(), "video de exemplo ausente")
    def test_upload_previa_e_lote_de_verdade(self):
        template_id = self.novo("post")
        self.assertEqual(self.cliente.post(f"/api/templates/{template_id}/upload?nome=virus.exe", content=b"x").status_code, 400)
        self.assertEqual(self.cliente.post(f"/api/templates/{template_id}/upload?nome=fake.mp4", content=b"nao sou video").status_code, 400)
        enviado = self.cliente.post(f"/api/templates/{template_id}/upload?nome=zoo.mp4", content=self.VIDEO.read_bytes())
        self.assertEqual(enviado.status_code, 200)
        self.cliente.post(f"/api/templates/{template_id}/frases", json={"textos": ["Frase um do lote", "Frase dois do lote"]})

        previa = self.cliente.get(f"/api/templates/{template_id}/previa.jpg")
        self.assertEqual(previa.status_code, 200)
        self.assertEqual(previa.headers["content-type"], "image/jpeg")
        miniatura = self.cliente.get(f"/api/templates/{template_id}/midias/{enviado.json()['id']}/miniatura.jpg")
        self.assertEqual(miniatura.status_code, 200)

        self.assertEqual(self.cliente.get(f"/api/templates/{template_id}").json()["resumo"]["total"], 2)
        gerar = self.cliente.post(f"/api/templates/{template_id}/gerar")
        self.assertEqual(gerar.json()["novas"], 2)
        self.assertEqual(self.cliente.post(f"/api/templates/{template_id}/gerar").status_code, 409)     # ja na fila

        from app.painel import fila
        self.assertTrue(fila.processar_proximo())                                  # a fila gera os 2 videos
        saidas = self.cliente.get(f"/api/templates/{template_id}/saidas").json()
        self.assertEqual(saidas["contagem"]["pronto"], 2, saidas)
        primeira = saidas["saidas"][0]
        baixado = self.cliente.get(primeira["url"] + "?baixar=1")
        self.assertEqual(baixado.status_code, 200)
        self.assertIn("attachment", baixado.headers.get("content-disposition", ""))
        arquivo = config.caminho_absoluto(self.repo.ler_saida(primeira["id"])["arquivo"])
        self.assertAlmostEqual(self.renderizar.duracao_do_arquivo(arquivo), 19.0, delta=1.0)
        self.assertEqual(self.cliente.get(f"/api/templates/{template_id}/saidas/99999.mp4").status_code, 404)
        self.assertEqual(self.cliente.delete(f"/api/templates/{template_id}").status_code, 200)   # apagar leva os arquivos
        self.assertFalse(arquivo.exists())
        self.ids.remove(template_id)

    def test_um_video_que_falha_nao_derruba_o_lote(self):
        template_id = self.novo()
        for i in range(2):
            self.repo.adicionar_arquivo(template_id, f"templates/x/v{i}.mp4", f"v{i}")
        self.repo.adicionar_frases(template_id, ["Frase"])
        self.repo.gerar_saidas(template_id)
        efeitos = [self.renderizar.ErroRender("video corrompido"), Path("ok.mp4")]
        with mock.patch.object(self.lote.renderizar, "renderizar_saida", side_effect=efeitos) as renderiza:
            # o mock nao atualiza o banco; marcamos como o render de verdade faria
            def faz(saida_id):
                efeito = efeitos.pop(0)
                self.repo.atualizar_saida(saida_id, estado="falhou" if isinstance(efeito, Exception) else "pronto")
                if isinstance(efeito, Exception):
                    raise efeito
            renderiza.side_effect = faz
            resumo = self.lote.processar_template(template_id)
        self.assertEqual(renderiza.call_count, 2)
        self.assertIn("1 prontos, 1 com falha", resumo)

    def test_apagar_template_em_geracao_e_recusado(self):
        template_id = self.novo()
        banco.enfileirar(1, "lote", str(template_id), "x")
        self.assertEqual(self.cliente.delete(f"/api/templates/{template_id}").status_code, 409)
        self.addCleanup(lambda: __import__("sqlite3").connect(config.ARQUIVO_BANCO).execute("DELETE FROM fila").connection.commit())


class TesteMigracaoDoBanco(unittest.TestCase):
    """O banco de quem ja usa o painel e refeito sem perder dados nem quebrar as ligacoes entre tabelas."""

    ANTIGO = """
    CREATE TABLE usuarios (id INTEGER PRIMARY KEY, nome TEXT NOT NULL, criado_em TEXT NOT NULL DEFAULT (datetime('now')));
    CREATE TABLE fila (id INTEGER PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
        tipo TEXT NOT NULL CHECK (tipo IN ('link', 'narrar', 'lote')), alvo TEXT NOT NULL, rotulo TEXT NOT NULL,
        estado TEXT NOT NULL DEFAULT 'aguardando', progresso TEXT, resultado TEXT,
        criado_em TEXT NOT NULL DEFAULT (datetime('now')), iniciado_em TEXT, terminado_em TEXT);
    CREATE TABLE templates (id INTEGER PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id), nome TEXT NOT NULL,
        layout TEXT NOT NULL CHECK (layout IN ('post', 'meme', 'viral')), config TEXT NOT NULL DEFAULT '{}',
        passo INTEGER NOT NULL DEFAULT 1, criado_em TEXT NOT NULL DEFAULT (datetime('now')),
        atualizado_em TEXT NOT NULL DEFAULT (datetime('now')));
    CREATE TABLE template_frases (id INTEGER PRIMARY KEY, template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
        texto TEXT NOT NULL, origem TEXT NOT NULL DEFAULT 'manual', selecionada INTEGER NOT NULL DEFAULT 1,
        criado_em TEXT NOT NULL DEFAULT (datetime('now')));
    INSERT INTO usuarios (id, nome) VALUES (1, 'dono');
    INSERT INTO fila (usuario_id, tipo, alvo, rotulo) VALUES (1, 'link', 'https://x', 'x');
    INSERT INTO templates (usuario_id, nome, layout) VALUES (1, 'Meu template', 'post');
    INSERT INTO template_frases (template_id, texto) VALUES (1, 'Frase guardada');
    """

    def test_refaz_as_tabelas_sem_perder_nada(self):
        import sqlite3
        pasta = Path(tempfile.mkdtemp(prefix="migra_"))
        arquivo = pasta / "canal.db"
        with sqlite3.connect(arquivo) as conexao:
            conexao.executescript(self.ANTIGO)
        with mock.patch.object(config, "ARQUIVO_BANCO", arquivo):
            banco.criar_tabelas()
            banco.criar_tabelas()                                   # rodar de novo nao muda nada
            from contextlib import closing
            with closing(banco.conectar()) as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM fila").fetchone()[0], 1)
                self.assertEqual(c.execute("SELECT nome, layout FROM templates").fetchone()[:], ("Meu template", "post"))
                self.assertEqual(c.execute("SELECT texto FROM template_frases").fetchone()[0], "Frase guardada")
                # as tabelas filhas continuam apontando para `templates` (nao para a tabela antiga)
                self.assertEqual([r["table"] for r in c.execute("PRAGMA foreign_key_list(template_frases)")], ["templates"])
                self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
                # o que a trava antiga proibia agora entra
                c.execute("INSERT INTO fila (usuario_id, tipo, alvo, rotulo) VALUES (1, 'baixar', 'u', 'u')")
                c.execute("INSERT INTO templates (usuario_id, nome, layout) VALUES (1, 'Editor', 'cheio')")
                # apagar um template continua levando as frases dele (ON DELETE CASCADE)
                c.execute("DELETE FROM templates WHERE id = 1")
                self.assertEqual(c.execute("SELECT COUNT(*) FROM template_frases").fetchone()[0], 0)


class TesteParteB(unittest.TestCase):
    """Perfis, biblioteca, Editor e download em .zip."""
    VIDEO = Path(__file__).parent / "exemplo_zoo.mp4"

    @classmethod
    def setUpClass(cls):
        os.environ["CANAL_SEM_TRABALHADOR"] = "1"
        from fastapi.testclient import TestClient
        from app.busca import biblioteca, perfil
        from app.multiplicador import renderizar, repositorio
        from app.painel import servidor
        cls.perfil, cls.biblioteca, cls.renderizar, cls.repo = perfil, biblioteca, renderizar, repositorio
        cls.cliente = TestClient(servidor.criar_app())

    def setUp(self):
        banco.criar_tabelas()
        perfil_cache = self.perfil._cache
        perfil_cache.clear()
        self.ids, self.itens = [], []
        self.addCleanup(self._limpar)

    def _limpar(self):
        import sqlite3
        for i in self.ids:
            self.repo.excluir_template(i)
        for i in self.itens:
            self.repo.excluir_da_biblioteca(i)
        with sqlite3.connect(config.ARQUIVO_BANCO) as conexao:
            conexao.execute("DELETE FROM fila")

    # ---------- leitura de perfil ----------

    def test_reconhece_canais_e_recusa_o_resto(self):
        norm = self.perfil.normalizar_alvo
        self.assertEqual(norm("@IShowSpeed"), "https://www.youtube.com/@IShowSpeed")
        self.assertEqual(norm("https://www.youtube.com/@canal/videos"), "https://www.youtube.com/@canal")
        self.assertEqual(norm("youtube.com/channel/UCabc123"), "https://www.youtube.com/channel/UCabc123")
        for ruim in ("", "banana", "https://www.youtube.com/watch?v=abcdefghijk", "https://instagram.com/perfil",
                     "https://www.youtube.com/"):
            with self.assertRaises(self.perfil.ErroPerfil, msg=ruim):
                norm(ruim)

    def test_velocidade_e_views_por_hora(self):
        from datetime import datetime, timedelta, timezone
        agora = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        publicado = (agora - timedelta(hours=10)).isoformat()
        self.assertEqual(self.perfil.velocidade(5000, publicado, agora), 500.0)
        self.assertEqual(self.perfil.velocidade(5000, (agora - timedelta(minutes=5)).isoformat(), agora), 5000.0)  # minimo 1 h
        self.assertIsNone(self.perfil.velocidade(None, publicado, agora))
        self.assertIsNone(self.perfil.velocidade(100, None, agora))
        self.assertIsNone(self.perfil.velocidade(100, "data estranha", agora))

    def test_listar_monta_os_posts_e_usa_cache(self):
        saida = json.dumps({"channel": "Canal Teste", "channel_id": "UC1", "uploader_id": "@teste", "entries": [
            {"id": "aaaaaaaaaaa", "title": "Primeiro", "view_count": 1000, "duration": 61},
            {"id": "bbbbbbbbbbb", "title": "Segundo", "view_count": 90000, "duration": 30},
            None]})
        with mock.patch.object(self.perfil, "_yt_dlp", return_value=saida) as ytdlp, \
             mock.patch.object(self.perfil, "_datas", return_value={"aaaaaaaaaaa": "2026-11-01T00:00:00+00:00"}):
            r = self.perfil.listar("@teste")
            self.perfil.listar("@teste")                                       # segunda vez: cache
        self.assertEqual(ytdlp.call_count, 1)
        self.assertEqual(r["canal"]["nome"], "Canal Teste")
        posts = r["posts"]
        self.assertEqual([p["id"] for p in posts], ["aaaaaaaaaaa", "bbbbbbbbbbb"])
        self.assertEqual(posts[0]["url"], "https://www.youtube.com/watch?v=aaaaaaaaaaa")
        self.assertIsNotNone(posts[0]["velocidade"])
        self.assertIsNone(posts[1]["velocidade"])                              # sem data, sem velocidade
        with mock.patch.object(self.perfil, "_yt_dlp", return_value=saida), mock.patch.object(self.perfil, "_datas", return_value={}):
            shorts = self.perfil.listar("@teste", aba="shorts")
        self.assertIn("/shorts/", shorts["posts"][0]["url"])
        with self.assertRaises(self.perfil.ErroPerfil):
            self.perfil.listar("@teste", aba="lives")

    def test_api_buscar_perfil(self):
        with mock.patch.object(self.perfil, "listar", return_value={"canal": {"nome": "X"}, "posts": []}):
            self.assertEqual(self.cliente.post("/api/perfis/buscar", json={"alvo": "@x"}).status_code, 200)
        self.assertEqual(self.cliente.post("/api/perfis/buscar", json={"alvo": "banana"}).status_code, 400)
        self.assertEqual(self.cliente.get("/perfis").status_code, 200)

    def test_enviar_para_cortes_nao_repete(self):
        a, b = "https://www.youtube.com/watch?v=perfil00001", "https://www.youtube.com/watch?v=perfil00002"
        r = self.cliente.post("/api/perfis/enviar-cortes", json={"urls": [a, b]}).json()
        self.assertEqual((r["na_fila"], r["ja_processados"]), (2, 0))
        r = self.cliente.post("/api/perfis/enviar-cortes", json={"urls": [a]}).json()
        self.assertEqual((r["na_fila"], r["ja_processados"]), (0, 1))          # ja esta na fila
        self.assertEqual(self.cliente.post("/api/perfis/enviar-cortes", json={"urls": []}).status_code, 400)
        self.assertEqual(self.cliente.post("/api/perfis/enviar-cortes", json={"urls": ["https://exemplo.com/x"]}).status_code, 400)
        self.assertEqual(self.cliente.post("/api/perfis/enviar-cortes", json={"urls": [a] * 61}).status_code, 400)

    # ---------- biblioteca ----------

    @unittest.skipUnless(VIDEO.exists(), "video de exemplo ausente")
    def test_baixar_para_biblioteca_e_usar_no_template(self):
        import shutil
        url = "https://www.youtube.com/watch?v=biblio00001"

        def baixa_de_mentira(link, pasta):
            pasta.mkdir(parents=True, exist_ok=True)
            destino = pasta / "youtube_biblio00001.mp4"
            shutil.copy(self.VIDEO, destino)
            return VideoBaixado("youtube", "biblio00001", link, "Video da biblioteca", "Canal B", 19.0, destino)

        with mock.patch.object(self.biblioteca.baixar, "baixar", side_effect=baixa_de_mentira) as baixa:
            self.assertIn("Baixado", self.biblioteca.baixar_para_biblioteca(url, 1))
            self.assertIn("Já estava", self.biblioteca.baixar_para_biblioteca(url, 1))    # nao baixa duas vezes
            self.assertEqual(baixa.call_count, 1)
        item = self.repo.buscar_na_biblioteca(1, "youtube", "biblio00001")
        self.itens.append(item["id"])
        lista = self.cliente.get("/api/biblioteca").json()["itens"]
        self.assertTrue(any(i["id"] == item["id"] for i in lista))
        self.assertEqual(self.cliente.get(f"/api/biblioteca/{item['id']}/miniatura.jpg").status_code, 200)
        self.assertEqual(self.cliente.get("/api/biblioteca/999999/miniatura.jpg").status_code, 404)

        # usar no template: a midia aponta para o arquivo da biblioteca e tirar a midia nao apaga o arquivo
        template_id = self.cliente.post("/api/templates", json={"layout": "post"}).json()["id"]
        self.ids.append(template_id)
        r = self.cliente.post(f"/api/templates/{template_id}/midias", json={"biblioteca": [item["id"]]})
        self.assertEqual(r.json()["novos"], 1)
        self.assertEqual(self.cliente.post(f"/api/templates/{template_id}/midias", json={"biblioteca": [item["id"]]}).json()["novos"], 0)
        midia = self.repo.listar_midias(template_id)[0]
        self.assertEqual((midia["origem"], midia["arquivo"]), ("perfil", item["arquivo"]))
        self.cliente.delete(f"/api/templates/{template_id}/midias/{midia['id']}")
        self.assertTrue(config.caminho_absoluto(item["arquivo"]).exists())
        self.assertEqual(self.cliente.post(f"/api/templates/{template_id}/midias", json={"biblioteca": [999999]}).status_code, 404)

    def test_fila_baixa_para_a_biblioteca(self):
        from app.painel import fila
        banco.enfileirar(1, "baixar", "https://www.youtube.com/watch?v=biblio00002", "Titulo")
        with mock.patch.object(fila.biblioteca, "baixar_para_biblioteca", return_value="Baixado: Titulo") as baixa:
            self.assertTrue(fila.processar_proximo())
        baixa.assert_called_once()
        self.assertEqual(banco.listar_fila(1)[0]["resultado"], "Baixado: Titulo")

    def test_baixar_nao_enfileira_o_que_ja_esta_na_biblioteca(self):
        url = "https://www.youtube.com/watch?v=biblio00003"
        self.assertEqual(self.cliente.post("/api/perfis/baixar", json={"urls": [url], "titulos": {url: "T"}}).json()["na_fila"], 1)
        self.assertEqual(self.cliente.post("/api/perfis/baixar", json={"urls": [url]}).json()["ja_tem"], 1)

    # ---------- Editor ----------

    def test_editor_fica_separado_dos_templates(self):
        r = self.cliente.post("/api/templates", json={"layout": "cheio", "nome": "Ajuste"})
        self.assertEqual(r.status_code, 200)
        ajuste = r.json()["id"]
        self.ids.append(ajuste)
        self.assertEqual([f["texto"] for f in self.repo.listar_frases(ajuste)], ["-"])      # frase muda do Editor
        template = self.cliente.post("/api/templates", json={"layout": "post"}).json()["id"]
        self.ids.append(template)
        ids_templates = [t["id"] for t in self.cliente.get("/api/templates").json()["templates"]]
        ids_editor = [a["id"] for a in self.cliente.get("/api/editor").json()["ajustes"]]
        self.assertIn(template, ids_templates)
        self.assertNotIn(ajuste, ids_templates)
        self.assertIn(ajuste, ids_editor)
        self.assertNotIn(template, ids_editor)
        layouts = self.cliente.get("/api/templates").json()["layouts"]
        self.assertNotIn("cheio", [l["id"] for l in layouts])                                # nao aparece na escolha de modelo
        self.assertNotIn("cheio", self.cliente.get(f"/api/templates/{template}").json()["layouts"])
        self.assertEqual(self.cliente.get("/editor").status_code, 200)
        self.assertEqual(self.cliente.get(f"/editor/{ajuste}").status_code, 200)
        self.assertEqual(self.cliente.get(f"/editor/{template}").status_code, 404)

    @unittest.skipUnless(VIDEO.exists(), "video de exemplo ausente")
    def test_editor_gera_tela_cheia_e_refaz_do_zero(self):
        from app.painel import fila
        ajuste = self.cliente.post("/api/templates", json={"layout": "cheio"}).json()["id"]
        self.ids.append(ajuste)
        enviado = self.cliente.post(f"/api/templates/{ajuste}/upload?nome=zoo.mp4", content=self.VIDEO.read_bytes()).json()["id"]
        self.cliente.put(f"/api/templates/{ajuste}/midias/{enviado}", json={"zoom": 1.5, "pos_x": 30})
        self.assertEqual(self.cliente.get(f"/api/templates/{ajuste}/previa.jpg").status_code, 200)

        self.assertEqual(self.cliente.post(f"/api/templates/{ajuste}/gerar").json()["novas"], 1)
        fila.processar_proximo()
        saidas = self.cliente.get(f"/api/templates/{ajuste}/saidas").json()
        self.assertEqual(saidas["contagem"]["pronto"], 1)
        arquivo = config.caminho_absoluto(self.repo.ler_saida(saidas["saidas"][0]["id"])["arquivo"])
        import subprocess
        tamanho = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                  "-of", "csv=p=0", str(arquivo)], capture_output=True, text=True).stdout.strip()
        self.assertEqual(tamanho, "1080,1920")

        # gerar de novo sem apagar e recusado; apagando antes, refaz
        self.assertEqual(self.cliente.post(f"/api/templates/{ajuste}/gerar").status_code, 409)
        self.assertEqual(self.cliente.delete(f"/api/templates/{ajuste}/saidas").json()["apagados"], 1)
        self.assertFalse(arquivo.exists())
        self.assertEqual(self.cliente.post(f"/api/templates/{ajuste}/gerar").json()["novas"], 1)

    @unittest.skipUnless(VIDEO.exists(), "video de exemplo ausente")
    def test_editor_comeca_em_caber_para_video_horizontal(self):
        ajuste = self.cliente.post("/api/templates", json={"layout": "cheio"}).json()["id"]
        template = self.cliente.post("/api/templates", json={"layout": "post"}).json()["id"]
        self.ids += [ajuste, template]
        for destino in (ajuste, template):
            self.cliente.post(f"/api/templates/{destino}/upload?nome=zoo.mp4", content=self.VIDEO.read_bytes())
        self.assertEqual(self.repo.listar_midias(ajuste)[0]["ajuste"], "caber")        # Editor + video horizontal
        self.assertEqual(self.repo.listar_midias(template)[0]["ajuste"], "preencher")  # template: nao muda
        # quem ja mexeu no enquadramento nao e sobrescrito
        midia = self.repo.listar_midias(ajuste)[0]
        self.repo.atualizar_midia(midia["id"], ajuste="preencher", zoom=1.4)
        self.cliente.post(f"/api/templates/{ajuste}/midias", json={"cortes": []})
        self.assertEqual(self.repo.ler_midia(midia["id"])["ajuste"], "preencher")
        self.assertEqual(self.renderizar.dimensoes(self.VIDEO)[0] > self.renderizar.dimensoes(self.VIDEO)[1], True)

    @unittest.skipUnless(VIDEO.exists(), "video de exemplo ausente")
    def test_zip_com_todos_os_videos_prontos(self):
        import io, zipfile
        from app.painel import fila
        template_id = self.cliente.post("/api/templates", json={"layout": "meme", "nome": "Meu Lote"}).json()["id"]
        self.ids.append(template_id)
        self.assertEqual(self.cliente.get(f"/api/templates/{template_id}/saidas.zip").status_code, 404)    # nada pronto ainda
        self.cliente.post(f"/api/templates/{template_id}/upload?nome=zoo.mp4", content=self.VIDEO.read_bytes())
        self.cliente.post(f"/api/templates/{template_id}/frases", json={"textos": ["Frase um", "Frase dois"]})
        self.cliente.post(f"/api/templates/{template_id}/gerar")
        fila.processar_proximo()
        resposta = self.cliente.get(f"/api/templates/{template_id}/saidas.zip")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(resposta.content)) as z:
            self.assertEqual(z.namelist(), ["Meu_Lote_01.mp4", "Meu_Lote_02.mp4"])
            self.assertIsNone(z.testzip())
        self.assertEqual(self.cliente.get("/api/templates/999999/saidas.zip").status_code, 404)


if __name__ == "__main__":
    unittest.main()
