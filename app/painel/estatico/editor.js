/* Tela Editor: lista dos ajustes feitos e criação de um novo. */
"use strict";

(() => {
  const { $, esc, icone, api, aviso } = Painel;
  const grade = $("#grade-ajustes");
  let lista = [], busca = "";

  const SELO = {
    rascunho: '<span class="selo">Sem vídeo</span>', pronto: '<span class="selo acento">Pronto para gerar</span>',
    gerando: '<span class="selo aviso">Gerando…</span>', concluido: '<span class="selo ok">Pronto para baixar</span>',
  };

  function desenhar() {
    const visiveis = lista.filter((a) => !busca || a.nome.toLowerCase().includes(busca));
    if (!lista.length) {
      grade.innerHTML = `<div class="cartao vazio" style="grid-column:1/-1;margin-top:0">
        <div class="em-breve" style="padding:0"><div class="arte">${icone("lapis")}</div></div>
        <h2>Nenhum ajuste ainda</h2><p>Use o Editor para pegar um vídeo (de um corte, da biblioteca ou do seu computador) e deixá-lo em tela cheia no formato vertical.</p>
        <button class="botao primario" onclick="document.getElementById('novo-ajuste').click()">${icone("mais")}Fazer meu primeiro ajuste</button></div>`;
      return;
    }
    grade.innerHTML = visiveis.map((a, i) => `<article class="cartao-template" data-id="${a.id}" style="animation-delay:${Math.min(i, 12) * 30}ms">
      <div class="capa"><img src="${a.capa}" alt="" loading="lazy"><div class="selo-topo">${SELO[a.estado]}</div>
        <button class="botao-icone apagar" data-apagar title="Apagar ajuste" aria-label="Apagar">${icone("x")}</button></div>
      <div class="info-template"><b title="${esc(a.nome)}">${esc(a.nome)}</b><small>${a.n_prontas ? "Vídeo pronto" : a.n_midias ? "Aguardando geração" : "Escolha um vídeo"}</small></div></article>`).join("");
  }

  async function carregar() {
    try { lista = (await api("/api/editor")).ajustes; desenhar(); }
    catch (erro) { grade.innerHTML = `<div class="cartao vazio" style="grid-column:1/-1"><h2>Não consegui carregar</h2><p>${esc(erro.message)}</p></div>`; }
  }

  grade.addEventListener("click", async (e) => {
    const alvo = e.target.closest(".cartao-template"); if (!alvo) return;
    const id = Number(alvo.dataset.id);
    if (e.target.closest("[data-apagar]")) {
      if (!confirm("Apagar este ajuste e o vídeo gerado?")) return;
      try { await api(`/api/templates/${id}`, { metodo: "DELETE" }); aviso("Ajuste apagado."); carregar(); }
      catch (erro) { aviso(erro.message, { tipo: "erro" }); }
      return;
    }
    location.href = `/editor/${id}`;
  });

  $("#novo-ajuste").onclick = async () => {
    try {
      const { id } = await api("/api/templates", { metodo: "POST", corpo: { layout: "cheio", nome: "Ajuste de vídeo" } });
      location.href = `/editor/${id}`;
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  };
  document.addEventListener("busca", (e) => { busca = e.detail; desenhar(); });
  carregar();
})();
