/* Tela Templates: lista dos templates e escolha do modelo de layout. */
"use strict";

(() => {
  const { $, esc, icone, api, aviso } = Painel;
  const grade = $("#grade-templates"), modal = $("#modal-layout");
  let lista = [], layouts = [], busca = "";

  const ESTADOS = {
    rascunho: ['<span class="selo">Rascunho</span>', "Continuar editando"],
    pronto: ['<span class="selo acento">Pronto para gerar</span>', "Abrir"],
    gerando: ['<span class="selo aviso">Gerando…</span>', "Ver progresso"],
    concluido: ['<span class="selo ok">Concluído</span>', "Abrir"],
  };

  function cartao(t, i) {
    const [selo] = ESTADOS[t.estado];
    const combinacoes = t.n_midias * t.n_frases;
    const resumo = t.n_saidas ? `${t.n_prontas} de ${t.n_saidas} vídeos prontos`
      : combinacoes ? `${t.n_midias} vídeo${t.n_midias > 1 ? "s" : ""} × ${t.n_frases} frase${t.n_frases > 1 ? "s" : ""} = ${combinacoes}`
      : "Faltam vídeos ou frases";
    return `<article class="cartao-template" data-id="${t.id}" style="animation-delay:${Math.min(i, 12) * 30}ms">
      <div class="capa"><img src="${t.capa}" alt="" loading="lazy"><div class="selo-topo">${selo}</div>
        <button class="botao-icone apagar" data-apagar title="Apagar template" aria-label="Apagar">${icone("x")}</button></div>
      <div class="info-template"><b title="${esc(t.nome)}">${esc(t.nome)}</b><small>${esc(t.layout_nome)}</small><small>${esc(resumo)}</small></div></article>`;
  }

  function desenhar() {
    const visiveis = lista.filter((t) => !busca || (t.nome + " " + t.layout_nome).toLowerCase().includes(busca));
    if (!lista.length) {
      grade.innerHTML = `<div class="cartao vazio" style="grid-column:1/-1;margin-top:0">
        <svg class="arte" viewBox="0 0 160 160" fill="none"><defs><linearGradient id="gt" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#6a45ff"/><stop offset="1" stop-color="#ff4f8b"/></linearGradient></defs>
        <rect x="22" y="26" width="64" height="112" rx="12" stroke="url(#gt)" stroke-width="3" opacity=".5"/><rect x="48" y="14" width="64" height="112" rx="12" fill="url(#gt)" opacity=".18" stroke="url(#gt)" stroke-width="3"/>
        <rect x="74" y="34" width="64" height="112" rx="12" stroke="url(#gt)" stroke-width="3"/><path d="M96 72v32l24-16z" fill="url(#gt)"/></svg>
        <h2>Nenhum template ainda</h2>
        <p>Um template junta o visual da sua página (foto, nome, frase) com seus vídeos. Depois é só escolher quantas variações gerar.</p>
        <button class="botao primario" onclick="document.getElementById('novo-template').click()">${icone("mais")}Criar meu primeiro template</button></div>`;
    } else if (!visiveis.length) {
      grade.innerHTML = `<div class="cartao vazio" style="grid-column:1/-1"><h2>Nada encontrado</h2><p>Nenhum template combina com a busca.</p></div>`;
    } else {
      grade.innerHTML = visiveis.map(cartao).join("");
    }
  }

  async function carregar() {
    try {
      const dados = await api("/api/templates");
      lista = dados.templates; layouts = dados.layouts;
      desenhar();
      clearTimeout(carregar.relogio);
      if (lista.some((t) => t.estado === "gerando")) carregar.relogio = setTimeout(carregar, 4000);
    } catch (erro) {
      grade.innerHTML = `<div class="cartao vazio" style="grid-column:1/-1"><h2>Não consegui carregar</h2><p>${esc(erro.message)}</p></div>`;
    }
  }

  grade.addEventListener("click", async (e) => {
    const alvo = e.target.closest(".cartao-template");
    if (!alvo) return;
    const id = Number(alvo.dataset.id);
    if (e.target.closest("[data-apagar]")) {
      const t = lista.find((x) => x.id === id);
      if (!confirm(`Apagar o template "${t.nome}"? Os vídeos gerados dele também serão apagados.`)) return;
      try { await api(`/api/templates/${id}`, { metodo: "DELETE" }); aviso("Template apagado."); carregar(); }
      catch (erro) { aviso(erro.message, { tipo: "erro" }); }
      return;
    }
    location.href = `/templates/${id}`;
  });

  // Novo template: escolher o layout.
  $("#novo-template").onclick = () => {
    $("#opcoes-layout").innerHTML = layouts.map((l) => `<button class="opcao-layout" data-layout="${l.id}">
      ${Painel.esquemaDeLayout(l.id)}<div><b>${esc(l.nome)}</b><small>${esc(l.descricao)}</small></div></button>`).join("");
    modal.classList.add("aberto");
  };
  $("#layout-fechar").onclick = () => modal.classList.remove("aberto");
  modal.addEventListener("mousedown", (e) => { if (e.target === modal) modal.classList.remove("aberto"); });
  $("#opcoes-layout").addEventListener("click", async (e) => {
    const botao = e.target.closest("[data-layout]");
    if (!botao) return;
    try {
      const { id } = await api("/api/templates", { metodo: "POST", corpo: { layout: botao.dataset.layout } });
      location.href = `/templates/${id}`;
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  });

  document.addEventListener("busca", (e) => { busca = e.detail; desenhar(); });
  document.addEventListener("fila:terminou", carregar);
  carregar();
})();
