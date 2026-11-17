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
from cryptography.fernet import Fernet  # noqa: E402
os.environ["CANAL_CHAVE_SECRETA"] = Fernet.generate_key().decode()

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

    def test_frase_de_um_video_so_sai_com_ele(self):
        template_id = self.novo()
        a = self.repo.adicionar_arquivo(template_id, "templates/x/a.mp4", "A")
        b = self.repo.adicionar_arquivo(template_id, "templates/x/b.mp4", "B")
        c = self.repo.adicionar_arquivo(template_id, "templates/x/c.mp4", "C")
        self.repo.adicionar_frases(template_id, ["Do A um", "Do A dois"], "ia", a)
        self.repo.adicionar_frases(template_id, ["Do B um", "Do B dois"], "ia", b)
        self.repo.adicionar_frases(template_id, ["Do C um", "Do C dois"], "ia", c)
        self.repo.adicionar_frases(template_id, ["Serve para todos"])
        pares = {(m["rotulo"], f["texto"]) for m, f in self.repo.cruzamento(template_id)}
        self.assertEqual(len(pares), 9)                                              # 3 videos x (2 deles + 1 geral)
        self.assertNotIn(("B", "Do A um"), pares)
        self.assertIn(("A", "Do A um"), pares)
        self.assertEqual({t for v, t in pares if t == "Serve para todos"}, {"Serve para todos"})
        self.assertEqual(len({v for v, t in pares if t == "Serve para todos"}), 3)  # a geral sai com os tres
        self.assertEqual(self.repo.gerar_saidas(template_id), (9, 0))
        # a mesma frase pode existir em videos diferentes, mas nao duas vezes no mesmo
        self.assertEqual(self.repo.adicionar_frases(template_id, ["Do A um"], "manual", b), 1)
        self.assertEqual(self.repo.adicionar_frases(template_id, ["do a um"], "manual", b), 0)
        # video desmarcado nao entra; video apagado leva as frases dele junto
        self.repo.atualizar_midia(a, selecionada=False)
        self.assertEqual({m["rotulo"] for m, f in self.repo.cruzamento(template_id)}, {"B", "C"})
        self.repo.excluir_midia(c)
        self.assertFalse([f for f in self.repo.listar_frases(template_id) if f["midia_id"] == c])
        self.assertTrue([f for f in self.repo.listar_frases(template_id) if f["midia_id"] is None])

    def test_banco_antigo_ganha_a_coluna_midia_id_sem_perder_frases(self):
        import sqlite3
        conexao = sqlite3.connect(":memory:")
        conexao.row_factory = sqlite3.Row
        conexao.execute("CREATE TABLE template_midias (id INTEGER PRIMARY KEY)")
        conexao.execute("CREATE TABLE template_frases (id INTEGER PRIMARY KEY, template_id INTEGER, texto TEXT)")
        conexao.execute("INSERT INTO template_frases (template_id, texto) VALUES (1, 'Antiga')")
        banco._garantir_colunas(conexao)
        banco._garantir_colunas(conexao)                                             # pode rodar de novo
        linha = conexao.execute("SELECT texto, midia_id FROM template_frases").fetchone()
        self.assertEqual((linha["texto"], linha["midia_id"]), ("Antiga", None))      # antiga vale para todos
        colunas = {l["name"]: l["dflt_value"] for l in conexao.execute("PRAGMA table_info(template_midias)")}
        self.assertEqual(colunas.get("com_legenda"), "1")                            # corte antigo passa a vir com legenda

    def test_gerar_para_video_usa_titulo_e_motivo(self):
        cliente = ClienteFalso([resposta_falsa({"frases": ["So uma"]}),
                                resposta_falsa({"frases": ["Quase ninguem viu esse detalhe", "Isso mudou o jogo?"]})])
        resultado = self.frases.gerar_para_video("Detalhe escondido no trailer", "Gancho forte.", 2,
                                                 usuario_id=1, cliente=cliente)
        self.assertEqual(len(resultado), 2)
        self.assertEqual(len(cliente.chamadas), 2)                                   # a primeira veio errada
        mensagem = cliente.chamadas[0]["messages"][0]["content"]
        self.assertIn("Detalhe escondido no trailer", mensagem)
        self.assertIn("Gancho forte.", mensagem)
        self.assertNotIn("{{", cliente.chamadas[0]["system"])
        with self.assertRaises(ValueError):
            self.frases.gerar_para_video("  ", None, 3, usuario_id=1)
        with self.assertRaises(ValueError):
            self.frases.gerar_para_video("Titulo", None, 99, usuario_id=1)

    def test_api_gera_frases_por_video_e_um_erro_nao_derruba_os_outros(self):
        from app import ia as modulo_ia
        template_id = self.novo()
        a = self.repo.adicionar_arquivo(template_id, "templates/x/a.mp4", "Trailer novo")
        b = self.repo.adicionar_arquivo(template_id, "templates/x/b.mp4", "Mapa vazado")

        def falso(titulo, motivo, quantidade, **_):
            if titulo == "Mapa vazado":
                raise modulo_ia.ErroIA("A IA nao respondeu.")
            return [f"{titulo} frase {i}" for i in range(quantidade)]

        url = f"/api/templates/{template_id}/frases/gerar-por-video"
        with mock.patch.object(self.frases, "gerar_para_video", side_effect=falso):
            r = self.cliente.post(url, json={"quantidade": 2})
            self.assertEqual(r.status_code, 200)
            dados = r.json()
            self.assertEqual([v["midia_id"] for v in dados["videos"]], [a])
            self.assertEqual([e["midia_id"] for e in dados["erros"]], [b])
            self.assertEqual(dados["resumo"]["total"], 2)                            # so as frases do video A
            self.assertEqual([f["midia_id"] for f in self.repo.listar_frases(template_id)], [a, a])
            # um video so
            r = self.cliente.post(url, json={"quantidade": 1, "midia_id": a})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(len(r.json()["videos"]), 1)
            # video de outro template e quantidade ruim
            outro = self.novo()
            estranho = self.repo.adicionar_arquivo(outro, "templates/x/z.mp4", "Z")
            self.assertEqual(self.cliente.post(url, json={"midia_id": estranho}).status_code, 404)
            self.assertEqual(self.cliente.post(url, json={"quantidade": "muitas"}).status_code, 400)
        # sem nenhum video escolhido
        vazio = self.novo()
        self.assertEqual(self.cliente.post(f"/api/templates/{vazio}/frases/gerar-por-video", json={}).status_code, 400)
        # todos os videos com erro: avisa em vez de dizer que deu certo
        with mock.patch.object(self.frases, "gerar_para_video", side_effect=modulo_ia.ErroIA("fora do ar")):
            self.assertEqual(self.cliente.post(url, json={"quantidade": 1, "midia_id": b}).status_code, 502)

    def test_api_adiciona_frase_a_um_video_do_proprio_template(self):
        template_id = self.novo()
        midia = self.repo.adicionar_arquivo(template_id, "templates/x/a.mp4", "A")
        outro = self.novo()
        estranha = self.repo.adicionar_arquivo(outro, "templates/x/z.mp4", "Z")
        url = f"/api/templates/{template_id}/frases"
        self.assertEqual(self.cliente.post(url, json={"textos": ["Minha frase"], "midia_id": midia}).status_code, 200)
        self.assertEqual(self.repo.listar_frases(template_id)[0]["midia_id"], midia)
        self.assertEqual(self.cliente.post(url, json={"textos": ["Outra"], "midia_id": estranha}).status_code, 404)
        dados = self.cliente.get(f"/api/templates/{template_id}").json()
        self.assertEqual(dados["frases"][0]["midia_id"], midia)

    def test_corte_entra_com_legenda_e_narracao_e_pode_sair_limpo(self):
        import shutil
        exemplo = Path(__file__).parent / "exemplo_zoo.mp4"
        pasta = config.PASTA_CORTES / "teste_legenda"
        pasta.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(pasta, ignore_errors=True))
        original, pronto = pasta / "original.mp4", pasta / "corte_pronto.mp4"
        shutil.copy(exemplo, original)
        shutil.copy(exemplo, pronto)
        video_id = banco.registrar_video(1, "youtube", f"leg{len(self.ids):08d}", "https://exemplo/legenda")
        banco.atualizar_video(video_id, caminho_arquivo=config.caminho_relativo(original))
        corte = banco.registrar_corte(1, video_id, CorteProposto(1, 2, 3.0, 9.0, 80, "m", "Corte com legenda", "narrado"))
        banco.atualizar_corte(corte, caminho_arquivo=config.caminho_relativo(pronto))
        template_id = self.novo()
        self.assertEqual(self.repo.adicionar_cortes(template_id, [corte]), 1)
        midia = self.repo.listar_midias(template_id)[0]
        self.assertEqual(midia["com_legenda"], 1)                                    # padrao: o corte pronto
        self.assertEqual(self.renderizar.resolver_midia(midia), (pronto, None, None))
        # desligado: so o trecho do original, sem legenda
        self.assertEqual(self.cliente.put(f"/api/templates/{template_id}/midias/{midia['id']}",
                                          json={"com_legenda": False}).status_code, 200)
        midia = self.repo.listar_midias(template_id)[0]
        self.assertEqual(self.renderizar.resolver_midia(midia), (original, 3.0, 6.0))
        # o recorte do corte pronto mira a faixa da legenda; se o dono mexer na posicao, vale a dele
        zona = (0, 0, 1080, 835)
        pronto_marcado = self.renderizar._marcar_corte_pronto({**midia, "pos_y": 50}, None)
        self.assertIn(f"ih*{self.renderizar.FOCO_CORTE_PRONTO}", self.renderizar._filtro_zona(0, "z", zona, pronto_marcado, "desfocado"))
        movido = {**pronto_marcado, "pos_y": 80}
        self.assertIn("(ih-835)*0.8000", self.renderizar._filtro_zona(0, "z", zona, movido, "desfocado"))
        limpo = self.renderizar._marcar_corte_pronto({**midia, "pos_y": 50}, 3.0)          # trecho do original
        self.assertIn("(ih-835)*0.5000", self.renderizar._filtro_zona(0, "z", zona, limpo, "desfocado"))
        # ligado, mas o corte pronto sumiu do disco: usa o original em vez de quebrar
        self.repo.atualizar_midia(midia["id"], com_legenda=True)
        pronto.unlink()
        midia = self.repo.listar_midias(template_id)[0]
        self.assertEqual(self.renderizar.resolver_midia(midia), (original, 3.0, 6.0))

    # ---------- janela do corte: postar com template ----------

    def _corte_com_video(self, titulo="Corte para postar"):
        import shutil
        pasta = config.PASTA_CORTES / "teste_modelo"
        pasta.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(pasta, ignore_errors=True))
        arquivo = pasta / f"c{len(self.ids)}.mp4"
        shutil.copy(Path(__file__).parent / "exemplo_zoo.mp4", arquivo)
        video_id = banco.registrar_video(1, "youtube", f"mod{len(self.ids):08d}{id(self) % 1000}", "https://exemplo/modelo")
        corte = banco.registrar_corte(1, video_id, CorteProposto(1, 2, 0.0, 10.0, 80, "Gancho forte.", titulo, "narrado"))
        banco.atualizar_corte(corte, estado="aprovado", caminho_arquivo=config.caminho_relativo(arquivo))
        return corte

    def test_preparar_varios_cortes_deixa_prontos_para_agendar(self):
        from app.painel import fila as modulo_fila
        um, dois = self._corte_com_video("Primeiro corte"), self._corte_com_video("Segundo corte")
        banco.atualizar_corte(dois, frase_gancho="Frase que ja existia")
        template_id = self.novo("post")
        r = self.cliente.post("/api/cortes/preparar", json={"cortes": [um, dois, um], "template_id": template_id})
        self.assertEqual((r.json()["enfileirados"], r.json()["pulados"]), (2, 0), r.text)
        # pedir de novo enquanto esta na fila nao duplica
        self.assertEqual(self.cliente.post("/api/cortes/preparar", json={"cortes": [um], "template_id": template_id}).json()["pulados"], 1)
        itens = [banco.item_na_fila(1, "preparar", f"{c}:{template_id}") for c in (um, dois)]
        cortes = {c["id"]: c for c in self.cliente.get("/api/cortes").json()["cortes"]}
        self.assertTrue(cortes[um]["preparando"])
        self.assertIsNone(cortes[um]["pronta"])
        with mock.patch.object(self.frases, "gerar_para_video", return_value=["Frase nova do gancho"]) as gera:
            for item in itens:
                self.assertEqual(modulo_fila.executar(item), "Pronto para agendar")
                banco.atualizar_fila(item["id"], estado="pronto")
            self.assertEqual(gera.call_count, 1)                                  # so o corte sem frase chamou a IA
        cortes = {c["id"]: c for c in self.cliente.get("/api/cortes").json()["cortes"]}
        for corte_id, frase in ((um, "Frase nova do gancho"), (dois, "Frase que ja existia")):
            c = cortes[corte_id]
            self.assertFalse(c["preparando"])
            self.assertEqual((c["pronta"]["template_id"], c["pronta"]["frase"]), (template_id, frase))
            self.assertFalse(c["agendado"])
            self.assertEqual(self.cliente.get(c["pronta"]["url"]).status_code, 200)
            mini = self.cliente.get(c["pronta"]["miniatura"])
            self.assertEqual((mini.status_code, mini.headers["content-type"]), (200, "image/jpeg"))
        self.assertEqual(banco.ler_corte(um)["frase_gancho"], "Frase nova do gancho")   # guardada para a proxima vez
        # pedidos ruins
        self.assertEqual(self.cliente.post("/api/cortes/preparar", json={"cortes": [], "template_id": template_id}).status_code, 400)
        self.assertEqual(self.cliente.post("/api/cortes/preparar", json={"cortes": [um], "template_id": 999999}).status_code, 404)

    def test_corte_gera_video_no_template_sem_bagunçar_o_assistente(self):
        corte = self._corte_com_video()
        template_id = self.novo("viral")
        url = f"/api/cortes/{corte}/modelo/gerar"
        r = self.cliente.post(url, json={"template_id": template_id, "frase": "  Olha   esse detalhe de GTA 6  "})
        self.assertEqual(r.status_code, 200, r.text)
        saida_id = r.json()["saida_id"]
        self.assertFalse(r.json()["ja_existia"])
        item = banco.item_na_fila(1, "lote", str(template_id))                         # entrou na fila
        self.assertIsNotNone(item)
        self.addCleanup(lambda: banco.atualizar_fila(item["id"], estado="pronto"))   # nao deixa item preso para outros testes
        # o assistente do template nao ve o corte nem a frase, e o lote do template nao os inclui
        dados = self.cliente.get(f"/api/templates/{template_id}").json()
        self.assertEqual((dados["midias"], dados["frases"]), ([], []))
        self.assertEqual(dados["resumo"]["total"], 0)
        self.assertEqual(self.repo.gerar_saidas(template_id), (0, 0))
        # a mesma frase de novo nao cria outro video
        r2 = self.cliente.post(url, json={"template_id": template_id, "frase": "olha esse detalhe de gta 6"})
        self.assertEqual(r2.json()["saida_id"], saida_id)
        self.assertTrue(r2.json()["ja_existia"])
        # o lote gera o video e ele aparece na lista do corte, pronto
        self.lote.processar_template(template_id)
        lista = self.cliente.get(f"/api/cortes/{corte}/modelo/saidas").json()["saidas"]
        self.assertEqual([(s["frase"], s["estado"]) for s in lista], [("Olha esse detalhe de GTA 6", "pronto")])
        self.assertEqual(self.cliente.get(lista[0]["url"]).status_code, 200)
        # adicionar o mesmo corte no assistente continua possivel (o avulso nao conta como repetido)
        self.assertEqual(self.repo.adicionar_cortes(template_id, [corte]), 1)

    def test_corte_gera_frases_previa_e_recusa_pedidos_ruins(self):
        from app import ia as modulo_ia
        corte = self._corte_com_video("Rockstar confirma 30 FPS")
        template_id = self.novo("post")
        with mock.patch.object(self.frases, "gerar_para_video", return_value=["Uma", "Duas"]) as gera:
            r = self.cliente.post(f"/api/cortes/{corte}/modelo/frases", json={"quantidade": 2})
            self.assertEqual(r.json()["frases"], ["Uma", "Duas"])
            self.assertEqual(gera.call_args.args[0], "Rockstar confirma 30 FPS")        # le o titulo do corte
        with mock.patch.object(self.frases, "gerar_para_video", side_effect=modulo_ia.ErroIA("fora")):
            self.assertEqual(self.cliente.post(f"/api/cortes/{corte}/modelo/frases", json={}).status_code, 502)
        with mock.patch.object(self.frases, "gerar_para_video", return_value=["Frase guardada"]) as gera:
            url_auto = f"/api/cortes/{self._corte_com_video('Outro corte')}/modelo/frase-auto"
            primeira = self.cliente.post(url_auto).json()
            segunda = self.cliente.post(url_auto).json()
            self.assertEqual((primeira["frase"], primeira["nova"]), ("Frase guardada", True))
            self.assertEqual((segunda["frase"], segunda["nova"]), ("Frase guardada", False))
            self.assertEqual(gera.call_count, 1)                                         # a IA so e chamada uma vez
        previa = self.cliente.get(f"/api/cortes/{corte}/modelo/previa.jpg", params={"template_id": template_id, "frase": "Teste"})
        self.assertEqual(previa.status_code, 200)
        self.assertEqual(previa.headers["content-type"], "image/jpeg")
        self.assertEqual(self.cliente.get(f"/api/cortes/{corte}/modelo/saidas").json()["saidas"], [])   # previa nao grava nada
        url = f"/api/cortes/{corte}/modelo/gerar"
        self.assertEqual(self.cliente.post(url, json={"template_id": template_id, "frase": "  "}).status_code, 400)
        self.assertEqual(self.cliente.post(url, json={"template_id": template_id, "frase": "x" * 300}).status_code, 400)
        self.assertEqual(self.cliente.post(url, json={"template_id": 999999, "frase": "ok"}).status_code, 404)
        self.assertEqual(self.cliente.post("/api/cortes/999999/modelo/gerar", json={"template_id": template_id, "frase": "ok"}).status_code, 404)
        editor = self.repo.criar_template(1, "cheio", "Ajuste do editor")
        self.ids.append(editor)
        self.assertEqual(self.cliente.post(url, json={"template_id": editor, "frase": "ok"}).status_code, 404)  # so templates de verdade

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

    def test_janela_do_corte_rola_quando_o_conteudo_passa_da_altura(self):
        """Sem a linha de altura limitada, o conteudo extra ficava cortado e sem rolagem."""
        css = (Path(__file__).parent.parent / "app" / "painel" / "estatico" / "painel.css").read_text(encoding="utf-8")
        regra = css[css.index(".modal {"):css.index("@keyframes sobe")]
        self.assertIn("grid-template-rows: minmax(0, 1fr)", regra)

    def test_arquivos_da_tela_sempre_conferem_se_mudaram(self):
        """Depois de uma atualizacao o navegador nao pode mostrar a tela antiga guardada."""
        r = self.cliente.get("/estatico/assistente.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["cache-control"], "no-cache")
        igual = self.cliente.get("/estatico/assistente.js", headers={"If-None-Match": r.headers["etag"]})
        self.assertEqual(igual.status_code, 304)                                     # sem mudanca, nada e baixado de novo

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
                # as tabelas filhas continuam apontando para `templates` (nao para a tabela antiga);
                # a frase tambem aponta para o video (template_midias) a que pertence
                self.assertEqual(sorted(r["table"] for r in c.execute("PRAGMA foreign_key_list(template_frases)")),
                                 ["template_midias", "templates"])
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


# ======================================================================
# Fase 5: postagem (redes simuladas: nada sai do computador)
# ======================================================================

class Resposta:
    """Imita uma resposta do `requests`."""

    def __init__(self, status=200, corpo=None, headers=None):
        self.status_code, self._corpo, self.headers = status, corpo, headers or {}
        self.text = json.dumps(corpo) if corpo is not None else ""

    def json(self):
        if self._corpo is None:
            raise ValueError("sem json")
        return self._corpo


class RedeFalsa:
    """Troca o `requests.request` dos conectores. Cada regra: (metodo, trecho da url) -> resposta ou funcao."""

    def __init__(self, regras):
        self.regras, self.chamadas = list(regras), []

    def __call__(self, metodo, url, **kwargs):
        dados = kwargs.get("data")
        if hasattr(dados, "read"):
            kwargs["data"] = dados.read()
        self.chamadas.append((metodo, url, kwargs))
        for i, (m, trecho, resposta) in enumerate(self.regras):
            if m == metodo and trecho in url:
                if isinstance(resposta, list):            # sequencia: usa e tira a primeira
                    proxima = resposta.pop(0) if len(resposta) > 1 else resposta[0]
                    resposta = proxima
                if callable(resposta) and not isinstance(resposta, Resposta):
                    resposta = resposta(metodo, url, kwargs)
                if isinstance(resposta, Exception):
                    raise resposta
                return resposta
        raise AssertionError(f"Chamada inesperada: {metodo} {url}")

    def ativar(self):
        from app.postagem import redes
        return mock.patch.object(redes.requests, "request", side_effect=self)


def arquivo_de(tamanho: int) -> Path:
    pasta = Path(tempfile.mkdtemp(prefix="post_"))
    arquivo = pasta / "video.mp4"
    arquivo.write_bytes(os.urandom(tamanho))
    return arquivo


class TesteCofre(unittest.TestCase):
    def test_guarda_e_abre(self):
        from app.postagem import cofre
        texto = cofre.guardar({"token": "segredo-123"})
        self.assertNotIn("segredo-123", texto)
        self.assertEqual(cofre.abrir(texto), {"token": "segredo-123"})

    def test_chave_errada_nao_abre(self):
        from cryptography.fernet import Fernet
        from app.postagem import cofre
        texto = cofre.guardar({"a": 1})
        with mock.patch.dict(os.environ, {"CANAL_CHAVE_SECRETA": Fernet.generate_key().decode()}):
            with self.assertRaises(cofre.ErroCofre):
                cofre.abrir(texto)

    def test_cria_a_chave_no_env_se_faltar(self):
        from app.postagem import cofre
        pasta = Path(tempfile.mkdtemp(prefix="env_"))
        (pasta / ".env").write_text("ANTHROPIC_API_KEY=x", encoding="utf-8")
        ambiente = {k: v for k, v in os.environ.items() if k != "CANAL_CHAVE_SECRETA"}
        with mock.patch.dict(os.environ, ambiente, clear=True), mock.patch.object(config, "RAIZ", pasta):
            texto = cofre.guardar({"b": 2})
            self.assertEqual(cofre.abrir(texto), {"b": 2})
        conteudo = (pasta / ".env").read_text(encoding="utf-8")
        self.assertIn("ANTHROPIC_API_KEY=x\n", conteudo)            # o que ja existia continua
        self.assertIn("CANAL_CHAVE_SECRETA=", conteudo)


    def test_rele_a_chave_criada_por_outro_processo(self):
        """O painel aberto nao pode criar uma segunda chave se um comando no terminal ja criou a primeira."""
        from cryptography.fernet import Fernet
        from app.postagem import cofre
        pasta = Path(tempfile.mkdtemp(prefix="env2_"))
        chave = Fernet.generate_key().decode()
        (pasta / ".env").write_text(f"CANAL_CHAVE_SECRETA={chave}\n", encoding="utf-8")
        ambiente = {k: v for k, v in os.environ.items() if k != "CANAL_CHAVE_SECRETA"}
        with mock.patch.dict(os.environ, ambiente, clear=True), mock.patch.object(config, "RAIZ", pasta):
            texto = cofre.guardar({"c": 3})
        self.assertEqual(Fernet(chave.encode()).decrypt(texto.encode()), b'{"c": 3}')
        self.assertEqual((pasta / ".env").read_text(encoding="utf-8").count("CANAL_CHAVE_SECRETA="), 1)


class TesteYouTube(unittest.TestCase):
    def setUp(self):
        from app.postagem import youtube
        self.yt = youtube
        self.ambiente = mock.patch.dict(os.environ, {"YOUTUBE_CLIENT_ID": "id", "YOUTUBE_CLIENT_SECRET": "seg"})
        self.ambiente.start(); self.addCleanup(self.ambiente.stop)
        self.credenciais = __import__("app.postagem.redes", fromlist=["Credenciais"]).Credenciais(
            {"access_token": "velho", "refresh_token": "renova"})

    def test_envio_em_partes_e_resposta(self):
        arquivo = arquivo_de(5000)
        recebido = bytearray()

        def put(_m, _u, kw):
            recebido.extend(kw["data"])
            fim = int(kw["headers"]["Content-Range"].split("-")[1].split("/")[0])
            return Resposta(201, {"id": "abc123"}) if fim == 4999 else Resposta(308, headers={"Range": f"bytes=0-{fim}"})
        rede = RedeFalsa([("POST", "oauth2.googleapis.com/token", Resposta(200, {"access_token": "novo"})),
                          ("POST", "upload/youtube/v3/videos", Resposta(200, {}, {"Location": "https://upload/sessao"})),
                          ("PUT", "https://upload/sessao", put)])
        with rede.ativar(), mock.patch.object(self.yt, "PEDACO", 2048):
            r = self.yt.publicar(self.credenciais, arquivo, "Título", "Legenda #Shorts")
        self.assertEqual((r.id_externo, r.url), ("abc123", "https://www.youtube.com/shorts/abc123"))
        self.assertEqual(bytes(recebido), arquivo.read_bytes())                    # tudo chegou, em ordem
        sessao = next(c for c in rede.chamadas if "upload/youtube" in c[1])
        self.assertEqual(sessao[2]["params"]["uploadType"], "resumable")
        self.assertEqual(sessao[2]["headers"]["X-Upload-Content-Length"], "5000")
        self.assertEqual(sessao[2]["json"]["status"]["privacyStatus"], "public")
        self.assertTrue(self.credenciais.mudou)                                  # token novo para guardar

    def test_retoma_de_onde_parou(self):
        import requests
        arquivo = arquivo_de(3000)
        recebido = []

        def put(_m, _u, kw):
            faixa = kw["headers"]["Content-Range"]
            if faixa == "bytes */3000":
                return Resposta(308, headers={"Range": "bytes=0-1023"})       # so 1024 bytes chegaram
            recebido.append(faixa)
            if len(recebido) == 1:
                raise requests.ConnectionError("caiu")
            return Resposta(201, {"id": "v1"})
        rede = RedeFalsa([("POST", "oauth2", Resposta(200, {"access_token": "t"})),
                          ("POST", "upload/youtube", Resposta(200, {}, {"Location": "https://upload/s"})),
                          ("PUT", "https://upload/s", put)])
        with rede.ativar():
            self.assertEqual(self.yt.publicar(self.credenciais, arquivo, "T", "L").id_externo, "v1")
        self.assertEqual(recebido, ["bytes 0-2999/3000", "bytes 1024-2999/3000"])

    def test_acesso_vencido_pede_reconectar_e_cota_e_temporaria(self):
        from app.postagem.redes import ErroPostagem
        arquivo = arquivo_de(100)
        with RedeFalsa([("POST", "oauth2", Resposta(400, {"error": "invalid_grant"}))]).ativar():
            with self.assertRaises(ErroPostagem) as erro:
                self.yt.publicar(self.credenciais, arquivo, "T", "L")
        self.assertTrue(erro.exception.reconectar)
        cota = Resposta(403, {"error": {"errors": [{"reason": "quotaExceeded"}], "message": "quota"}})
        with RedeFalsa([("POST", "oauth2", Resposta(200, {"access_token": "t"})), ("POST", "upload/youtube", cota)]).ativar():
            with self.assertRaises(ErroPostagem) as erro:
                self.yt.publicar(self.credenciais, arquivo, "T", "L")
        self.assertTrue(erro.exception.temporario)

    def test_login_monta_o_endereco_e_guarda_o_canal(self):
        from urllib.parse import parse_qs, urlparse
        url = self.yt.endereco_de_login("http://127.0.0.1:8000/contas/retorno/youtube", "ESTADO")
        q = parse_qs(urlparse(url).query)
        self.assertEqual((q["access_type"], q["state"], q["prompt"]), (["offline"], ["ESTADO"], ["consent"]))
        self.assertIn("youtube.upload", q["scope"][0])
        rede = RedeFalsa([("POST", "oauth2", Resposta(200, {"access_token": "a", "refresh_token": "r"})),
                          ("GET", "youtube/v3/channels", Resposta(200, {"items": [{"id": "UC1", "snippet": {"title": "Meu Canal"}}]}))])
        with rede.ativar():
            contas = self.yt.concluir_login("CODIGO", "http://retorno")
        self.assertEqual((contas[0]["id_externo"], contas[0]["nome"]), ("UC1", "Meu Canal"))
        self.assertEqual(contas[0]["credenciais"]["refresh_token"], "r")


class TesteMeta(unittest.TestCase):
    def setUp(self):
        from app.postagem import meta
        from app.postagem.redes import Credenciais
        self.meta, self.Credenciais = meta, Credenciais
        self.addCleanup(mock.patch.object(meta, "_dormir", lambda s: None).stop)
        mock.patch.object(meta, "_dormir", lambda s: None).start()
        ambiente = mock.patch.dict(os.environ, {"META_APP_ID": "app", "META_APP_SECRET": "seg"})
        ambiente.start(); self.addCleanup(ambiente.stop)

    def test_login_usa_config_id_quando_existe(self):
        from urllib.parse import parse_qs, urlparse
        # app novo da Meta: as permissoes vivem na configuracao, o endereco leva o numero dela
        with mock.patch.dict(os.environ, {"META_CONFIG_ID": "123456789"}):
            q = parse_qs(urlparse(self.meta.endereco_de_login("https://painel/retorno/meta", "ESTADO")).query)
        self.assertEqual((q["config_id"], q["override_default_response_type"], q["response_type"]),
                         (["123456789"], ["true"], ["code"]))
        self.assertNotIn("scope", q)
        # app antigo: continua mandando a lista de permissoes
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("META_CONFIG_ID", None)
            q = parse_qs(urlparse(self.meta.endereco_de_login("https://painel/retorno/meta", "ESTADO")).query)
        self.assertIn("instagram_content_publish", q["scope"][0])
        self.assertNotIn("config_id", q)

    def test_reel_do_instagram(self):
        arquivo = arquivo_de(4000)
        rede = RedeFalsa([
            ("POST", "/IG1/media_publish", Resposta(200, {"id": "M9"})),
            ("POST", "/IG1/media", Resposta(200, {"id": "C1", "uri": "https://rupload.facebook.com/ig-api-upload/v27.0/C1"})),
            ("POST", "rupload.facebook.com/ig-api-upload", Resposta(200, {"success": True})),
            ("GET", "/C1", [Resposta(200, {"status_code": "IN_PROGRESS"}), Resposta(200, {"status_code": "FINISHED"})]),
            ("GET", "/M9", Resposta(200, {"permalink": "https://www.instagram.com/reel/XYZ/"})),
        ])
        with rede.ativar():
            r = self.meta.publicar_instagram(self.Credenciais({"ig_id": "IG1", "page_token": "PT"}), arquivo, "T", "Legenda")
        self.assertEqual((r.id_externo, r.url), ("M9", "https://www.instagram.com/reel/XYZ/"))
        criar = rede.chamadas[0]
        self.assertEqual((criar[2]["data"]["media_type"], criar[2]["data"]["upload_type"]), ("REELS", "resumable"))
        envio = rede.chamadas[1]
        self.assertEqual(envio[2]["headers"]["Authorization"], "OAuth PT")
        self.assertEqual((envio[2]["headers"]["offset"], envio[2]["headers"]["file_size"]), ("0", "4000"))

    def test_reel_do_instagram_tenta_de_novo_quando_a_meta_falha_a_toa(self):
        from app.postagem.redes import ErroPostagem
        falha = Resposta(400, {"debug_info": {"retriable": False, "type": "ProcessingFailedError",
                                              "message": "Request processing failed"}})
        rede = RedeFalsa([
            ("POST", "/IG1/media_publish", Resposta(200, {"id": "M9"})),
            ("POST", "/IG1/media", [Resposta(200, {"id": f"C{n}", "uri": f"https://rupload.facebook.com/ig-api-upload/v27.0/C{n}"})
                                    for n in (1, 2, 3)]),
            ("POST", "rupload.facebook.com/ig-api-upload", [falha, falha, Resposta(200, {"success": True})]),
            ("GET", "/C3", Resposta(200, {"status_code": "FINISHED"})),
            ("GET", "/M9", Resposta(200, {"permalink": "https://www.instagram.com/reel/XYZ/"})),
        ])
        with rede.ativar():
            r = self.meta.publicar_instagram(self.Credenciais({"ig_id": "IG1", "page_token": "PT"}), arquivo_de(500), "T", "L")
        self.assertEqual(r.id_externo, "M9")
        publicado = [c for c in rede.chamadas if "media_publish" in c[1]][0]
        self.assertEqual(publicado[2]["data"]["creation_id"], "C3")     # publica o Reel que recebeu o arquivo
        # falhando sempre: desiste, mas como erro temporario (o agendador tenta de novo mais tarde)
        rede = RedeFalsa([("POST", "/IG1/media", Resposta(200, {"id": "C1", "uri": "https://rupload.facebook.com/ig-api-upload/v27.0/C1"})),
                          ("POST", "rupload.facebook.com/ig-api-upload", falha)])
        with rede.ativar():
            with self.assertRaises(ErroPostagem) as erro:
                self.meta.publicar_instagram(self.Credenciais({"ig_id": "IG1", "page_token": "PT"}), arquivo_de(500), "T", "L")
        self.assertTrue(erro.exception.temporario)
        self.assertEqual(sum(1 for c in rede.chamadas if "rupload" in c[1]), self.meta.TENTATIVAS_ENVIO_IG)

    def test_reel_do_instagram_por_link_publico(self):
        arquivo = arquivo_de(700)
        pasta = Path(tempfile.mkdtemp(prefix="publico_"))
        visto = {}

        def criar(_m, _u, kw):
            # no momento em que a Meta e chamada, o video ja esta no link publico
            nome = kw["data"]["video_url"].rsplit("/", 1)[1]
            visto["nome"], visto["existia"] = nome, (pasta / nome).exists()
            return Resposta(200, {"id": "C1"})
        rede = RedeFalsa([
            ("POST", "/IG1/media_publish", Resposta(200, {"id": "M9"})),
            ("POST", "/IG1/media", criar),
            ("GET", "/C1", Resposta(200, {"status_code": "FINISHED"})),
            ("GET", "/M9", Resposta(200, {"permalink": "https://www.instagram.com/reel/XYZ/"})),
        ])
        with mock.patch.object(self.meta.config, "URL_VIDEOS_PUBLICOS", "https://exemplo:8443/videos"), \
                mock.patch.object(self.meta.config, "PASTA_VIDEOS_PUBLICOS", pasta), rede.ativar():
            r = self.meta.publicar_instagram(self.Credenciais({"ig_id": "IG1", "page_token": "PT"}), arquivo, "T", "L")
        self.assertEqual(r.id_externo, "M9")
        criar_chamada = [c for c in rede.chamadas if c[1].endswith("/IG1/media")][0]
        self.assertTrue(criar_chamada[2]["data"]["video_url"].startswith("https://exemplo:8443/videos/"))
        self.assertNotIn("upload_type", criar_chamada[2]["data"])
        self.assertFalse(any("rupload" in c[1] for c in rede.chamadas))
        self.assertTrue(visto["existia"])
        self.assertEqual(list(pasta.glob("*.mp4")), [])          # depois de publicar, o link some

    def test_reel_do_facebook_e_token_invalido(self):
        from app.postagem.redes import ErroPostagem
        arquivo = arquivo_de(1000)
        fases = []

        def reels(_m, _u, kw):
            fases.append(kw["data"]["upload_phase"])
            return Resposta(200, {"video_id": "V1", "upload_url": "https://rupload.facebook.com/video-upload/V1"}) \
                if kw["data"]["upload_phase"] == "start" else Resposta(200, {"success": True})
        rede = RedeFalsa([("POST", "/P1/video_reels", reels),
                          ("POST", "rupload.facebook.com/video-upload", Resposta(200, {"success": True})),
                          ("GET", "/V1", Resposta(200, {"status": {"video_status": "ready"}}))])
        with rede.ativar():
            r = self.meta.publicar_facebook(self.Credenciais({"page_id": "P1", "page_token": "PT"}), arquivo, "T", "L")
        self.assertEqual(fases, ["start", "finish"])
        self.assertEqual(r.url, "https://www.facebook.com/reel/V1")
        finalizar = [c for c in rede.chamadas if c[0] == "POST" and "video_reels" in c[1]][-1]
        self.assertEqual(finalizar[2]["data"]["video_state"], "PUBLISHED")
        vencido = Resposta(400, {"error": {"code": 190, "message": "expired"}})
        with RedeFalsa([("POST", "/P1/video_reels", vencido)]).ativar():
            with self.assertRaises(ErroPostagem) as erro:
                self.meta.publicar_facebook(self.Credenciais({"page_id": "P1", "page_token": "PT"}), arquivo, "T", "L")
        self.assertTrue(erro.exception.reconectar)

    def test_login_traz_pagina_e_instagram(self):
        rede = RedeFalsa([
            ("GET", "oauth/access_token", [Resposta(200, {"access_token": "curto"}), Resposta(200, {"access_token": "longo"})]),
            ("GET", "/me/accounts", Resposta(200, {"data": [{"id": "P1", "name": "Minha Página", "access_token": "PT",
                                                             "instagram_business_account": {"id": "IG1", "username": "minhapagina"}}]})),
        ])
        with rede.ativar():
            contas = self.meta.concluir_login("CODIGO", "http://retorno")
        self.assertEqual([(c["rede"], c["id_externo"], c["nome"]) for c in contas],
                         [("facebook", "P1", "Minha Página"), ("instagram", "IG1", "@minhapagina")])
        self.assertEqual(contas[1]["credenciais"], {"ig_id": "IG1", "page_id": "P1", "page_token": "PT"})


    def test_login_acha_pagina_do_portfolio_empresarial(self):
        # Pagina que mora num portfolio empresarial nao aparece em /me/accounts: vem pelo portfolio,
        # e o token de publicacao dela precisa ser buscado a parte.
        rede = RedeFalsa([
            ("GET", "oauth/access_token", [Resposta(200, {"access_token": "curto"}), Resposta(200, {"access_token": "longo"})]),
            ("GET", "/me/accounts", Resposta(200, {"data": []})),
            ("GET", "/me/businesses", Resposta(200, {"data": [{"id": "B1", "name": "Portfolio"}]})),
            ("GET", "/B1/owned_pages", Resposta(200, {"data": [{"id": "P1", "name": "Minha Página",
                                                               "instagram_business_account": {"id": "IG1", "username": "minhapagina"}}]})),
            ("GET", "/B1/client_pages", Resposta(200, {"data": []})),
            ("GET", "/P1", Resposta(200, {"access_token": "PT"})),
        ])
        with rede.ativar():
            contas = self.meta.concluir_login("CODIGO", "http://retorno")
        self.assertEqual([(c["rede"], c["id_externo"]) for c in contas], [("facebook", "P1"), ("instagram", "IG1")])
        self.assertEqual(contas[1]["credenciais"]["page_token"], "PT")

    def test_login_sem_pagina_explica_o_portfolio(self):
        from app.postagem.redes import ErroPostagem
        rede = RedeFalsa([
            ("GET", "oauth/access_token", [Resposta(200, {"access_token": "curto"}), Resposta(200, {"access_token": "longo"})]),
            ("GET", "/me/accounts", Resposta(200, {"data": []})),
            ("GET", "/me/businesses", Resposta(400, {"error": {"code": 200, "message": "sem permissao"}})),
        ])
        with rede.ativar():
            with self.assertRaises(ErroPostagem) as erro:
                self.meta.concluir_login("CODIGO", "http://retorno")
        self.assertIn("portfólio empresarial", str(erro.exception))


class TesteTikTok(unittest.TestCase):
    def setUp(self):
        from app.postagem import tiktok
        from app.postagem.redes import Credenciais
        self.tt, self.Credenciais = tiktok, Credenciais
        p = mock.patch.object(tiktok, "_dormir", lambda s: None); p.start(); self.addCleanup(p.stop)
        ambiente = mock.patch.dict(os.environ, {"TIKTOK_CLIENT_KEY": "k", "TIKTOK_CLIENT_SECRET": "s"})
        ambiente.start(); self.addCleanup(ambiente.stop)

    def credenciais(self, expira=None):
        import time as relogio
        return self.Credenciais({"access_token": "A", "refresh_token": "R", "expira_em": expira or relogio.time() + 3600})

    def test_plano_de_pedacos_segue_a_documentacao(self):
        mb = self.tt.MB
        self.assertEqual(self.tt.plano_de_pedacos(4 * mb), (4 * mb, 1))             # menor que 5 MB: inteiro
        # Ate 64 MB vai inteiro: o pedaco nunca pode ser maior que o arquivo (era o "chunk size is invalid").
        for tamanho_do_corte in (7 * mb, 16 * mb + 500, 64 * mb):
            self.assertEqual(self.tt.plano_de_pedacos(tamanho_do_corte), (tamanho_do_corte, 1))
        tamanho, quantidade = self.tt.plano_de_pedacos(500_000_123)
        self.assertEqual(quantidade, 500_000_123 // tamanho)
        ultimo = 500_000_123 - (quantidade - 1) * tamanho
        self.assertTrue(5 * mb <= tamanho <= 64 * mb and ultimo <= 128 * mb)

    def test_posta_com_a_privacidade_escolhida(self):
        arquivo = arquivo_de(3000)
        rede = RedeFalsa([
            ("POST", "creator_info/query", Resposta(200, {"data": {"privacy_level_options": ["SELF_ONLY", "FOLLOWER_OF_CREATOR"],
                                                                   "creator_nickname": "eu"}, "error": {"code": "ok"}})),
            ("POST", "video/init", Resposta(200, {"data": {"publish_id": "PUB1", "upload_url": "https://up.tiktok/x"}, "error": {"code": "ok"}})),
            ("PUT", "https://up.tiktok/x", Resposta(201)),
            ("POST", "status/fetch", [Resposta(200, {"data": {"status": "PROCESSING_UPLOAD"}}),
                                      Resposta(200, {"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": []}})]),
        ])
        with rede.ativar():
            r = self.tt.publicar(self.credenciais(), arquivo, "T", "Legenda", {"privacidade": "SELF_ONLY", "comentarios": True})
        self.assertEqual(r.id_externo, "PUB1")
        iniciar = next(c for c in rede.chamadas if "video/init" in c[1])[2]["json"]
        self.assertEqual(iniciar["post_info"]["privacy_level"], "SELF_ONLY")
        self.assertFalse(iniciar["post_info"]["disable_comment"])
        self.assertTrue(iniciar["post_info"]["disable_duet"])                       # desligado por padrao
        self.assertEqual(iniciar["source_info"], {"source": "FILE_UPLOAD", "video_size": 3000, "chunk_size": 3000, "total_chunk_count": 1})
        envio = next(c for c in rede.chamadas if c[0] == "PUT")[2]
        self.assertEqual(envio["headers"]["Content-Range"], "bytes 0-2999/3000")

    def test_recusa_sem_privacidade_ou_com_privacidade_nao_permitida(self):
        from app.postagem.redes import ErroPostagem
        arquivo = arquivo_de(100)
        with self.assertRaises(ErroPostagem):
            self.tt.publicar(self.credenciais(), arquivo, "T", "L", {})
        rede = RedeFalsa([("POST", "creator_info", Resposta(200, {"data": {"privacy_level_options": ["SELF_ONLY"]}, "error": {"code": "ok"}}))])
        with rede.ativar(), self.assertRaises(ErroPostagem):
            self.tt.publicar(self.credenciais(), arquivo, "T", "L", {"privacidade": "PUBLIC_TO_EVERYONE"})

    def test_renova_o_token_e_guarda_o_novo(self):
        credenciais = self.credenciais(expira=1)
        rede = RedeFalsa([("POST", "oauth/token", Resposta(200, {"access_token": "A2", "refresh_token": "R2", "expires_in": 7200})),
                          ("POST", "creator_info", Resposta(200, {"data": {"privacy_level_options": ["SELF_ONLY"]}, "error": {"code": "ok"}}))])
        with rede.ativar():
            self.tt.info_do_criador(credenciais)
        self.assertTrue(credenciais.mudou)
        self.assertEqual((credenciais["access_token"], credenciais["refresh_token"]), ("A2", "R2"))   # o de renovacao muda


class TesteAgendador(unittest.TestCase):
    """Agenda: horarios, aprovacao, regra contra repeticao, publicacao e novas tentativas."""
    VIDEO = Path(__file__).parent / "exemplo_zoo.mp4"

    @classmethod
    def setUpClass(cls):
        from app.postagem import agendador, contas
        cls.ag, cls.contas = agendador, contas

    def setUp(self):
        import shutil, sqlite3
        banco.criar_tabelas()
        with sqlite3.connect(config.ARQUIVO_BANCO) as c:
            c.execute("DELETE FROM publicacoes"); c.execute("DELETE FROM contas")
        self.video_id = banco.registrar_video(1, "youtube", f"agenda{len(self._testMethodName):05d}", "https://www.youtube.com/watch?v=origem00001")
        banco.atualizar_video(self.video_id, titulo="Vídeo de origem", canal="Canal Fonte")
        config.garantir_pastas()
        destino = config.PASTA_CORTES / "agenda" / "corte.mp4"
        destino.parent.mkdir(parents=True, exist_ok=True)
        if not destino.exists():
            shutil.copy(self.VIDEO, destino)
        self.arquivo = config.caminho_relativo(destino)
        self.corte = self.novo_corte("aprovado")
        self.textos = {"titulo": "Título do post", "descricao": "Descrição.", "hashtags": ["GTA6", "Rockstar", "games"]}
        p = mock.patch.object(self.ag.legenda, "escrever", return_value=self.textos); p.start(); self.addCleanup(p.stop)
        self.yt = self.contas.salvar_conta(1, "youtube", "UC1", "Canal YT", None, {"refresh_token": "r"}, 4)
        self.fb = self.contas.salvar_conta(1, "facebook", "P1", "Página", None, {"page_id": "P1", "page_token": "t"}, 4)

    def novo_corte(self, estado):
        corte_id = banco.registrar_corte(1, self.video_id, CorteProposto(1, 2, 0.0, 19.0, 85, "Motivo", "Corte de teste", "original"))
        banco.atualizar_corte(corte_id, estado=estado, caminho_arquivo=self.arquivo)
        return corte_id

    def test_horarios_espacados_na_janela_e_arredondados(self):
        from datetime import date
        horarios = self.ag.horarios_do_dia(date(2026, 11, 14), 4, 9, 22)
        locais = [h.astimezone(self.ag._fuso()) for h in horarios]
        self.assertEqual(len(locais), 4)
        self.assertTrue(all(9 <= h.hour < 22 and h.minute % 5 == 0 for h in locais))
        self.assertEqual(sorted(locais), locais)

    def test_proximos_horarios_pulam_ocupados_e_passado(self):
        conta = self.contas.ler_conta(self.yt)
        primeiros = self.ag.proximos_horarios(conta, 3, 1)
        self.assertEqual(len(primeiros), 3)
        self.assertTrue(all(h > self.ag.agora() for h in primeiros))
        self.contas.criar_publicacao(1, self.yt, origem="corte", corte_id=self.corte, saida_id=None, arquivo=self.arquivo,
                                     chave_video="x", titulo="t", legenda="l", opcoes={}, agendada_para=self.ag.texto(primeiros[0]))
        depois = self.ag.proximos_horarios(conta, 1, 1)
        self.assertEqual(depois[0], primeiros[1])

    def test_intervalo_minimo_entre_posts_da_mesma_conta(self):
        # 8 por dia das 11h as 23h daria um post a cada 90 min; o intervalo do YouTube (210 min) segura
        self.contas.atualizar_conta(self.yt, posts_por_dia=8, rampa=0)
        horarios = sorted(self.ag.proximos_horarios(self.contas.ler_conta(self.yt), 10, 1))
        self.assertEqual(len(horarios), 10)
        self.assertTrue(all((b - a).total_seconds() >= 210 * 60 for a, b in zip(horarios, horarios[1:])))
        locais = [h.astimezone(self.ag._fuso()) for h in horarios]
        self.assertTrue(all(11 <= h.hour < 23 for h in locais))

    def test_meta_do_youtube_cabe_no_dia_com_intervalo_maior_que_o_passo(self):
        # 4 por dia em 12 h daria um a cada 3 h, menos que as 3h30 do YouTube: os 4 ficam a 3h30, todos no mesmo dia
        from datetime import date
        locais = [h.astimezone(self.ag._fuso()) for h in self.ag.horarios_do_dia(date(2026, 11, 20), 4, 11, 23, 210)]
        self.assertEqual(len(locais), 4)
        self.assertTrue(all((b - a).total_seconds() == 210 * 60 for a, b in zip(locais, locais[1:])))
        self.assertTrue(all(11 <= h.hour < 23 and h.minute % 5 == 0 for h in locais))
        # o que nao cabe na janela fica para o dia seguinte (nao aperta o intervalo)
        self.assertEqual(len(self.ag.horarios_do_dia(date(2026, 11, 20), 8, 11, 23, 210)), 4)

    def test_ritmo_padrao_por_rede(self):
        self.assertEqual([banco.ler_config(1, f"posts_dia_{r}") for r in ("youtube", "instagram", "facebook", "tiktok")],
                         [4, 3, 3, 3])
        self.assertEqual([banco.ler_config(1, f"intervalo_{r}_min") for r in ("youtube", "instagram", "facebook", "tiktok")],
                         [210, 150, 150, 180])

    def test_conta_nova_sobe_aos_poucos_ate_a_meta(self):
        from datetime import timedelta
        yt = self.contas.ler_conta(self.yt)
        ig = self.contas.ler_conta(self.contas.salvar_conta(1, "instagram", "IG1", "Insta", None, {"t": "x"}, 3))
        inicio = self.ag._inicio_da_conta(yt)
        dias = [0, 13, 14, 27, 28, 200]
        self.assertEqual([self.ag.ritmo_no_dia(yt, inicio + timedelta(days=d)) for d in dias], [2, 2, 3, 3, 4, 4])
        self.assertEqual([self.ag.ritmo_no_dia(ig, inicio + timedelta(days=d)) for d in dias], [1, 1, 2, 2, 3, 3])
        resumo = self.ag.resumo_ritmo(yt, inicio)
        self.assertEqual((resumo["ritmo_hoje"], resumo["subindo"], resumo["proximo_ritmo"]), (2, True, 3))
        self.assertEqual(resumo["muda_em"], (inicio + timedelta(days=14)).isoformat())
        # meta abaixo do degrau: nunca passa da meta
        self.contas.atualizar_conta(self.yt, posts_por_dia=1)
        self.assertEqual(self.ag.ritmo_no_dia(self.contas.ler_conta(self.yt), inicio), 1)
        # conta ja estabelecida (rampa desligada): meta desde o primeiro dia
        self.contas.atualizar_conta(self.yt, posts_por_dia=4, rampa=0)
        conta = self.contas.ler_conta(self.yt)
        self.assertEqual(self.ag.ritmo_no_dia(conta, inicio), 4)
        self.assertFalse(self.ag.resumo_ritmo(conta, inicio)["subindo"])

    def test_agenda_de_conta_nova_respeita_a_rampa(self):
        horarios = self.ag.proximos_horarios(self.contas.ler_conta(self.yt), 12, 1)
        por_dia = {}
        for h in horarios:
            dia = h.astimezone(self.ag._fuso()).date()
            por_dia[dia] = por_dia.get(dia, 0) + 1
        self.assertTrue(all(n <= 2 for n in por_dia.values()))          # semanas 1 e 2 do YouTube: 2 por dia

    def test_freio_de_seguranca_e_o_dobro_da_meta(self):
        conta = self.contas.ler_conta(self.yt)
        self.assertEqual(self.ag.limite_seguro(conta), 8)
        self.contas.atualizar_conta(self.yt, posts_por_dia=24)
        self.assertEqual(self.ag.limite_seguro(self.contas.ler_conta(self.yt)), 48)
        tiktok = self.contas.ler_conta(self.contas.salvar_conta(1, "tiktok", "TT1", "TT", None, {"t": "x"}, 12))
        self.assertEqual(self.ag.limite_seguro(tiktok), 15)              # nunca acima do teto tecnico da rede

    def test_so_corte_aprovado_e_agendado(self):
        nao_aprovado = self.novo_corte("renderizado")
        with self.assertRaises(self.ag.ErroAgenda):
            self.ag.item_de_corte(nao_aprovado, 1)

    def test_mesmo_corte_nunca_duas_vezes_na_mesma_conta(self):
        item = self.ag.item_de_corte(self.corte, 1)
        primeira = self.ag.agendar(1, [item], [self.yt, self.fb])
        self.assertEqual(len(primeira["criadas"]), 2)
        segunda = self.ag.agendar(1, [item], [self.yt])
        self.assertEqual(segunda["criadas"], [])
        self.assertIn("já foi", segunda["puladas"][0]["motivo"])
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):                       # e o banco tambem trava
            self.contas.criar_publicacao(1, self.yt, origem="corte", corte_id=self.corte, saida_id=None, arquivo=self.arquivo,
                                         chave_video=f"corte:{self.corte}", titulo="t", legenda="l", opcoes={},
                                         agendada_para="2030-01-01 12:00:00")

    def test_variacoes_de_um_corte_sao_espalhadas_entre_contas(self):
        item = self.ag.item_de_corte(self.corte, 1)
        variacoes = [dict(item, frase=f"Frase {i}") for i in range(3)]          # 3 variacoes do MESMO corte
        r = self.ag.agendar(1, variacoes, [self.yt, self.fb], distribuir=True)
        self.assertEqual(sorted(c["conta"] for c in r["criadas"]), ["Canal YT", "Página"])   # 1 por conta
        self.assertEqual(len(r["puladas"]), 1)                                  # a terceira nao repete em ninguem

    def test_legenda_tem_credito_e_hashtags(self):
        self.ag.agendar(1, [self.ag.item_de_corte(self.corte, 1)], [self.yt])
        p = self.contas.listar_publicacoes(1)[0]
        self.assertIn("Fonte: Vídeo de origem — Canal Fonte (https://www.youtube.com/watch?v=origem00001)", p["legenda"])
        self.assertIn("#GTA6", p["legenda"])
        self.assertIn("#Shorts", p["legenda"])

    def test_facebook_recusa_video_mais_longo_que_90s(self):
        import subprocess
        longo = config.PASTA_CORTES / "agenda" / "longo.mp4"
        if not longo.exists():
            subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=160x284:d=95",
                            "-c:v", "libx264", "-preset", "ultrafast", str(longo)], check=True)
        corte = self.novo_corte("aprovado")
        banco.atualizar_corte(corte, caminho_arquivo=config.caminho_relativo(longo))
        r = self.ag.agendar(1, [self.ag.item_de_corte(corte, 1)], [self.yt, self.fb])
        self.assertEqual([c["rede"] for c in r["criadas"]], ["youtube"])
        self.assertIn("3 a 90", r["puladas"][0]["motivo"])

    def test_tiktok_exige_privacidade_e_confirmacao(self):
        tt = self.contas.salvar_conta(1, "tiktok", "OPEN1", "Meu TikTok", None, {"access_token": "a"}, 2)
        item = self.ag.item_de_corte(self.corte, 1)
        with self.assertRaises(self.ag.ErroAgenda):
            self.ag.agendar(1, [item], [tt])
        r = self.ag.agendar(1, [item], [tt], opcoes_por_rede={"tiktok": {"privacidade": "SELF_ONLY", "confirmado": True}})
        self.assertEqual(len(r["criadas"]), 1)

    def test_horario_no_passado_e_recusado(self):
        from datetime import timedelta
        with self.assertRaises(self.ag.ErroAgenda):
            self.ag.agendar(1, [self.ag.item_de_corte(self.corte, 1)], [self.yt], horario=self.ag.agora() - timedelta(hours=1))

    def _agendar_agora(self):
        from datetime import timedelta
        self.ag.agendar(1, [self.ag.item_de_corte(self.corte, 1)], [self.yt], horario=self.ag.agora() + timedelta(minutes=2))
        return self.contas.listar_publicacoes(1)[0]["id"], self.ag.agora() + timedelta(minutes=3)

    def test_publica_na_hora_e_guarda_o_link(self):
        from app.postagem.redes import Resultado
        publicacao, depois = self._agendar_agora()
        publicar = mock.Mock(return_value=Resultado("abc", "https://www.youtube.com/shorts/abc"))
        with mock.patch.dict(self.ag.CONECTORES, {"youtube": publicar}):
            self.assertEqual(self.ag.publicar_vencidas(self.ag.agora()), 0)     # ainda nao e a hora
            self.assertEqual(self.ag.publicar_vencidas(depois), 1)
        p = self.contas.ler_publicacao(publicacao)
        self.assertEqual((p["estado"], p["url"]), ("publicada", "https://www.youtube.com/shorts/abc"))
        argumentos = publicar.call_args.args
        self.assertTrue(str(argumentos[1]).endswith("corte.mp4"))
        self.assertEqual(argumentos[2], "Título do post")

    def test_falha_temporaria_tenta_de_novo_e_depois_desiste(self):
        from datetime import timedelta
        from app.postagem.redes import ErroPostagem
        publicacao, depois = self._agendar_agora()
        falha = mock.Mock(side_effect=ErroPostagem("fora do ar", temporario=True))
        momento = depois
        with mock.patch.dict(self.ag.CONECTORES, {"youtube": falha}):
            for _ in range(self.ag.MAX_TENTATIVAS + 1):
                self.ag.publicar_vencidas(momento)
                momento += timedelta(hours=2)
        p = self.contas.ler_publicacao(publicacao)
        self.assertEqual(p["estado"], "falhou")
        self.assertEqual(falha.call_count, self.ag.MAX_TENTATIVAS + 1)

    def test_acesso_vencido_marca_a_conta(self):
        from app.postagem.redes import ErroPostagem
        publicacao, depois = self._agendar_agora()
        with mock.patch.dict(self.ag.CONECTORES, {"youtube": mock.Mock(side_effect=ErroPostagem("venceu", reconectar=True))}):
            self.ag.publicar_vencidas(depois)
        self.assertEqual(self.contas.ler_conta(self.yt)["estado"], "expirada")
        self.assertEqual(self.contas.ler_publicacao(publicacao)["estado"], "agendada")   # espera reconectar
        with mock.patch.dict(self.ag.CONECTORES, {"youtube": mock.Mock()}) as _:
            self.assertEqual(self.ag.publicar_vencidas(depois), 0)               # conta expirada: nao tenta

    def test_token_renovado_e_guardado(self):
        from app.postagem.redes import Resultado
        publicacao, depois = self._agendar_agora()

        def publica(credenciais, *_):
            credenciais.atualizar(access_token="novo")
            return Resultado("x")
        with mock.patch.dict(self.ag.CONECTORES, {"youtube": publica}):
            self.ag.publicar_vencidas(depois)
        self.assertEqual(self.contas.credenciais_da_conta(self.yt)["access_token"], "novo")

    def test_limite_diario_adia_sem_gastar_tentativa(self):
        publicacao, depois = self._agendar_agora()
        with mock.patch.dict(self.ag.REDES["youtube"], {"limite_diario": 0}), \
             mock.patch.dict(self.ag.CONECTORES, {"youtube": mock.Mock()}) as conectores:
            self.ag.publicar_vencidas(depois)
            conectores["youtube"].assert_not_called()
        p = self.contas.ler_publicacao(publicacao)
        self.assertEqual((p["estado"], p["tentativas"]), ("agendada", 0))
        self.assertIsNotNone(p["proxima_tentativa"])

    def test_modo_automatico_desligado_e_ligado(self):
        bom = self.novo_corte("renderizado")
        self.assertEqual(self.ag.rodar_modo_automatico(1), 0)
        self.assertEqual(banco.ler_corte(bom)["estado"], "renderizado")
        tt = self.contas.salvar_conta(1, "tiktok", "OPEN2", "TikTok", None, {"access_token": "a"}, 2)
        banco.salvar_config(1, "modo_automatico", 1)
        self.addCleanup(banco.salvar_config, 1, "modo_automatico", 0)
        self.assertEqual(self.ag.rodar_modo_automatico(1), 2)                    # YouTube + Facebook, nunca TikTok
        self.assertEqual(banco.ler_corte(bom)["estado"], "aprovado")
        self.assertFalse(any(p["conta_id"] == tt for p in self.contas.listar_publicacoes(1)))


class TestePainelPostagem(unittest.TestCase):
    """Rotas de Contas e Agenda no painel."""

    @classmethod
    def setUpClass(cls):
        os.environ["CANAL_SEM_TRABALHADOR"] = "1"
        from fastapi.testclient import TestClient
        from app.painel import api_postagem, servidor
        from app.postagem import contas
        cls.api, cls.contas = api_postagem, contas
        cls.cliente = TestClient(servidor.criar_app())

    def setUp(self):
        import sqlite3
        banco.criar_tabelas()
        with sqlite3.connect(config.ARQUIVO_BANCO) as c:
            c.execute("DELETE FROM publicacoes"); c.execute("DELETE FROM contas")

    def test_paginas_e_lista_sem_segredos(self):
        self.assertEqual(self.cliente.get("/contas").status_code, 200)
        self.assertEqual(self.cliente.get("/agenda").status_code, 200)
        self.contas.salvar_conta(1, "youtube", "UC9", "Canal", None, {"refresh_token": "SEGREDO-NAO-VAZA"}, 4)
        texto = self.cliente.get("/api/contas").text
        self.assertNotIn("SEGREDO-NAO-VAZA", texto)
        self.assertNotIn("credenciais", texto)

    def test_conectar_sem_app_cadastrado_avisa(self):
        with mock.patch.dict(os.environ, {"YOUTUBE_CLIENT_ID": "", "YOUTUBE_CLIENT_SECRET": ""}):
            r = self.cliente.get("/contas/conectar/youtube", follow_redirects=False)
        self.assertTrue(r.headers["location"].startswith("/contas?erro="))

    def test_login_completo_e_protecao_do_retorno(self):
        with mock.patch.dict(os.environ, {"YOUTUBE_CLIENT_ID": "id", "YOUTUBE_CLIENT_SECRET": "s"}):
            r = self.cliente.get("/contas/conectar/youtube", follow_redirects=False)
        destino = r.headers["location"]
        self.assertTrue(destino.startswith("https://accounts.google.com/"))
        from urllib.parse import parse_qs, urlparse
        estado = parse_qs(urlparse(destino).query)["state"][0]
        # retorno com estado inventado: recusado
        r = self.cliente.get("/contas/retorno/youtube?code=X&state=inventado", follow_redirects=False)
        self.assertIn("erro=", r.headers["location"])
        nova = [{"rede": "youtube", "id_externo": "UC5", "nome": "Canal Novo", "credenciais": {"refresh_token": "r"}}]
        with mock.patch.object(self.api.youtube, "concluir_login", return_value=nova):
            r = self.cliente.get(f"/contas/retorno/youtube?code=X&state={estado}", follow_redirects=False)
            self.assertEqual(r.headers["location"], "/contas?conectadas=1")
            # o mesmo estado nao vale duas vezes
            r = self.cliente.get(f"/contas/retorno/youtube?code=X&state={estado}", follow_redirects=False)
            self.assertIn("erro=", r.headers["location"])
        self.assertEqual([c["nome"] for c in self.contas.listar_contas(1)], ["Canal Novo"])

    def test_ajustar_conta(self):
        conta = self.contas.salvar_conta(1, "youtube", "UC7", "Canal", None, {"refresh_token": "r"}, 4)
        self.assertEqual(self.cliente.put(f"/api/contas/{conta}", json={"posts_por_dia": 8, "ativa": False}).status_code, 200)
        dados = self.contas.ler_conta(conta)
        self.assertEqual((dados["posts_por_dia"], dados["ativa"]), (8, 0))
        self.assertEqual(self.cliente.put(f"/api/contas/{conta}", json={"posts_por_dia": 99}).status_code, 400)
        lida = next(c for c in self.cliente.get("/api/contas").json()["contas"] if c["id"] == conta)
        self.assertEqual((lida["rampa"], lida["ritmo_hoje"], lida["subindo"], lida["limite_seguro"]), (1, 2, True, 16))
        self.assertEqual(self.cliente.put(f"/api/contas/{conta}", json={"rampa": False}).status_code, 200)
        lida = next(c for c in self.cliente.get("/api/contas").json()["contas"] if c["id"] == conta)
        self.assertEqual((lida["rampa"], lida["ritmo_hoje"], lida["subindo"]), (0, 8, False))
        self.assertEqual(self.cliente.delete(f"/api/contas/{conta}").status_code, 200)
        self.assertEqual(self.cliente.put("/api/contas/99999", json={"ativa": True}).status_code, 404)

    def test_configuracao_da_janela_e_do_modo_automatico(self):
        put = lambda **c: self.cliente.put("/api/configuracoes", json=c)   # noqa: E731
        self.assertEqual(put(janela_inicio=23, janela_fim=8).status_code, 400)
        self.assertEqual(put(modo_automatico=1).status_code, 200)
        self.assertEqual(banco.ler_config(1, "modo_automatico"), 1)
        self.assertEqual(put(modo_automatico=0).status_code, 200)
        self.assertEqual(put(modo_automatico=2).status_code, 400)

    def test_agendar_editar_e_cancelar_pelo_painel(self):
        import shutil
        video_id = banco.registrar_video(1, "youtube", "painelpost1", "https://www.youtube.com/watch?v=painelpost1")
        destino = config.PASTA_CORTES / "agenda" / "painel.mp4"
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(Path(__file__).parent / "exemplo_zoo.mp4", destino)
        corte = banco.registrar_corte(1, video_id, CorteProposto(1, 2, 0.0, 19.0, 80, "m", "Corte", "original"))
        banco.atualizar_corte(corte, estado="aprovado", caminho_arquivo=config.caminho_relativo(destino))
        conta = self.contas.salvar_conta(1, "youtube", "UC8", "Canal", None, {"refresh_token": "r"}, 4)
        textos = {"titulo": "Meu título", "descricao": "Descrição curta.", "hashtags": ["GTA6", "games", "Rockstar"]}
        r = self.cliente.post("/api/agendar", json={"cortes": [corte], "contas": [conta], "textos": textos})
        self.assertEqual(len(r.json()["criadas"]), 1, r.text)
        self.assertEqual(self.cliente.post("/api/agendar", json={"cortes": [corte], "contas": [conta], "textos": {"titulo": ""}}).status_code, 400)
        agenda = self.cliente.get("/api/agenda").json()["publicacoes"]
        self.assertEqual(agenda[0]["titulo"], "Meu título")
        pid = agenda[0]["id"]
        self.assertEqual(self.cliente.put(f"/api/publicacoes/{pid}", json={"horario": "2020-01-01T10:00"}).status_code, 400)
        self.assertEqual(self.cliente.put(f"/api/publicacoes/{pid}", json={"legenda": "Nova legenda"}).status_code, 200)
        self.assertEqual(self.cliente.post(f"/api/publicacoes/{pid}/agora").status_code, 200)
        self.assertEqual(self.cliente.post(f"/api/publicacoes/{pid}/cancelar").status_code, 200)
        self.assertEqual(self.cliente.post(f"/api/publicacoes/{pid}/cancelar").status_code, 409)
        self.assertEqual(self.cliente.get(f"/api/publicacoes/{pid}/miniatura.jpg").status_code, 200)
        nao_aprovado = banco.registrar_corte(1, video_id, CorteProposto(3, 4, 0.0, 19.0, 80, "m", "Outro", "original"))
        banco.atualizar_corte(nao_aprovado, caminho_arquivo=config.caminho_relativo(destino))
        r = self.cliente.post("/api/agendar", json={"cortes": [nao_aprovado], "contas": [conta]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("aprovados", r.json()["erro"])


class TesteBuscaDiaria(unittest.TestCase):
    """Fase 6: ranking por velocidade, meta diaria, repetidos, horario da busca e limpeza do disco."""

    @classmethod
    def setUpClass(cls):
        from app.busca import diaria
        cls.d = diaria

    def setUp(self):
        import sqlite3
        banco.criar_tabelas()
        with sqlite3.connect(config.ARQUIVO_BANCO) as c:
            for tabela in ("ranking", "buscas", "canais_monitorados", "fila", "configuracoes"):
                c.execute(f"DELETE FROM {tabela}")
        from datetime import datetime, timezone
        self.agora = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)     # 09:00 em Brasilia

    def cand(self, id_, horas, views, duracao=600, origem="busca", titulo="GTA 6 novo"):
        from datetime import timedelta
        publicado = (self.agora - timedelta(hours=horas)).isoformat()
        return {"id_externo": id_, "titulo": titulo, "canal": "Canal", "views": views, "duracao_s": duracao,
                "publicado": publicado, "origem": origem}

    def test_ranking_ordena_por_velocidade_e_corta_a_janela(self):
        lista = [self.cand("aaaaaaaaaa1", 6, 200_000),        # 33 mil/h
                 self.cand("aaaaaaaaaa2", 700, 1_000_000),    # fora da janela
                 self.cand("aaaaaaaaaa3", 30, 600_000),       # 20 mil/h
                 self.cand("aaaaaaaaaa1", 6, 200_000)]        # repetido
        ranking = self.d.montar_ranking(lista, 48, self.agora)
        self.assertEqual([r["id_externo"] for r in ranking], ["aaaaaaaaaa1", "aaaaaaaaaa3"])
        self.assertAlmostEqual(ranking[0]["velocidade"], 33333.3, delta=1)

    def test_filtro_de_titulo_so_aceita_gta_6(self):
        self.assertTrue(self.d.TITULO_GTA.search("GTA VI trailer"))
        self.assertFalse(self.d.TITULO_GTA.search("GTA V mods"))

    def test_titulo_com_spoiler_da_historia_nao_vai_para_a_fila(self):
        for titulo in ("GTA 6 ENDING explained", "GTA 6 - Final do jogo", "GTA VI all cutscenes (game movie)",
                       "GTA 6 filme completo dublado"):
            item = dict(self.cand("ccccccccc01", 5, 500_000), titulo=titulo)
            self.assertEqual(self.d._motivo_de_descarte(item, 1), ("ignorado", "O título indica spoiler da história"))
        for titulo in ("GTA 6 trailer final", "GTA 6: 10 segredos que você não viu", "GTA 6 gameplay da primeira missão"):
            item = dict(self.cand("ccccccccc02", 5, 500_000), titulo=titulo)
            self.assertIsNone(self.d._motivo_de_descarte(item, 1))

    def test_rodar_enfileira_ate_a_meta_e_pula_repetidos_e_longos(self):
        banco.salvar_config(1, "meta_cortes_dia", 8)          # media 4 cortes por video -> 2 videos
        banco.registrar_video(1, "youtube", "bbbbbbbbbb1", "https://www.youtube.com/watch?v=bbbbbbbbbb1")
        lista = [self.cand("bbbbbbbbbb1", 4, 900_000),                     # ja processado
                 self.cand("bbbbbbbbbb2", 5, 800_000, duracao=9000),       # longo demais
                 self.cand("bbbbbbbbbb3", 6, 700_000),
                 self.cand("bbbbbbbbbb4", 7, 600_000),
                 self.cand("bbbbbbbbbb5", 8, 500_000)]
        r = self.d.rodar(1, coletor=lambda: lista, agora=self.agora)
        self.assertEqual(r["enfileirados"], 2)
        destinos = {x["id_externo"]: x["destino"] for x in self.d.ranking_da_busca(r["busca_id"])}
        self.assertEqual(destinos["bbbbbbbbbb1"], "ja_processado")
        self.assertEqual(destinos["bbbbbbbbbb2"], "ignorado")
        self.assertEqual(destinos["bbbbbbbbbb3"], "enfileirado")
        self.assertEqual(destinos["bbbbbbbbbb5"], "fora_da_meta")
        self.assertEqual(len(banco.listar_fila(1)), 2)
        # uma segunda busca no mesmo dia nao passa da meta
        self.assertEqual(self.d.rodar(1, coletor=lambda: lista, agora=self.agora)["enfileirados"], 0)

    def test_sem_enfileirar_so_mostra_o_ranking(self):
        r = self.d.rodar(1, enfileirar=False, coletor=lambda: [self.cand("cccccccccc1", 3, 90_000)], agora=self.agora)
        self.assertEqual(r["enfileirados"], 0)
        self.assertEqual(banco.listar_fila(1), [])

    def test_aceleracao_compara_com_a_busca_anterior(self):
        from datetime import timedelta
        self.d.rodar(1, enfileirar=False, coletor=lambda: [self.cand("dddddddddd1", 5, 100_000)], agora=self.agora)
        depois = self.agora + timedelta(hours=10)
        item = self.cand("dddddddddd1", 15, 600_000)
        item["publicado"] = (self.agora - timedelta(hours=5)).isoformat()
        r = self.d.rodar(1, enfileirar=False, coletor=lambda: [item], agora=depois)
        linha = self.d.ranking_da_busca(r["busca_id"])[0]
        self.assertAlmostEqual(linha["aceleracao"], 50_000, delta=1)

    def test_busca_sem_resultado_registra_falha(self):
        with self.assertRaises(RuntimeError):
            self.d.rodar(1, coletor=lambda: [], agora=self.agora)
        self.assertEqual(self.d.ultima_busca(1)["estado"], "falhou")

    def test_horario_da_busca_automatica(self):
        from datetime import datetime, timedelta, timezone
        cedo = datetime(2026, 11, 13, 8, 0, tzinfo=timezone.utc)        # 05:00 em Brasilia
        self.assertFalse(self.d.deve_rodar(1, self.agora))             # desligada por padrao
        banco.salvar_config(1, "busca_ativa", 1)
        self.assertFalse(self.d.deve_rodar(1, cedo))                   # antes das 6h
        self.assertTrue(self.d.deve_rodar(1, self.agora))
        self.assertTrue(self.d.rodar_se_for_hora(1, self.agora, coletor=lambda: [self.cand("eeeeeeeeee1", 3, 90_000)]))
        self.assertFalse(self.d.deve_rodar(1, self.agora + timedelta(hours=2)))   # ja rodou hoje
        self.assertTrue(self.d.deve_rodar(1, self.agora + timedelta(days=1)))     # amanha roda de novo

    def test_falha_tenta_de_novo_depois_de_30_minutos_e_para_em_3(self):
        from datetime import timedelta
        banco.salvar_config(1, "busca_ativa", 1)
        for n in range(3):
            momento = self.agora + timedelta(minutes=40 * n)
            self.assertTrue(self.d.deve_rodar(1, momento))
            self.d.rodar_se_for_hora(1, momento, coletor=lambda: [])
            self.assertFalse(self.d.deve_rodar(1, momento + timedelta(minutes=5)))
        self.assertFalse(self.d.deve_rodar(1, self.agora + timedelta(hours=5)))

    def test_limpeza_apaga_so_os_brutos_antigos(self):
        import os as _os
        from datetime import timedelta
        config.garantir_pastas()
        velho, novo = config.PASTA_BRUTOS / "velho_limpeza.mp4", config.PASTA_BRUTOS / "novo_limpeza.mp4"
        for arquivo in (velho, novo):
            arquivo.write_bytes(b"x")
        antigo = (self.agora - timedelta(days=9)).timestamp()
        _os.utime(velho, (antigo, antigo))
        recente = (self.agora - timedelta(days=0.5)).timestamp()
        _os.utime(novo, (recente, recente))
        id_velho = banco.registrar_video(1, "youtube", "ffffffffff1", "https://www.youtube.com/watch?v=ffffffffff1")
        id_novo = banco.registrar_video(1, "youtube", "ffffffffff2", "https://www.youtube.com/watch?v=ffffffffff2")
        banco.atualizar_video(id_velho, caminho_arquivo=config.caminho_relativo(velho), estado="pronto")
        banco.atualizar_video(id_novo, caminho_arquivo=config.caminho_relativo(novo), estado="pronto")
        self.assertEqual(self.d.limpar_brutos(1, self.agora), 1)
        self.assertFalse(velho.exists())
        self.assertTrue(novo.exists())
        self.assertIsNone(banco.ler_video(id_velho)["caminho_arquivo"])
        self.assertIsNotNone(banco.ler_video(id_novo)["caminho_arquivo"])


class TestePainelHoje(unittest.TestCase):
    """Tela Hoje: pagina, ranking, gerar cortes de um video e canais."""

    @classmethod
    def setUpClass(cls):
        os.environ["CANAL_SEM_TRABALHADOR"] = "1"
        from fastapi.testclient import TestClient
        from app.busca import diaria
        from app.painel import servidor
        cls.d = diaria
        cls.cliente = TestClient(servidor.criar_app())

    def setUp(self):
        import sqlite3
        banco.criar_tabelas()
        with sqlite3.connect(config.ARQUIVO_BANCO) as c:
            for tabela in ("ranking", "buscas", "canais_monitorados", "fila"):
                c.execute(f"DELETE FROM {tabela}")

    def test_pagina_e_ranking_vazio(self):
        self.assertEqual(self.cliente.get("/hoje").status_code, 200)
        dados = self.cliente.get("/api/hoje").json()
        self.assertEqual(dados["ranking"], [])
        self.assertFalse(dados["ativa"])

    def test_ranking_e_gerar_cortes(self):
        from datetime import datetime, timedelta, timezone
        agora = datetime.now(timezone.utc)
        item = {"id_externo": "gggggggggg1", "titulo": "GTA 6 vídeo", "canal": "C", "views": 50_000, "duracao_s": 300,
                "publicado": (agora - timedelta(hours=4)).isoformat(), "origem": "busca"}
        self.d.rodar(1, enfileirar=False, coletor=lambda: [item])
        dados = self.cliente.get("/api/hoje").json()
        self.assertEqual(dados["ranking"][0]["destino"], "fora_da_meta")
        self.assertEqual(self.cliente.post("/api/hoje/processar", json={"id": "gggggggggg1"}).status_code, 200)
        self.assertEqual(self.cliente.post("/api/hoje/processar", json={"id": "gggggggggg1"}).status_code, 409)
        self.assertEqual(self.cliente.post("/api/hoje/processar", json={"id": "naoexiste01"}).status_code, 404)
        self.assertEqual(len(banco.listar_fila(1)), 1)

    def test_canais_acompanhados(self):
        falso = {"canal": {"nome": "Canal Teste"}, "posts": []}
        with mock.patch("app.busca.perfil.listar", return_value=falso):
            r = self.cliente.post("/api/canais", json={"url": "@canalteste"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.cliente.get("/api/hoje").json()["canais"][0]["nome"], "Canal Teste")
        self.assertEqual(self.cliente.delete(f"/api/canais/{r.json()['canal']['id']}").status_code, 200)
        self.assertEqual(self.cliente.get("/api/hoje").json()["canais"], [])
        self.assertEqual(self.cliente.post("/api/canais", json={"url": "https://instagram.com/x"}).status_code, 400)

    def test_configuracoes_da_busca_aparecem(self):
        chaves = {v["chave"] for v in self.cliente.get("/api/configuracoes").json()["valores"]}
        self.assertTrue({"busca_ativa", "busca_hora", "meta_cortes_dia", "apagar_brutos_dias"} <= chaves)


class TesteAvisos(unittest.TestCase):
    """Fase 7: avisos no Telegram so quando ligados, sem repetir e sem vazar o token."""

    def setUp(self):
        from app import avisos
        self.av = avisos
        avisos._enviados.clear()

    def test_desligado_nao_manda_nada(self):
        with mock.patch.dict(os.environ, {"CANAL_AVISOS": "", "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}), \
                mock.patch("app.avisos.requests.post") as post:
            self.assertFalse(self.av.avisar("oi", esperar=True))
        post.assert_not_called()

    def test_ligado_manda_uma_vez_por_chave(self):
        ambiente = {"CANAL_AVISOS": "1", "TELEGRAM_BOT_TOKEN": "TOKEN-SECRETO", "TELEGRAM_CHAT_ID": "123"}
        with mock.patch.dict(os.environ, ambiente), \
                mock.patch("app.avisos.requests.post", return_value=SimpleNamespace(status_code=200)) as post:
            self.assertTrue(self.av.avisar("Falhou X", chave="x", esperar=True))
            self.assertFalse(self.av.avisar("Falhou X de novo", chave="x", esperar=True))
            self.assertTrue(self.av.avisar("Outra coisa", chave="y", esperar=True))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["json"]["chat_id"], "123")

    def test_erro_de_rede_nao_quebra_nem_mostra_o_token(self):
        import requests as _requests
        ambiente = {"CANAL_AVISOS": "1", "TELEGRAM_BOT_TOKEN": "TOKEN-SECRETO", "TELEGRAM_CHAT_ID": "123"}
        with mock.patch.dict(os.environ, ambiente), \
                mock.patch("app.avisos.requests.post", side_effect=_requests.ConnectionError("https://api.telegram.org/botTOKEN-SECRETO")), \
                self.assertLogs("canal.avisos", level="WARNING") as registro:
            self.assertFalse(self.av.avisar("oi", esperar=True))
        self.assertNotIn("TOKEN-SECRETO", "\n".join(registro.output))

    def test_falha_da_busca_avisa(self):
        from app.busca import diaria
        banco.criar_tabelas()
        with mock.patch.object(diaria.avisos, "avisar") as avisar, self.assertRaises(RuntimeError):
            diaria.rodar(1, coletor=lambda: [])
        self.assertIn("busca", avisar.call_args.args[0])


class TesteVps(unittest.TestCase):
    """Fase 7: painel de testes no computador e o que vai (e nao vai) para a VPS."""

    def test_painel_de_teste_nao_liga_publicador_nem_busca(self):
        from fastapi.testclient import TestClient
        from app.painel import servidor
        ambiente = {"CANAL_SEM_TRABALHADOR": "0", "CANAL_PAINEL_DE_TESTE": "1"}
        with mock.patch.dict(os.environ, ambiente), \
                mock.patch.object(servidor.fila.Trabalhador, "start") as trab, \
                mock.patch.object(servidor.agendador.Publicador, "start") as pub, \
                mock.patch.object(servidor.diaria.Buscador, "start") as bus:
            with TestClient(servidor.criar_app()) as cliente:
                self.assertIn("Painel de <b>testes</b>", cliente.get("/cortes").text)
        trab.assert_called_once()
        pub.assert_not_called()
        bus.assert_not_called()

    def test_env_da_vps_nao_leva_linhas_do_computador(self):
        import importlib.util
        especificacao = importlib.util.spec_from_file_location("publicar", Path(__file__).parent.parent / "deploy" / "publicar.py")
        publicar = importlib.util.module_from_spec(especificacao)
        especificacao.loader.exec_module(publicar)
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / ".env").write_text("ANTHROPIC_API_KEY=a\nCANAL_PAINEL_DE_TESTE=1\nCANAL_URL_PAINEL=http://127.0.0.1:8000\n"
                                       "CANAL_VPS=ubuntu@1.2.3.4\nCANAL_CHAVE_SECRETA=k\n", encoding="utf-8")
            with mock.patch.object(publicar, "RAIZ", raiz):
                texto = publicar._env_para_vps(raiz).read_text(encoding="utf-8")
        self.assertIn("ANTHROPIC_API_KEY=a", texto)
        self.assertIn("CANAL_CHAVE_SECRETA=k", texto)
        self.assertNotIn("CANAL_PAINEL_DE_TESTE", texto)
        self.assertNotIn("CANAL_URL_PAINEL", texto)
        self.assertNotIn("CANAL_VPS", texto)

    def test_scripts_da_vps_tem_fim_de_linha_do_linux(self):
        import subprocess as _sp
        raiz = Path(__file__).parent.parent
        for nome in ("deploy/instalar_vps.sh", "deploy/canal-dark.service"):
            atributo = _sp.run(["git", "check-attr", "eol", nome], cwd=raiz, capture_output=True, text=True).stdout
            self.assertIn("eol: lf", atributo, nome)


class TesteChaves(unittest.TestCase):
    """Area "Chaves e integracoes": grava no .env, nunca devolve o valor, e a publicacao nao apaga as da VPS."""

    @classmethod
    def setUpClass(cls):
        os.environ["CANAL_SEM_TRABALHADOR"] = "1"
        from fastapi.testclient import TestClient
        from app import chaves
        from app.painel import servidor
        cls.ch = chaves
        cls.cliente = TestClient(servidor.criar_app())

    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.env = Path(self.pasta.name) / ".env"
        self.env.write_text("ANTHROPIC_API_KEY=a\n# comentario\n", encoding="utf-8")
        p = mock.patch.object(self.ch, "_arquivo", return_value=self.env); p.start(); self.addCleanup(p.stop)
        nomes = [n for n in self.ch.NOMES]
        guardados = {n: os.environ.get(n) for n in nomes}
        def restaurar():
            for n, v in guardados.items():
                if v is None: os.environ.pop(n, None)
                else: os.environ[n] = v
        self.addCleanup(restaurar)

    def test_salvar_troca_limpa_e_apaga(self):
        self.ch.salvar("YOUTUBE_CLIENT_ID", '  "123-abc.apps.googleusercontent.com" ')
        self.assertIn("YOUTUBE_CLIENT_ID=123-abc.apps.googleusercontent.com", self.env.read_text(encoding="utf-8"))
        self.assertEqual(os.environ["YOUTUBE_CLIENT_ID"], "123-abc.apps.googleusercontent.com")
        self.ch.salvar("YOUTUBE_CLIENT_ID", "outro-valor-1234")
        self.assertEqual(self.env.read_text(encoding="utf-8").count("YOUTUBE_CLIENT_ID="), 1)
        self.ch.salvar("YOUTUBE_CLIENT_ID", "")
        self.assertNotIn("YOUTUBE_CLIENT_ID", self.env.read_text(encoding="utf-8"))
        self.assertIsNone(os.environ.get("YOUTUBE_CLIENT_ID"))
        self.assertIn("# comentario", self.env.read_text(encoding="utf-8"))

    def test_recusa_valor_estranho_e_chave_desconhecida(self):
        with self.assertRaises(self.ch.ErroChave):
            self.ch.salvar("YOUTUBE_CLIENT_ID", "tem espaco no meio")
        with self.assertRaises(self.ch.ErroChave):
            self.ch.salvar("YOUTUBE_CLIENT_ID", "abc\nCANAL_CHAVE_SECRETA=x")
        with self.assertRaises(self.ch.ErroChave):
            self.ch.salvar("CANAL_CHAVE_SECRETA", "qualquer-coisa")
        with self.assertRaises(self.ch.ErroChave):
            self.ch.salvar("META_APP_ID", "nao-e-numero")

    def test_painel_nunca_devolve_o_valor(self):
        r = self.cliente.put("/api/chaves", json={"nome": "META_APP_SECRET", "valor": "SEGREDO-NAO-VAZA-123"})
        self.assertEqual(r.status_code, 200)
        texto = self.cliente.get("/api/chaves").text
        self.assertNotIn("SEGREDO-NAO-VAZA-123", texto)
        estado = {c["nome"]: c["preenchida"] for c in self.cliente.get("/api/chaves").json()["chaves"]}
        self.assertTrue(estado["META_APP_SECRET"])
        self.assertIn("/contas/retorno/youtube", texto)
        self.assertEqual(self.cliente.put("/api/chaves", json={"nome": "X", "valor": "y"}).status_code, 400)

    def test_recusa_pedido_de_outro_site(self):
        r = self.cliente.put("/api/chaves", json={"nome": "META_APP_SECRET", "valor": "abc12345"},
                             headers={"Origin": "https://site-malicioso.com"})
        self.assertEqual(r.status_code, 403)

    def test_publicacao_mantem_as_chaves_da_vps(self):
        pasta = Path(self.pasta.name)
        novo, atual = pasta / "novo", pasta / "atual"
        novo.write_text("ANTHROPIC_API_KEY=nova\nYOUTUBE_CLIENT_ID=\nCANAL_CHAVE_SECRETA=outra\nOUTRA=1\n", encoding="utf-8")
        atual.write_text("ANTHROPIC_API_KEY=da-vps\nYOUTUBE_CLIENT_ID=id-da-vps\nCANAL_CHAVE_SECRETA=cofre-vps\nVELHA=2\n",
                         encoding="utf-8")
        mantidas = self.ch.juntar(novo, atual)
        valores = self.ch._valores(atual.read_text(encoding="utf-8").splitlines())
        self.assertEqual(valores["YOUTUBE_CLIENT_ID"], "id-da-vps")
        self.assertEqual(valores["CANAL_CHAVE_SECRETA"], "cofre-vps")
        self.assertEqual(valores["ANTHROPIC_API_KEY"], "da-vps")
        self.assertEqual(valores["OUTRA"], "1")
        self.assertNotIn("VELHA", valores)
        self.assertIn("CANAL_CHAVE_SECRETA", mantidas)
        # primeira publicacao: a VPS ainda nao tem .env
        (pasta / "vazio").write_text("", encoding="utf-8")
        primeiro = pasta / "primeiro"
        self.ch.juntar(novo, primeiro)
        self.assertIn("ANTHROPIC_API_KEY=nova", primeiro.read_text(encoding="utf-8"))

    def test_telegram_descobrir_salva_a_conversa(self):
        from app import avisos
        os.environ["TELEGRAM_BOT_TOKEN"] = "123:abc"
        resposta = SimpleNamespace(json=lambda: {"ok": True, "result": [{"message": {"chat": {"id": 987654}}}]})
        with mock.patch("app.avisos.requests.get", return_value=resposta):
            self.assertEqual(self.cliente.post("/api/chaves/telegram/descobrir").status_code, 200)
        self.assertIn("TELEGRAM_CHAT_ID=987654", self.env.read_text(encoding="utf-8"))
        vazio = SimpleNamespace(json=lambda: {"ok": True, "result": []})
        with mock.patch("app.avisos.requests.get", return_value=vazio):
            r = self.cliente.post("/api/chaves/telegram/descobrir")
        self.assertEqual(r.status_code, 400)
        self.assertIn("oi", r.json()["erro"])
        self.assertTrue(avisos.ligado() or os.getenv("CANAL_AVISOS") != "1")


if __name__ == "__main__":
    unittest.main()
