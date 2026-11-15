"""Testes da Fase 8 (Desempenho). Nao usam internet nem gastam credito de API.

Rodar:
    .venv\\Scripts\\python.exe -m unittest testes.teste_desempenho -v
"""
import itertools
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

# Pasta de dados temporaria, para nunca mexer no banco de verdade (se teste_base ja rodou, usa a dele).
if "CANAL_PASTA_DADOS" not in os.environ:
    _PASTA = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    os.environ["CANAL_PASTA_DADOS"] = _PASTA.name
if "CANAL_CHAVE_SECRETA" not in os.environ:
    from cryptography.fernet import Fernet
    os.environ["CANAL_CHAVE_SECRETA"] = Fernet.generate_key().decode()

from app import banco, config  # noqa: E402
from app.contratos import CorteProposto  # noqa: E402
from app.desempenho import repositorio  # noqa: E402
from app.postagem import agendador, contas  # noqa: E402
from app.postagem.redes import Credenciais, ErroPostagem, Numeros  # noqa: E402

_contador = itertools.count(1)
SEMPRE = ("2000-01-01 00:00:00", "2100-01-01 00:00:00")


def limpar() -> None:
    banco.criar_tabelas()
    with closing(sqlite3.connect(config.ARQUIVO_BANCO)) as c, c:
        c.execute("DELETE FROM leituras")
        c.execute("DELETE FROM publicacoes")
        c.execute("DELETE FROM contas")
        c.execute("DELETE FROM narracoes")
        c.execute("DELETE FROM cortes WHERE video_id IN (SELECT id FROM videos WHERE id_externo LIKE 'desemp%')")
        c.execute("DELETE FROM videos WHERE id_externo LIKE 'desemp%'")


def agora_texto() -> str:
    return agendador.texto(agendador.agora())


def criar_conta(rede: str = "youtube", nome: str = "Canal") -> int:
    return contas.salvar_conta(1, rede, f"conta{next(_contador)}", nome, None, {"access_token": "A"}, 4)


def criar_corte(modo: str = "narrado", nota: int = 80, canal: str = "Canal X") -> int:
    n = next(_contador)
    video = banco.registrar_video(1, "youtube", f"desemp{n:05d}", f"https://www.youtube.com/watch?v=desemp{n:05d}")
    banco.atualizar_video(video, titulo=f"Video {n}", canal=canal)
    corte = banco.registrar_corte(1, video, CorteProposto(0, 3, 0.0, 30.0, nota, "Motivo.", f"Corte {n}", modo))
    banco.atualizar_corte(corte, estado="aprovado")
    return corte


def publicar(conta_id: int, horas_atras: float, corte_id: int | None = None, origem: str = "corte",
             id_externo: str | None = None) -> int:
    n = next(_contador)
    quando = agendador.texto(agendador.agora() - timedelta(hours=horas_atras))
    p = contas.criar_publicacao(1, conta_id, origem=origem, corte_id=corte_id, saida_id=None, arquivo="x.mp4",
                                chave_video=f"teste:{n}", titulo=f"Post {n}", legenda="", opcoes={},
                                agendada_para=quando)
    contas.atualizar_publicacao(p, estado="publicada", id_externo=id_externo or f"ext{n}",
                                url=f"https://exemplo/{n}", publicado_em=quando)
    return p


def agendar_post(conta_id: int) -> int:
    n = next(_contador)
    return contas.criar_publicacao(1, conta_id, origem="corte", corte_id=None, saida_id=None, arquivo="x.mp4",
                                   chave_video=f"teste:{n}", titulo=f"Agendado {n}", legenda="", opcoes={},
                                   agendada_para=agendador.texto(agendador.agora() + timedelta(hours=5)))


def leituras_de(publicacao_id: int) -> dict:
    linha = next(l for l in repositorio.linhas_do_relatorio(1, *SEMPRE) if l["id"] == publicacao_id)
    return linha["leituras"]


def resposta_http(status: int, dados: dict):
    return SimpleNamespace(status_code=status, json=lambda: dados, headers={})


class TesteRepositorio(unittest.TestCase):
    def setUp(self):
        limpar()
        self.conta = criar_conta()

    def test_grava_e_regrava_a_mesma_leitura(self):
        p = publicar(self.conta, 2)
        repositorio.gravar_leitura(1, p, "atual", Numeros(100, 5, 1), "2026-11-14 10:00:00")
        repositorio.gravar_leitura(1, p, "atual", Numeros(150, 6, None), "2026-11-14 11:00:00")
        self.assertEqual(leituras_de(p), {"atual": Numeros(150, 6, None)})

    def test_marco_desconhecido_e_recusado(self):
        with self.assertRaises(ValueError):
            repositorio.gravar_leitura(1, publicar(self.conta, 2), "2d", Numeros(), "2026-11-14 10:00:00")

    def test_marcos_gravados(self):
        p, q = publicar(self.conta, 2), publicar(self.conta, 2)
        repositorio.gravar_leitura(1, p, "atual", Numeros(1, 1, 1), "2026-11-14 10:00:00")
        repositorio.gravar_leitura(1, p, "24h", Numeros(1, 1, 1), "2026-11-14 10:00:00")
        self.assertEqual(repositorio.marcos_gravados([p, q]), {p: {"atual", "24h"}, q: set()})

    def test_para_ler_so_traz_publicadas_recentes_e_nao_removidas(self):
        recente, _velha, removida = publicar(self.conta, 5), publicar(self.conta, 200), publicar(self.conta, 5)
        agendar_post(self.conta)                          # fica 'agendada': nao entra
        repositorio.marcar_removida(removida, agora_texto())
        lidas = repositorio.publicacoes_para_ler(agora_texto(), 170)
        self.assertEqual([p["id"] for p in lidas], [recente])
        self.assertEqual(set(lidas[0]), {"id", "usuario_id", "conta_id", "rede", "id_externo", "publicado_em"})

    def test_conta_vencida_fica_fora_da_leitura(self):
        publicar(self.conta, 5)
        contas.atualizar_conta(self.conta, estado="expirada")
        self.assertEqual(repositorio.publicacoes_para_ler(agora_texto(), 170), [])

    def test_linha_do_relatorio_traz_corte_e_fonte(self):
        corte = criar_corte(modo="original", nota=72, canal="Canal Y")
        publicar(self.conta, 5, corte_id=corte)
        linha = repositorio.linhas_do_relatorio(1, *SEMPRE)[0]
        self.assertEqual((linha["modo"], linha["nota"], linha["fonte"], linha["rede"], linha["conta_nome"]),
                         ("original", 72, "Canal Y", "youtube", "Canal"))

    def test_linha_sem_corte_tem_campos_vazios(self):
        publicar(self.conta, 5, origem="template")
        linha = repositorio.linhas_do_relatorio(1, *SEMPRE)[0]
        self.assertEqual((linha["modo"], linha["nota"], linha["fonte"], linha["origem"]), (None, None, None, "template"))

    def test_relatorio_respeita_o_intervalo_e_a_conta(self):
        outra = criar_conta(nome="Outra")
        publicar(self.conta, 5); publicar(outra, 5); publicar(self.conta, 300)
        desde = agendador.texto(agendador.agora() - timedelta(days=7))
        self.assertEqual(len(repositorio.linhas_do_relatorio(1, desde, agora_texto())), 2)
        self.assertEqual(len(repositorio.linhas_do_relatorio(1, desde, agora_texto(), conta_id=outra)), 1)

    def test_visualizacoes_por_corte_soma_os_posts(self):
        corte = criar_corte()
        outra = criar_conta("instagram", "Insta")
        a, b = publicar(self.conta, 5, corte_id=corte), publicar(outra, 5, corte_id=corte)
        repositorio.gravar_leitura(1, a, "atual", Numeros(1000, 1, 1), "2026-11-14 10:00:00")
        repositorio.gravar_leitura(1, b, "atual", Numeros(None, 9, 2), "2026-11-14 10:00:00")
        self.assertEqual(repositorio.visualizacoes_por_corte(1), {corte: 1000})

    def test_banco_antigo_ganha_a_coluna(self):
        banco.criar_tabelas()
        banco.criar_tabelas()                         # roda duas vezes sem erro
        with closing(banco.conectar()) as c:
            self.assertIn("removida_em", [l["name"] for l in c.execute("PRAGMA table_info(publicacoes)")])


class TesteNumerosYoutube(unittest.TestCase):
    def setUp(self):
        from app.postagem import youtube
        self.yt = youtube
        renovar = mock.patch.object(youtube, "_renovar", return_value="TOKEN")
        renovar.start()
        self.addCleanup(renovar.stop)
        self.cred = Credenciais({"access_token": "A", "refresh_token": "R"})

    def test_le_numeros_e_deixa_vazio_o_que_a_rede_esconde(self):
        resposta = resposta_http(200, {"items": [
            {"id": "aaa", "statistics": {"viewCount": "1200", "likeCount": "80", "commentCount": "7"}},
            {"id": "bbb", "statistics": {"viewCount": "15"}}]})
        with mock.patch.object(self.yt, "chamar", return_value=resposta) as chamar:
            numeros = self.yt.ler_numeros(self.cred, ["aaa", "bbb", "sumiu"])
        self.assertEqual(numeros, {"aaa": Numeros(1200, 80, 7), "bbb": Numeros(15, None, None)})
        self.assertEqual(chamar.call_args.kwargs["params"], {"part": "statistics", "id": "aaa,bbb,sumiu"})
        self.assertEqual(chamar.call_args.kwargs["headers"], {"Authorization": "Bearer TOKEN"})

    def test_lotes_de_50(self):
        with mock.patch.object(self.yt, "chamar", return_value=resposta_http(200, {"items": []})) as chamar:
            self.yt.ler_numeros(self.cred, [f"v{i}" for i in range(120)])
        self.assertEqual(chamar.call_count, 3)

    def test_lista_vazia_nao_chama_a_rede(self):
        with mock.patch.object(self.yt, "chamar") as chamar:
            self.assertEqual(self.yt.ler_numeros(self.cred, []), {})
        chamar.assert_not_called()

    def test_403_nao_pede_reconexao(self):
        erro = {"error": {"message": "sem permissao", "errors": [{"reason": "insufficientPermissions"}]}}
        with mock.patch.object(self.yt, "chamar", return_value=resposta_http(403, erro)):
            with self.assertRaises(ErroPostagem) as c:
                self.yt.ler_numeros(self.cred, ["aaa"])
        self.assertFalse(c.exception.reconectar)
        self.assertFalse(c.exception.temporario)

    def test_cota_estourada_e_temporaria(self):
        erro = {"error": {"message": "cota", "errors": [{"reason": "quotaExceeded"}]}}
        with mock.patch.object(self.yt, "chamar", return_value=resposta_http(403, erro)):
            with self.assertRaises(ErroPostagem) as c:
                self.yt.ler_numeros(self.cred, ["aaa"])
        self.assertTrue(c.exception.temporario)


if __name__ == "__main__":
    unittest.main()
