# Desempenho (Fase 8) — Plano de construção

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O painel lê nas redes as visualizações, curtidas e comentários de cada post publicado e mostra, numa tela Desempenho e nos cartões da tela Cortes, o que está funcionando.

**Architecture:** Cada conector de rede em `app/postagem/` ganha uma função `ler_numeros`. Um coletor em `app/desempenho/` roda de hora em hora numa thread própria do painel (separada do publicador), grava as leituras na tabela nova `leituras` e nunca altera o estado de um post. Um módulo de relatório transforma as leituras nos números da tela; a tela é HTML/JS puro, como as outras.

**Tech Stack:** Python 3.12, SQLite, FastAPI + Jinja2, `requests` (via `app.postagem.redes.chamar`), `unittest` + `unittest.mock`, JS sem bibliotecas.

**Spec:** `docs/superpowers/specs/2026-11-14-desempenho-design.md` (ler antes de começar, junto com `CLAUDE.md` e `plano.md`).

## Global Constraints

- Nenhuma chamada de IA nesta fase. Nenhuma permissão nova no login das redes.
- A leitura nunca muda `estado`, `agendada_para`, `tentativas` nem `erro` de uma publicação. O único campo de `publicacoes` que ela grava é `removida_em`.
- Número que a rede não informa é `None` (vazio), nunca `0`.
- Média de grupo com menos de **3** posts não é mostrada: texto **"poucos dados"**.
- Leitura de hora em hora (**3600 s**), só de posts publicados há menos de **170 h** (7 dias + 2 h de folga). Fotos: `24h` = 24 h, `3d` = 72 h, `7d` = 168 h, com tolerância de **6 h**.
- Horários no banco em UTC, formato `AAAA-MM-DD HH:MM:SS` (usar `agendador.texto` / `agendador.momento`). Na tela, horário de `config.FUSO`.
- Toda tabela tem `usuario_id`. Caminhos com `pathlib`. Tokens nunca vão para o log.
- Nomes de arquivos, funções e comentários em português, sem acentos nos nomes de arquivo. Textos da tela em português do Brasil, simples.
- Tela sem bibliotecas externas de JS ou CSS. Seguir o visual das telas existentes (`agenda.html`, `hoje.html`) e `referencia-design.md`.
- Cada módulo novo roda sozinho para teste (`python -m app.desempenho.coletor` faz uma rodada e imprime o resumo).
- Testes: `.venv\Scripts\python.exe -m unittest testes.teste_desempenho -v`. Não usam internet nem banco de verdade.
- Commits no estilo do repositório (`Desempenho: ...`), em português.
- **Modelo:** Tarefas 1 a 4 em **Opus 5.5, esforço high**. Tarefas 5 a 8 em **Sonnet 5.5, esforço medium**. Parar e avisar o dono na troca (regra do `CLAUDE.md`).

## Fora deste plano (planos próprios, depois)

- Visualizações do Instagram e do Facebook (dependem de o dono acrescentar uma permissão na Meta e reconectar).
- TikTok (depois da auditoria).

## Review Focus

1. **Painel desligado por mais de um dia.** Um post que passou da janela de 24 h sem ser lido não deve ganhar uma foto de "24 h" com números de 50 h. Teste: Tarefa 4, `test_foto_atrasada_nao_e_gravada`.
2. **Erro de permissão na leitura.** Um 403 ao ler números não pode marcar a conta como vencida (isso seguraria os posts dela). Testes: Tarefa 2, `test_403_nao_pede_reconexao`; Tarefa 4, `test_erro_de_permissao_nao_expira_a_conta`.
3. **A rede esconde um número** (curtidas ocultas, comentários desligados). Fica vazio, e as médias ignoram esse post em vez de contar zero. Testes: Tarefa 2, `test_le_numeros_e_deixa_vazio_o_que_a_rede_esconde`; Tarefa 5, `test_numero_vazio_nao_entra_na_media`.
4. **Post apagado na rede x rede fora do ar.** Apagado: vira "removido", para de ser lido, mantém o histórico. Fora do ar: nada muda. Testes: Tarefa 4, `test_post_que_sumiu_vira_removido` e `test_falha_temporaria_nao_mexe_em_nada`.
5. **Tela sem dados.** Nenhum post, período vazio ou grupo pequeno: mensagem clara, sem erro e sem divisão por zero. Testes: Tarefa 5, `test_periodo_vazio`; Tarefa 6, `test_api_sem_dados`.

## Arquivos

| Arquivo | Responsabilidade |
|---|---|
| `app/banco.py` (modificar) | Tabela `leituras`; coluna `publicacoes.removida_em` |
| `app/desempenho/__init__.py` (criar) | Pacote |
| `app/desempenho/repositorio.py` (criar) | Tudo que lê e grava leituras no banco |
| `app/postagem/redes.py` (modificar) | Tipo `Numeros` |
| `app/postagem/youtube.py`, `meta.py` (modificar) | `ler_numeros` de cada rede |
| `app/desempenho/coletor.py` (criar) | A rodada de leitura e a thread `Coletor` |
| `app/desempenho/relatorio.py` (criar) | Os números da tela, a partir das leituras |
| `app/painel/api_desempenho.py` (criar) | Página e API da tela |
| `app/painel/paginas/desempenho.html`, `estatico/desempenho.js` (criar) | A tela |
| `app/painel/servidor.py`, `estatico/cortes.js`, `estatico/painel.css` (modificar) | Menu, thread, total no cartão do corte |
| `testes/teste_desempenho.py` (criar) | Todos os testes desta fase |

---

### Task 1: Banco e repositório das leituras

**Files:**
- Modify: `app/banco.py` (`ESQUEMA`, depois de `publicacoes`; `_garantir_colunas`)
- Create: `app/desempenho/__init__.py`, `app/desempenho/repositorio.py`
- Modify: `app/postagem/redes.py` (tipo `Numeros`, ao lado de `Resultado`)
- Test: `testes/teste_desempenho.py`

**Interfaces:**
- Produces, em `app/postagem/redes.py`:
  ```python
  @dataclass
  class Numeros:
      visualizacoes: int | None = None
      curtidas: int | None = None
      comentarios: int | None = None
  ```
- Produces, em `app/desempenho/repositorio.py`:
  - `MARCOS_VALIDOS = ("atual", "24h", "3d", "7d")`
  - `gravar_leitura(usuario_id: int, publicacao_id: int, marco: str, numeros: Numeros, lido_em: str) -> None` — grava ou regrava (uma linha por publicação e marco). `marco` fora de `MARCOS_VALIDOS` levanta `ValueError`.
  - `marcos_gravados(publicacao_ids: list[int]) -> dict[int, set[str]]`
  - `publicacoes_para_ler(agora_utc: str, idade_maxima_h: int) -> list[dict]` — publicações `publicada`, com `id_externo`, sem `removida_em`, com `publicado_em` nas últimas `idade_maxima_h` horas, de contas com `estado = 'conectada'`. Cada dict traz `id`, `usuario_id`, `conta_id`, `rede`, `id_externo`, `publicado_em`.
  - `marcar_removida(publicacao_id: int, agora_utc: str) -> None`
  - `linhas_do_relatorio(usuario_id: int, desde_utc: str, ate_utc: str, conta_id: int | None = None) -> list[dict]` — uma linha por publicação `publicada` com `publicado_em` no intervalo `[desde, ate)`. Campos: `id`, `titulo`, `url`, `rede`, `conta_id`, `conta_nome`, `origem`, `corte_id`, `publicado_em`, `removida_em`, `modo`, `nota`, `fonte` (canal do vídeo original; os três últimos `None` se não há corte), e `leituras`: `{marco: Numeros}` só com os marcos que existem.
  - `visualizacoes_por_corte(usuario_id: int) -> dict[int, int]` — soma de `visualizacoes` das leituras `atual` por `corte_id`; cortes sem nenhuma leitura com número ficam fora do dict.

Esquema:
```sql
-- Leituras dos numeros de um post nas redes (Fase 8). marco: 'atual' (regravada a cada rodada) ou a
-- foto tirada quando o post completou aquela idade ('24h', '3d', '7d'). NULL = a rede nao informa.
CREATE TABLE IF NOT EXISTS leituras (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    publicacao_id INTEGER NOT NULL REFERENCES publicacoes(id) ON DELETE CASCADE,
    marco TEXT NOT NULL,
    visualizacoes INTEGER,
    curtidas INTEGER,
    comentarios INTEGER,
    lido_em TEXT NOT NULL,
    UNIQUE (publicacao_id, marco)
);
```
`publicacoes` ganha `removida_em TEXT` (em `ESQUEMA` e em `_garantir_colunas`, para bancos que já existem). `removida_em` **não** entra em `contas.CAMPOS_PUBLICACAO`.

- [ ] **Step 1: Criar `testes/teste_desempenho.py` com o cabeçalho e os testes do repositório**

Cabeçalho (o arquivo precisa rodar sozinho e também junto com `teste_base.py`):
```python
import os, tempfile, unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

if "CANAL_PASTA_DADOS" not in os.environ:
    _PASTA = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    os.environ["CANAL_PASTA_DADOS"] = _PASTA.name
    from cryptography.fernet import Fernet
    os.environ["CANAL_CHAVE_SECRETA"] = Fernet.generate_key().decode()

from app import banco, config  # noqa: E402
from app.contratos import CorteProposto  # noqa: E402
from app.desempenho import repositorio  # noqa: E402
from app.postagem import agendador, contas  # noqa: E402
from app.postagem.redes import ErroPostagem, Numeros  # noqa: E402
```
Ajudantes do arquivo (usados por todas as tarefas):
- `limpar()` — apaga `leituras`, `publicacoes`, `contas` e os cortes/vídeos criados pelo teste.
- `criar_conta(rede="youtube", nome="Canal") -> int` — via `contas.salvar_conta` (conferir a assinatura completa no arquivo).
- `criar_corte(modo="narrado", nota=80, canal="Canal X") -> int` — `banco.registrar_video` + `banco.atualizar_video(canal=...)` + `banco.registrar_corte`.
- `publicar(conta_id, horas_atras, corte_id=None, origem="corte", id_externo=None) -> int` — `contas.criar_publicacao` + `contas.atualizar_publicacao(estado="publicada", id_externo=..., url=..., publicado_em=agendador.texto(agendador.agora() - timedelta(hours=horas_atras)))`. Cada chamada usa uma `chave_video` diferente.
- `agendar_post(conta_id) -> int` — só `contas.criar_publicacao`, com horário no futuro: a publicação fica `agendada`.

Testes (`class TesteRepositorio`):
```python
def test_grava_e_regrava_a_mesma_leitura(self):
    p = publicar(self.conta, 2)
    repositorio.gravar_leitura(1, p, "atual", Numeros(100, 5, 1), "2026-11-14 10:00:00")
    repositorio.gravar_leitura(1, p, "atual", Numeros(150, 6, None), "2026-11-14 11:00:00")
    linha = repositorio.linhas_do_relatorio(1, "2000-01-01 00:00:00", "2100-01-01 00:00:00")[0]
    self.assertEqual(linha["leituras"], {"atual": Numeros(150, 6, None)})

def test_marco_desconhecido_e_recusado(self):
    with self.assertRaises(ValueError):
        repositorio.gravar_leitura(1, publicar(self.conta, 2), "2d", Numeros(), "2026-11-14 10:00:00")

def test_para_ler_so_traz_publicadas_recentes_e_nao_removidas(self):
    recente, velha, removida = publicar(self.conta, 5), publicar(self.conta, 200), publicar(self.conta, 5)
    agendar_post(self.conta)                         # fica 'agendada': nao entra
    repositorio.marcar_removida(removida, agendador.texto(agendador.agora()))
    ids = [p["id"] for p in repositorio.publicacoes_para_ler(agendador.texto(agendador.agora()), 170)]
    self.assertEqual(ids, [recente])

def test_conta_vencida_fica_fora_da_leitura(self):
    publicar(self.conta, 5); contas.atualizar_conta(self.conta, estado="expirada")
    self.assertEqual(repositorio.publicacoes_para_ler(agendador.texto(agendador.agora()), 170), [])

def test_linha_do_relatorio_traz_corte_e_fonte(self):
    corte = criar_corte(modo="original", nota=72, canal="Canal Y")
    publicar(self.conta, 5, corte_id=corte)
    linha = repositorio.linhas_do_relatorio(1, "2000-01-01 00:00:00", "2100-01-01 00:00:00")[0]
    self.assertEqual((linha["modo"], linha["nota"], linha["fonte"], linha["rede"]), ("original", 72, "Canal Y", "youtube"))

def test_visualizacoes_por_corte_soma_os_posts(self):
    corte = criar_corte(); outra = criar_conta("instagram", "Insta")
    a, b = publicar(self.conta, 5, corte_id=corte), publicar(outra, 5, corte_id=corte)
    repositorio.gravar_leitura(1, a, "atual", Numeros(1000, 1, 1), "2026-11-14 10:00:00")
    repositorio.gravar_leitura(1, b, "atual", Numeros(None, 9, 2), "2026-11-14 10:00:00")
    self.assertEqual(repositorio.visualizacoes_por_corte(1), {corte: 1000})

def test_banco_antigo_ganha_a_coluna(self):
    banco.criar_tabelas(); banco.criar_tabelas()      # roda duas vezes sem erro
    with banco.conectar() as c:
        self.assertIn("removida_em", [l["name"] for l in c.execute("PRAGMA table_info(publicacoes)")])
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv\Scripts\python.exe -m unittest testes.teste_desempenho -v`
Expected: erro de importação (`app.desempenho` não existe).

- [ ] **Step 3: Implementar esquema, `Numeros` e `repositorio.py`** conforme Interfaces. Seguir o estilo de `app/postagem/contas.py` (`closing(banco.conectar())`).

- [ ] **Step 4: Conferir `contas.remover_conta`.** Se desconectar uma conta apaga as publicações dela, as leituras somem junto (cascata). Não mudar esse comportamento; anotar o que foi encontrado no relatório final desta tarefa, para o dono decidir depois.

- [ ] **Step 5: Rodar os testes** — Expected: 7 testes, todos passam. Rodar também `.venv\Scripts\python.exe -m unittest discover testes` e confirmar que nada antigo quebrou.

- [ ] **Step 6: Commit**
```bash
git add app/banco.py app/desempenho app/postagem/redes.py testes/teste_desempenho.py docs/superpowers plano.md
git commit -m "Desempenho: tabela de leituras e repositorio"
```

---

### Task 2: Leitura dos números do YouTube

**Files:**
- Modify: `app/postagem/youtube.py`
- Test: `testes/teste_desempenho.py`

**Interfaces:**
- Consumes: `Numeros` (Task 1); `_renovar`, `chamar`, `json_ou_vazio`, `ErroPostagem` já existentes.
- Produces: `youtube.ler_numeros(credenciais: Credenciais, ids: list[str]) -> dict[str, Numeros]`.
  - **Contrato de todo `ler_numeros`:** devolve uma entrada por id que a rede confirmou existir. Id ausente do resultado significa "a rede disse que esse post não existe mais". Qualquer outra dúvida (resposta estranha, rede fora do ar) levanta `ErroPostagem`, nunca omite o id.
  - Endereço: `GET https://www.googleapis.com/youtube/v3/videos`, parâmetros `{"part": "statistics", "id": "<ids separados por vírgula>"}`, em lotes de **50** ids (`LOTE_NUMEROS = 50`). Campos da resposta: `items[].id`, `items[].statistics.viewCount | likeCount | commentCount` (textos; campo ausente vira `None`).
  - Erros: token que não renova → o `reconectar=True` que `_renovar` já levanta. `403` com motivo `quotaExceeded` ou `rateLimitExceeded` → `temporario=True`. Qualquer outro `401`/`403` na chamada de leitura → `ErroPostagem` simples (**sem** `reconectar`, sem `temporario`). Outros códigos diferentes de 200 → `ErroPostagem` simples.

- [ ] **Step 1: Escrever os testes (`class TesteNumerosYoutube`)**

Ajudante do arquivo: `resposta_http(status: int, dados: dict)` → `SimpleNamespace(status_code=status, json=lambda: dados, headers={})`. `setUp`: `mock.patch.object(youtube, "_renovar", return_value="TOKEN")` e credenciais `Credenciais({"access_token": "A", "refresh_token": "R"})`.

```python
def test_le_numeros_e_deixa_vazio_o_que_a_rede_esconde(self):
    resposta = resposta_http(200, {"items": [
        {"id": "aaa", "statistics": {"viewCount": "1200", "likeCount": "80", "commentCount": "7"}},
        {"id": "bbb", "statistics": {"viewCount": "15"}}]})
    with mock.patch.object(youtube, "chamar", return_value=resposta) as chamar:
        numeros = youtube.ler_numeros(self.cred, ["aaa", "bbb", "sumiu"])
    self.assertEqual(numeros, {"aaa": Numeros(1200, 80, 7), "bbb": Numeros(15, None, None)})
    self.assertEqual(chamar.call_args.kwargs["params"], {"part": "statistics", "id": "aaa,bbb,sumiu"})
    self.assertEqual(chamar.call_args.kwargs["headers"], {"Authorization": "Bearer TOKEN"})

def test_lotes_de_50(self):
    with mock.patch.object(youtube, "chamar", return_value=resposta_http(200, {"items": []})) as chamar:
        youtube.ler_numeros(self.cred, [f"v{i}" for i in range(120)])
    self.assertEqual(chamar.call_count, 3)

def test_lista_vazia_nao_chama_a_rede(self):
    with mock.patch.object(youtube, "chamar") as chamar:
        self.assertEqual(youtube.ler_numeros(self.cred, []), {})
    chamar.assert_not_called()

def test_403_nao_pede_reconexao(self):
    erro = {"error": {"message": "sem permissao", "errors": [{"reason": "insufficientPermissions"}]}}
    with mock.patch.object(youtube, "chamar", return_value=resposta_http(403, erro)):
        with self.assertRaises(ErroPostagem) as c:
            youtube.ler_numeros(self.cred, ["aaa"])
    self.assertFalse(c.exception.reconectar); self.assertFalse(c.exception.temporario)

def test_cota_estourada_e_temporaria(self):
    erro = {"error": {"message": "cota", "errors": [{"reason": "quotaExceeded"}]}}
    with mock.patch.object(youtube, "chamar", return_value=resposta_http(403, erro)):
        with self.assertRaises(ErroPostagem) as c:
            youtube.ler_numeros(self.cred, ["aaa"])
    self.assertTrue(c.exception.temporario)
```

- [ ] **Step 2: Rodar e ver falhar** — `...unittest testes.teste_desempenho.TesteNumerosYoutube -v` → `AttributeError: ler_numeros`.

- [ ] **Step 3: Implementar `ler_numeros` em `app/postagem/youtube.py`.** Não reutilizar `_explicar` (ele pede reconexão em 401/403, o que aqui é proibido).

- [ ] **Step 4: Rodar os testes** — Expected: 5 passam.

- [ ] **Step 5: Commit** — `git commit -m "Desempenho: leitura dos numeros do YouTube"`

---

### Task 3: Leitura de curtidas e comentários do Instagram e do Facebook

**Files:**
- Modify: `app/postagem/meta.py`
- Modify: `plano.md` (Fase 8: anotar o que a documentação diz)
- Test: `testes/teste_desempenho.py`

**Interfaces:**
- Consumes: `Numeros`; `GRAPH`, `chamar`, `json_ou_vazio`, `_erro_da_meta` existentes. Credenciais: `page_token`, `ig_id` (Instagram), `page_id` (Facebook). `id_externo` do post: id da mídia (Instagram) e id do vídeo (Facebook).
- Produces: `meta.ler_numeros_instagram(credenciais, ids) -> dict[str, Numeros]` e `meta.ler_numeros_facebook(credenciais, ids) -> dict[str, Numeros]`, com o mesmo contrato da Task 2. `visualizacoes` é sempre `None` nesta fase.

- [ ] **Step 1: Conferir na documentação oficial da Meta (Graph API, versão `config.VERSAO_META`)**, com as permissões que o app já tem (`instagram_basic`, `pages_read_engagement`):
  1. Os campos de curtidas e comentários de uma mídia do Instagram e de um Reel/vídeo de Página.
  2. Se dá para ler vários posts numa chamada (listagem das mídias da conta ou consulta por vários ids) e o que acontece quando um deles foi apagado.
  3. O código de erro para "objeto não existe" e o limite de chamadas por hora com token de Página.

  Escolher o caminho com **menos chamadas por rodada** (meta: no máximo 2 por conta para até 50 posts). Se for usada uma listagem, um id que não aparece nela só é dado como inexistente depois de uma consulta direta a ele confirmar. Anotar o que foi encontrado, com a data, na Fase 8 do `plano.md` (mesmo formato das "Travas conferidas" da Fase 5).

- [ ] **Step 2: Escrever os testes (`class TesteNumerosMeta`)**, com as respostas falsas no formato que a documentação mostrou (`mock.patch.object(meta, "chamar", ...)`):
  - `test_instagram_le_curtidas_e_comentarios` — dois posts; resultado `{"m1": Numeros(None, 40, 3), "m2": Numeros(None, 0, 0)}`.
  - `test_facebook_le_curtidas_e_comentarios` — mesmo formato de resultado.
  - `test_post_apagado_fica_fora_do_resultado` — a rede responde "não existe" para `m2`; resultado só tem `m1`.
  - `test_rede_fora_do_ar_levanta_erro_temporario` — `chamar` levanta `ErroPostagem(temporario=True)`; `ler_numeros_instagram` propaga, não devolve dict parcial.
  - `test_erro_de_permissao_nao_pede_reconexao` — resposta de erro de permissão; `ErroPostagem` com `reconectar=False`.
  - `test_token_vencido_pede_reconexao` — erro de token inválido (código 190); `reconectar=True`.

- [ ] **Step 3: Rodar e ver falhar.**

- [ ] **Step 4: Implementar as duas funções em `app/postagem/meta.py`.** Conferir como `_erro_da_meta` classifica erros hoje; se ele pede reconexão em erro de permissão, tratar esse caso nas funções novas sem mudar `_erro_da_meta` (a postagem depende dele).

- [ ] **Step 5: Rodar os testes** — Expected: 6 passam; `discover testes` continua verde.

- [ ] **Step 6: Commit** — `git commit -m "Desempenho: leitura de curtidas e comentarios da Meta"`

---

### Task 4: Coletor (a rodada de leitura e a thread)

**Files:**
- Create: `app/desempenho/coletor.py`
- Modify: `app/painel/servidor.py` (`criar_app` / `ciclo_de_vida`)
- Test: `testes/teste_desempenho.py`

**Interfaces:**
- Consumes: `repositorio.*` (Task 1), `youtube.ler_numeros` (Task 2), `meta.ler_numeros_instagram/facebook` (Task 3), `contas.credenciais_da_conta`, `contas.regravar_credenciais`, `contas.atualizar_conta`, `contas.ler_conta`, `avisos.avisar`, `ErroCofre`.
- Produces, em `app/desempenho/coletor.py`:
  ```python
  LEITORES = {"youtube": youtube.ler_numeros, "instagram": meta.ler_numeros_instagram,
              "facebook": meta.ler_numeros_facebook}          # TikTok: sem leitor nesta fase
  MARCOS = (("24h", 24), ("3d", 72), ("7d", 168))             # (nome, horas de vida)
  TOLERANCIA_H = 6
  IDADE_MAXIMA_H = 170
  INTERVALO_S = 3600

  def rodar(momento_agora: datetime | None = None) -> dict:
      """Uma rodada. Devolve {"lidas": int, "removidas": int, "falhas": int, "ocupado": bool}."""

  class Coletor(threading.Thread):      # mesmo molde de agendador.Publicador: run(), parar()
  ```
- Regras de `rodar`:
  - Agrupa `repositorio.publicacoes_para_ler(agora, IDADE_MAXIMA_H)` por conta. Rede sem leitor em `LEITORES` é pulada em silêncio.
  - Para cada conta, chama o leitor uma vez com todos os `id_externo`. Regrava as credenciais se `credenciais.mudou` (como `agendador.publicar_uma`).
  - Para cada id devolvido: grava `atual`. Para cada marco `(nome, horas)`: se a idade do post está em `[horas, horas + TOLERANCIA_H)` e o marco ainda não existe, grava o marco com os mesmos números.
  - Id não devolvido: `repositorio.marcar_removida`.
  - `ErroPostagem` com `reconectar=True` ou `ErroCofre`: conta vira `expirada` e sai `avisos.avisar(..., chave=f"reconectar:{conta_id}")`, com o mesmo texto que o publicador usa. Qualquer outro erro (inclusive inesperado): registra no log, soma em `falhas`, segue para a próxima conta. Nada é gravado para a conta que falhou.
  - Uma trava (`threading.Lock`) impede duas rodadas ao mesmo tempo: a segunda devolve `{"ocupado": True, ...zeros}` na hora.
  - `python -m app.desempenho.coletor` roda uma rodada e imprime o resumo em português.
- `Coletor.run`: roda na partida e depois a cada `INTERVALO_S`; nunca deixa a thread morrer (mesmo `try/except` do `Publicador`). Em `servidor.py`: criado em `criar_app`, iniciado no mesmo `if not painel_de_teste()` do publicador, parado no fim de `ciclo_de_vida`.

- [ ] **Step 1: Escrever os testes (`class TesteColetor`)**

`setUp`: `limpar()`, `self.conta = criar_conta()`. Ajudante `self.rodar(numeros_por_id)`: `mock.patch.dict(coletor.LEITORES, {"youtube": mock.Mock(return_value=numeros_por_id)})` e `mock.patch.object(coletor.contas, "credenciais_da_conta", return_value=Credenciais({}))`; devolve `(resultado, leitor)`. `self.leituras(p)` devolve o dict `leituras` da linha do relatório daquela publicação.

```python
def test_grava_atual_e_foto_de_24h_que_nao_muda_depois(self):
    p = publicar(self.conta, 25, id_externo="v1")
    self.rodar({"v1": Numeros(1000, 50, 3)})
    self.rodar({"v1": Numeros(1500, 60, 4)})
    self.assertEqual(self.leituras(p), {"atual": Numeros(1500, 60, 4), "24h": Numeros(1000, 50, 3)})

def test_post_novo_so_tem_atual(self):
    p = publicar(self.conta, 2, id_externo="v1"); self.rodar({"v1": Numeros(10, 1, 0)})
    self.assertEqual(set(self.leituras(p)), {"atual"})

def test_foto_atrasada_nao_e_gravada(self):                 # painel ficou desligado: 50 h de vida
    p = publicar(self.conta, 50, id_externo="v1"); self.rodar({"v1": Numeros(900, 9, 9)})
    self.assertEqual(set(self.leituras(p)), {"atual"})

def test_fotos_de_3_e_7_dias(self):
    a, b = publicar(self.conta, 73, id_externo="v1"), publicar(self.conta, 169, id_externo="v2")
    self.rodar({"v1": Numeros(5, 5, 5), "v2": Numeros(7, 7, 7)})
    self.assertEqual(set(self.leituras(a)), {"atual", "3d"}); self.assertEqual(set(self.leituras(b)), {"atual", "7d"})

def test_post_com_mais_de_7_dias_nao_e_lido(self):
    publicar(self.conta, 200, id_externo="velho"); _, leitor = self.rodar({})
    leitor.assert_not_called()

def test_post_que_sumiu_vira_removido(self):
    p = publicar(self.conta, 5, id_externo="v1")
    self.rodar({"v1": Numeros(10, 1, 0)}); resultado, _ = self.rodar({})
    self.assertEqual(resultado["removidas"], 1)
    self.assertIsNotNone(contas.ler_publicacao(p)["removida_em"])
    self.assertEqual(self.leituras(p), {"atual": Numeros(10, 1, 0)})       # o historico fica
    _, leitor = self.rodar({}); leitor.assert_not_called()                 # nao e mais lido

def test_falha_temporaria_nao_mexe_em_nada(self):
    p = publicar(self.conta, 5, id_externo="v1")
    agendada = agendar_post(self.conta); antes = contas.ler_publicacao(agendada)
    with mock.patch.dict(coletor.LEITORES, {"youtube": mock.Mock(side_effect=ErroPostagem("fora do ar", temporario=True))}), ...:
        resultado = coletor.rodar()
    self.assertEqual(resultado["falhas"], 1)
    self.assertIsNone(contas.ler_publicacao(p)["removida_em"])
    self.assertEqual(contas.ler_publicacao(agendada), antes)
    self.assertEqual(contas.ler_conta(self.conta)["estado"], "conectada")

def test_erro_de_permissao_nao_expira_a_conta(self):        # ErroPostagem simples
    ...; self.assertEqual(contas.ler_conta(self.conta)["estado"], "conectada")

def test_erro_inesperado_nao_derruba_a_rodada(self):         # leitor do youtube levanta ValueError; conta do instagram e lida
    ...; self.assertEqual((resultado["falhas"], resultado["lidas"]), (1, 1))

def test_acesso_vencido_marca_a_conta_e_avisa(self):
    with ... side_effect=ErroPostagem("venceu", reconectar=True), mock.patch.object(coletor.avisos, "avisar") as avisar:
        coletor.rodar()
    self.assertEqual(contas.ler_conta(self.conta)["estado"], "expirada")
    self.assertEqual(avisar.call_args.kwargs["chave"], f"reconectar:{self.conta}")

def test_rede_sem_leitor_e_pulada(self):                     # conta do tiktok com post publicado
    ...; self.assertEqual(coletor.rodar()["falhas"], 0)

def test_duas_rodadas_ao_mesmo_tempo(self):
    with coletor._trava:
        self.assertTrue(coletor.rodar()["ocupado"])
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar `coletor.py` e ligar a thread em `servidor.py`.**
- [ ] **Step 4: Rodar os testes** — Expected: 12 passam; `discover testes` verde (em especial `TestePainel` e `TesteAgendador`).
- [ ] **Step 5: Commit** — `git commit -m "Desempenho: coletor de hora em hora"`

**Parar aqui e avisar o dono: as próximas tarefas pedem Sonnet 5.5, esforço medium.**

---

### Task 5: Relatório

**Files:**
- Create: `app/desempenho/relatorio.py`
- Test: `testes/teste_desempenho.py`

**Interfaces:**
- Consumes: `repositorio.linhas_do_relatorio`, `contas.listar_contas`, `config.FUSO`, `agendador.agora/texto/momento`.
- Produces:
  ```python
  PERIODOS = (7, 30, 90)
  MEDIDAS = ("visualizacoes", "curtidas", "comentarios")
  MINIMO_POR_GRUPO = 3

  def montar(usuario_id: int, dias: int, medida: str, conta_id: int | None = None,
             momento_agora: datetime | None = None) -> dict
  ```
  `dias` fora de `PERIODOS` ou `medida` fora de `MEDIDAS` → `ValueError`. Formato devolvido:
  ```python
  {"dias": 7, "medida": "visualizacoes",
   "totais": {"visualizacoes": 48200, "curtidas": 3100, "comentarios": 212,   # soma das leituras 'atual'; None se nenhum post informa
              "posts": 41,
              "variacao_pct": 32.0,                          # ver regra; None sem base
              "melhor_horario": {"inicio_h": 19, "fim_h": 21}},   # None sem base
   "grupos": {"modo": [...], "nota": [...], "rede": [...], "fonte": [...], "tipo": [...], "hora": [...]},
   "melhores": [post, ...], "piores": [post, ...],
   "sem_medida": ["instagram"],                              # redes com post no periodo e nenhum numero dessa medida
   "contas": [{"id": 1, "nome": "Canal", "rede": "youtube"}]}
  ```
  Cada item de grupo: `{"rotulo": str, "posts": int, "media": int | None}`. Cada `post`: `{"id", "titulo", "url", "rede", "conta", "corte_id", "publicado_em" (horário local, mesmo formato que `api_postagem._local` devolve), "removido": bool, "atual", "24h", "3d", "7d"}` (os quatro últimos são o valor da `medida` naquela leitura, ou `None`).
- Regras (todas sobre o valor da `medida` escolhida):
  - Período: posts com `publicado_em` nos últimos `dias` dias.
  - **Totais** (as três medidas, sempre): soma das leituras `atual`.
  - **Grupos, melhores, piores, variação e melhor horário** usam a foto `24h`. Post sem foto `24h` ou com valor `None` não conta.
  - `media` = média arredondada para inteiro; `None` quando `posts < MINIMO_POR_GRUPO`.
  - `modo`: `narrado`, `original` (só posts com corte). `nota`: `"80 ou mais"`, `"70 a 79"`, `"abaixo de 70"`, sempre os três, nessa ordem. `rede`: uma entrada por rede com post no período, com o nome de `REDES[rede]["nome"]`. `fonte`: os 5 canais com mais posts. `tipo`: `corte`, `template` (campo `origem`). `hora`: 24 entradas, rótulos `"0"` a `"23"`, pela hora local de `publicado_em`.
  - `melhor_horario`: a janela de 2 horas seguidas (`h`, `h+1`; `fim_h = h + 2`) com a maior média, entre as janelas com pelo menos `MINIMO_POR_GRUPO` posts. `None` se nenhuma tem.
  - `variacao_pct`: soma das fotos `24h` dos posts do período contra a soma dos posts do período anterior de mesmo tamanho, em porcentagem com uma casa. `None` se o período anterior soma zero ou não tem foto.
  - `melhores`: os 5 maiores pela foto `24h`. `piores`: os 5 menores, sem repetir nenhum de `melhores` (com poucos posts, pode ficar vazia).

- [ ] **Step 1: Escrever os testes (`class TesteRelatorio`)**

Ajudante `post(horas_atras, *, v24=None, atual=None, n24=None, n_atual=None, conta=None, modo=None, nota=None, canal=None) -> int`: cria um corte se `modo`, `nota` ou `canal` vierem (os que faltarem usam o padrão de `criar_corte`), publica na `conta` (padrão: `self.conta`) e grava as leituras. `v24` e `atual` são só visualizações (`Numeros(visualizacoes=v)`); `n24` e `n_atual` recebem um `Numeros` pronto, para testar outras medidas. Leitura não informada não é gravada.

```python
def test_media_por_modo_e_poucos_dados(self):
    for v in (100, 200, 300): post(30, v24=v, atual=v, modo="narrado")
    for v in (900, 950): post(30, v24=v, atual=v, modo="original")
    modo = {g["rotulo"]: g for g in relatorio.montar(1, 7, "visualizacoes")["grupos"]["modo"]}
    self.assertEqual((modo["narrado"]["posts"], modo["narrado"]["media"]), (3, 200))
    self.assertEqual((modo["original"]["posts"], modo["original"]["media"]), (2, None))

def test_totais_usam_a_leitura_atual(self):
    post(30, v24=100, atual=400); post(2, atual=50)
    t = relatorio.montar(1, 7, "visualizacoes")["totais"]
    self.assertEqual((t["visualizacoes"], t["posts"]), (450, 2))

def test_numero_vazio_nao_entra_na_media(self):          # curtidas ocultas em um dos quatro posts
    for c in (10, 20, 30): post(30, n24=Numeros(1, c, 0))
    post(30, n24=Numeros(1, None, 0))
    rede = relatorio.montar(1, 7, "curtidas")["grupos"]["rede"][0]
    self.assertEqual((rede["posts"], rede["media"]), (3, 20))

def test_rede_sem_a_medida_e_avisada(self):
    insta = criar_conta("instagram", "Insta"); post(30, conta=insta, n24=Numeros(None, 5, 1), n_atual=Numeros(None, 5, 1))
    self.assertEqual(relatorio.montar(1, 7, "visualizacoes")["sem_medida"], ["instagram"])
    self.assertEqual(relatorio.montar(1, 7, "curtidas")["sem_medida"], [])

def test_faixas_de_nota(self):
    for nota in (85, 90, 80): post(30, v24=1000, nota=nota)
    for nota in (70, 79, 75): post(30, v24=400, nota=nota)
    notas = relatorio.montar(1, 7, "visualizacoes")["grupos"]["nota"]
    self.assertEqual([(g["rotulo"], g["media"]) for g in notas],
                     [("80 ou mais", 1000), ("70 a 79", 400), ("abaixo de 70", None)])

def test_variacao_contra_o_periodo_anterior(self):
    post(24 * 10, v24=1000); post(30, v24=1320)
    self.assertEqual(relatorio.montar(1, 7, "visualizacoes")["totais"]["variacao_pct"], 32.0)

def test_variacao_sem_base_fica_vazia(self):
    post(30, v24=500); self.assertIsNone(relatorio.montar(1, 7, "visualizacoes")["totais"]["variacao_pct"])

def test_melhores_e_piores_nao_repetem(self):
    for v in range(1, 8): post(30, v24=v * 100)                      # 7 posts
    r = relatorio.montar(1, 7, "visualizacoes")
    self.assertEqual([p["24h"] for p in r["melhores"]], [700, 600, 500, 400, 300])
    self.assertEqual([p["24h"] for p in r["piores"]], [100, 200])

def test_melhor_horario_precisa_de_base(self):
    post(30, v24=100); self.assertIsNone(relatorio.montar(1, 7, "visualizacoes")["totais"]["melhor_horario"])

def test_filtro_por_conta(self):
    outra = criar_conta("youtube", "Canal 2"); post(30, v24=100, atual=100); post(30, v24=900, atual=900, conta=outra)
    self.assertEqual(relatorio.montar(1, 7, "visualizacoes", conta_id=outra)["totais"]["visualizacoes"], 900)

def test_periodo_vazio(self):
    r = relatorio.montar(1, 7, "visualizacoes")
    self.assertEqual((r["totais"]["posts"], r["totais"]["visualizacoes"], r["melhores"], r["piores"]), (0, None, [], []))
    self.assertEqual(len(r["grupos"]["hora"]), 24)

def test_pedido_invalido(self):
    with self.assertRaises(ValueError): relatorio.montar(1, 5, "visualizacoes")
    with self.assertRaises(ValueError): relatorio.montar(1, 7, "alcance")
```
Mais um, com horário fixo: `test_hora_local_e_melhor_horario` — quatro posts publicados às 19h30 de Brasília (montar o `publicado_em` em UTC a partir de `ZoneInfo(config.FUSO)`) com foto `24h`; o grupo `hora` de rótulo `"19"` tem `posts == 4` e `melhor_horario == {"inicio_h": 19, "fim_h": 21}` (ou a janela 18–20, se a média for igual: fixar no teste os valores de forma que só uma janela vença).

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar `relatorio.py`** — funções puras sobre a lista de linhas, uma função pequena por bloco (totais, grupos, listas).
- [ ] **Step 4: Rodar os testes** — Expected: 13 passam.
- [ ] **Step 5: Commit** — `git commit -m "Desempenho: relatorio"`

---

### Task 6: Tela Desempenho

**Files:**
- Create: `app/painel/api_desempenho.py`, `app/painel/paginas/desempenho.html`, `app/painel/estatico/desempenho.js`
- Modify: `app/painel/servidor.py` (`MENU`, `api_desempenho.registrar(...)`), `app/painel/estatico/painel.css`, `app/painel/paginas/base.html` (ícone novo, onde os outros são definidos)
- Test: `testes/teste_desempenho.py`

**Interfaces:**
- Consumes: `relatorio.montar`, `relatorio.PERIODOS`, `relatorio.MEDIDAS`, `coletor.rodar`.
- Produces:
  - `api_desempenho.registrar(app, paginas, contexto)` (mesmo molde de `api_postagem.registrar`).
  - `GET /desempenho` → página.
  - `GET /api/desempenho?dias=7&medida=visualizacoes&conta_id=` → o dict de `relatorio.montar`. Padrões: `dias=7`, `medida=visualizacoes`. Valor inválido → 400 com `{"erro": "..."}` em português.
  - `POST /api/desempenho/atualizar` → devolve o dict de `coletor.rodar()`.
  - `MENU`, depois de `agenda`: `{"id": "desempenho", "nome": "Desempenho", "icone": "grafico", "fase": 8, "pronto": True, "descricao": "Quanto cada post rendeu e o que está funcionando."}`.

Textos fixos da tela:
- Seletor de período: `7 dias`, `30 dias`, `90 dias`. Seletor de medida: `Visualizações`, `Curtidas`, `Comentários`. Filtro: `Todas as contas` + uma opção por conta.
- Cartões do topo: `Visualizações`, `Curtidas`, `Comentários`, `Posts`, `Melhor horário` (ex.: `19h às 21h`; sem base: `poucos dados`). Variação: `▲ 32% sobre o período anterior` / `▼ 12% sobre o período anterior`; sem base, não aparece.
- Seção `O que está funcionando`, subtítulo `Média por post, com 24 horas de vida`. Linhas: `Modo`, `Nota`, `Rede`, `Fonte`, `Tipo`, `Horário` (barras por hora, de 0h a 23h, altura proporcional à média; hora sem base fica com barra vazia). Grupo com `media` vazia: `poucos dados`.
- Aviso quando `sem_medida` não está vazio: `Instagram Reels e Facebook Reels ainda não informam visualizações. Troque para Curtidas ou Comentários para ver essas redes.` (nomes das redes vindos de `REDES`).
- Listas `Melhores posts` e `Posts que não renderam`, colunas `24 h`, `3 dias`, `7 dias`, `Agora`. Título do post é link para a rede (abre em outra aba). Post que veio de um corte tem o link `ver corte`, que leva à tela Cortes. Valor vazio: `—`. Post removido: etiqueta `removido`.
- Botão `Atualizar agora`; durante a leitura, `Lendo os números…`; resposta `ocupado`: `Já existe uma leitura em andamento.`
- Sem nenhum post no período: `Ainda não há números. Os primeiros aparecem cerca de uma hora depois que um post é publicado.`
- Números com separador de milhar brasileiro (`48.200`).

- [ ] **Step 1: Escrever os testes (`class TesteTelaDesempenho`)**, com `TestClient(servidor.criar_app())` e `CANAL_SEM_TRABALHADOR=1` (mesmo `setUpClass` de `TestePainel`):
```python
def test_pagina_e_menu(self):
    resposta = self.cliente.get("/desempenho")
    self.assertEqual(resposta.status_code, 200); self.assertIn("Desempenho", resposta.text)
    self.assertIn('href="/desempenho"', self.cliente.get("/cortes").text)

def test_api_sem_dados(self):
    dados = self.cliente.get("/api/desempenho").json()
    self.assertEqual((dados["dias"], dados["medida"], dados["totais"]["posts"]), (7, "visualizacoes", 0))

def test_api_com_filtros(self):
    dados = self.cliente.get("/api/desempenho?dias=30&medida=curtidas").json()
    self.assertEqual((dados["dias"], dados["medida"]), (30, "curtidas"))

def test_pedido_invalido_da_400(self):
    for consulta in ("dias=5", "medida=alcance", "dias=abc"):
        resposta = self.cliente.get(f"/api/desempenho?{consulta}")
        self.assertEqual(resposta.status_code, 400, consulta); self.assertIn("erro", resposta.json())

def test_atualizar_agora(self):
    with mock.patch("app.desempenho.coletor.rodar", return_value={"lidas": 3, "removidas": 0, "falhas": 0, "ocupado": False}):
        self.assertEqual(self.cliente.post("/api/desempenho/atualizar").json()["lidas"], 3)
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Olhar `referencia-design.md`, as imagens de `referencia/` e as telas `agenda.html` / `hoje.html`**, depois implementar API, página, JS e estilos. Reaproveitar as classes de cartão e de lista que já existem em `painel.css`; estilos novos só para as barras de horário e a linha de grupos. Tema claro e escuro, e tela estreita, como as outras.
- [ ] **Step 4: Rodar os testes** — Expected: 5 passam; `TestePainel.test_paginas_existem` continua passando.
- [ ] **Step 5: Conferir no navegador.** Ligar o painel de testes (`preview_start` com a configuração do painel; criar `.claude/launch.json` se não existir, rodando `python -m app.painel`), gravar algumas leituras de exemplo no banco **de teste** com um script descartável no scratchpad e conferir: os três seletores, o filtro de conta, o aviso de rede sem medida, o estado vazio, tema escuro e tela estreita. Sem erros no console. Tirar uma captura para mostrar ao dono.
- [ ] **Step 6: Commit** — `git commit -m "Desempenho: tela no painel"`

---

### Task 7: Visualizações no cartão do corte

**Files:**
- Modify: `app/painel/servidor.py` (`api_cortes`, `_corte_json`), `app/painel/estatico/cortes.js`
- Test: `testes/teste_desempenho.py`

**Interfaces:**
- Consumes: `repositorio.visualizacoes_por_corte(usuario_id)`.
- Produces: cada corte de `GET /api/cortes` ganha `"visualizacoes": int | None` (`None` = sem nenhuma leitura). `api_cortes` chama o repositório **uma vez** por pedido, não uma vez por corte.

- [ ] **Step 1: Teste (`class TesteCortesComNumeros`)**
```python
def test_corte_mostra_a_soma_das_visualizacoes(self):
    corte, sem_post = criar_corte(), criar_corte()
    a, b = publicar(self.conta, 5, corte_id=corte), publicar(criar_conta("youtube", "Canal 2"), 5, corte_id=corte)
    repositorio.gravar_leitura(1, a, "atual", Numeros(1000, 1, 1), "2026-11-14 10:00:00")
    repositorio.gravar_leitura(1, b, "atual", Numeros(500, 1, 1), "2026-11-14 10:00:00")
    cortes = {c["id"]: c for c in self.cliente.get("/api/cortes").json()["cortes"]}
    self.assertEqual(cortes[corte]["visualizacoes"], 1500); self.assertIsNone(cortes[sem_post]["visualizacoes"])
```
(Os cortes do teste precisam estar num estado de `ESTADOS_REVISAVEIS`, ex.: `aprovado`.)

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.** No cartão (`cortes.js`), quando `visualizacoes` não é vazio, mostrar `1.500 visualizações` junto das outras informações do corte, com link para `/desempenho`.
- [ ] **Step 4: Rodar os testes e conferir o cartão no navegador.**
- [ ] **Step 5: Commit** — `git commit -m "Desempenho: visualizacoes no cartao do corte"`

---

### Task 8: Fechamento da fase

**Files:**
- Modify: `plano.md` (Fase 8: "Como ficou"; tabela de telas por fase da Fase 3, se couber)

- [ ] **Step 1: Rodar tudo** — `.venv\Scripts\python.exe -m unittest discover testes -v`. Expected: tudo passa. Mostrar o resultado.
- [ ] **Step 2: Atualizar a Fase 8 do `plano.md`** com um bloco "Como ficou (data)": o que foi construído, os arquivos, o que a documentação da Meta dizia, e o que ficou de fora (visualizações da Meta, TikTok).
- [ ] **Step 3: Explicar ao dono, em linguagem simples, como testar sozinho**: publicar a atualização na VPS (`publicar_na_vps.bat`, **só com o OK dele**), abrir `Desempenho`, clicar em `Atualizar agora` e conferir os números de um post do YouTube contra o que o próprio YouTube mostra.
- [ ] **Step 4: Critério de pronto (com o dono, na VPS):** números do YouTube na tela em até uma hora; no dia seguinte, a coluna `24 h` preenchida; total no cartão do corte. Marcar no `plano.md` o que passou e o que ainda falta ver.
- [ ] **Step 5: Commit** — `git commit -m "Plano: Fase 8 (Desempenho) construida"`
