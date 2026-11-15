/* Tela Contas: conectar as redes e ajustar o ritmo de cada conta. */
"use strict";

(() => {
  const { $, esc, icone, api, aviso } = Painel;
  const SERVICOS = {
    youtube: { nome: "YouTube Shorts", texto: "Envia como Short público. Até 100 envios por dia por projeto do Google.", passos: "Google Cloud: criar projeto, ativar a YouTube Data API v3, criar credencial OAuth (tipo Web) e colar o ID e o segredo no .env (YOUTUBE_CLIENT_ID e YOUTUBE_CLIENT_SECRET)." },
    meta: { nome: "Instagram e Facebook", texto: "Um login da Meta conecta a sua Página do Facebook e o Instagram profissional ligado a ela. Facebook Reels aceita vídeos de 3 a 90 s.", passos: "Meta for Developers: criar app do tipo Empresa, no caso de uso do Instagram criar uma configuração de login (token de usuário, com a Página e o Instagram) e colar o ID do app, a chave secreta e o número da configuração em Configurações → Chaves e integrações." },
    tiktok: { nome: "TikTok", texto: "Cada post pede sua escolha de privacidade e confirmação. Sem auditoria do app, só posta como 'Somente eu' em conta privada.", passos: "TikTok for Developers: criar app com Login Kit e Content Posting API (postagem direta) e colar a chave e o segredo no .env (TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET)." },
  };
  const NOMES_REDE = { youtube: "YouTube", instagram: "Instagram", facebook: "Facebook", tiktok: "TikTok" };

  function mensagemDaUrl() {
    const p = new URLSearchParams(location.search);
    const caixa = $("#mensagem-contas");
    if (p.get("erro")) caixa.innerHTML = `<div class="aviso-caixa" style="margin-top:16px;background:var(--erro-fraco);color:var(--erro)">${icone("alerta")}<span>${esc(p.get("erro"))}</span></div>`;
    else if (p.get("conectadas")) caixa.innerHTML = `<div class="aviso-caixa" style="margin-top:16px;background:var(--ok-fraco);color:var(--ok)">${icone("check")}<span>${esc(p.get("conectadas"))} conta(s) conectada(s).</span></div>`;
    if (p.get("erro") || p.get("conectadas")) history.replaceState(null, "", "/contas");
  }

  function dataCurta(iso) {
    const [, mes, dia] = iso.split("-");
    return `${dia}/${mes}`;
  }

  function ritmoTexto(c) {
    const hoje = `Hoje: ${c.ritmo_hoje} ${c.ritmo_hoje === 1 ? "post" : "posts"}`;
    if (c.subindo) return `${hoje} (conta nova: sobe para ${c.proximo_ritmo} em ${dataCurta(c.muda_em)}, até chegar a ${c.posts_por_dia})`;
    return `${hoje} · freio de segurança: no máximo ${c.limite_seguro} em 24 h`;
  }

  function desenhar(dados) {
    $("#servicos").innerHTML = Object.entries(SERVICOS).map(([id, s]) => {
      const info = dados.servicos[id];
      const conectadas = dados.contas.filter((c) => info.redes.includes(c.rede)).length;
      return `<article class="cartao servico">
        <div class="servico-topo">${info.redes.map((r) => `<span class="rede ${r}">${NOMES_REDE[r]}</span>`).join("")}
          <span style="margin-left:auto">${info.configurado ? (conectadas ? `<span class="selo ok">${conectadas} conectada(s)</span>` : '<span class="selo">Pronto para conectar</span>')
            : '<span class="selo aviso">App não cadastrado</span>'}</span></div>
        <b>${s.nome}</b><p class="dica" style="margin:0">${s.texto}</p>
        ${info.configurado ? `<a class="botao primario" href="/contas/conectar/${id}">${icone("plug")}${conectadas ? "Conectar outra conta" : "Conectar"}</a>`
          : `<details><summary class="dica" style="cursor:pointer">Como liberar</summary><p class="dica">${s.passos}</p>
              <p class="dica">Endereço de retorno para cadastrar no app:</p><code class="codigo">${esc(info.retorno)}</code></details>`}
      </article>`;
    }).join("");

    const lista = $("#lista-contas");
    if (!dados.contas.length) { lista.innerHTML = '<div class="vazio-pequeno">Nenhuma conta conectada ainda.</div>'; return; }
    lista.innerHTML = `<div class="lista">${dados.contas.map((c) => `
      <div class="linha-conta" data-id="${c.id}">
        <div class="foto-conta">${c.foto ? `<img src="${esc(c.foto)}" alt="" referrerpolicy="no-referrer">` : esc((c.nome || "?").replace("@", "")[0].toUpperCase())}</div>
        <div style="min-width:0;flex:1"><b>${esc(c.nome)}</b> <span class="rede ${c.rede}">${NOMES_REDE[c.rede]}</span>
          ${c.estado !== "conectada" ? `<br><small style="color:var(--erro)">${esc(c.erro || "Precisa conectar de novo.")}</small>` : ""}
          <br><small class="dica">${ritmoTexto(c)}</small></div>
        ${c.estado !== "conectada" ? `<a class="botao pequeno" href="/contas/conectar/${c.rede === "youtube" ? "youtube" : c.rede === "tiktok" ? "tiktok" : "meta"}">Conectar de novo</a>` : ""}
        <label class="interruptor" title="Conta nova: começa com poucos posts por dia e sobe sozinha até a meta em 4 semanas. Desligue se a conta já é estabelecida."><input type="checkbox" data-rampa ${c.rampa ? "checked" : ""}>Subir aos poucos</label>
        <label class="rotulo-campo" style="display:flex;align-items:center;gap:8px;font-weight:500">Meta por dia
          <input class="campo" type="number" min="1" max="24" value="${c.posts_por_dia}" data-ritmo style="width:72px;padding:7px 9px"></label>
        <label class="interruptor" title="Pausar ou retomar"><input type="checkbox" data-ativa ${c.ativa ? "checked" : ""}>Ativa</label>
        <button class="mini no" data-remover title="Desconectar" aria-label="Desconectar">${icone("x")}</button>
      </div>`).join("")}</div>`;
  }

  async function carregar() {
    try { desenhar(await api("/api/contas")); }
    catch (erro) { $("#lista-contas").innerHTML = `<p class="erro-texto">${esc(erro.message)}</p>`; }
  }

  $("#lista-contas").addEventListener("change", async (e) => {
    const linha = e.target.closest("[data-id]"); if (!linha) return;
    const id = linha.dataset.id;
    try {
      if (e.target.matches("[data-ritmo]")) await api(`/api/contas/${id}`, { metodo: "PUT", corpo: { posts_por_dia: Number(e.target.value) } });
      if (e.target.matches("[data-ativa]")) await api(`/api/contas/${id}`, { metodo: "PUT", corpo: { ativa: e.target.checked } });
      if (e.target.matches("[data-rampa]")) await api(`/api/contas/${id}`, { metodo: "PUT", corpo: { rampa: e.target.checked } });
      aviso("Conta atualizada.");
      if (e.target.matches("[data-ritmo], [data-rampa]")) carregar();       // atualiza o "Hoje: N posts"
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); carregar(); }
  });
  $("#lista-contas").addEventListener("click", async (e) => {
    if (!e.target.closest("[data-remover]")) return;
    const linha = e.target.closest("[data-id]");
    if (!confirm("Desconectar esta conta? O que estava agendado para ela é cancelado (o que já foi publicado continua na rede).")) return;
    try { await api(`/api/contas/${linha.dataset.id}`, { metodo: "DELETE" }); aviso("Conta desconectada."); carregar(); }
    catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  });

  mensagemDaUrl();
  carregar();
})();
