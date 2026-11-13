/* Tela Cortes: grade, filtros, revisão por teclado e seleção em massa. */
"use strict";

(() => {
  const { $, esc, icone, api, aviso, dolar } = Painel;

  const estado = {
    cortes: [], numeros: null, aba: "revisar", modos: new Set(), ordem: "novos", busca: "",
    selecionados: new Set(), selecao: false, aberto: null, carregado: false,
  };

  const grade = $("#grade"), modal = $("#modal-corte"), player = $("#player");

  // ---------- dados ----------

  async function carregar() {
    try {
      const dados = await api("/api/cortes");
      estado.cortes = dados.cortes;
      estado.numeros = dados.numeros;
      estado.carregado = true;
      // Tira da seleção o que sumiu da lista.
      for (const id of [...estado.selecionados]) if (!estado.cortes.some((c) => c.id === id)) estado.selecionados.delete(id);
      desenhar();
      if (estado.aberto) preencherModal();
    } catch (erro) {
      grade.innerHTML = `<div class="cartao vazio" style="grid-column:1/-1"><h2>Não consegui carregar os cortes</h2><p>${esc(erro.message)}</p></div>`;
    }
  }

  const ABAS = {
    revisar: (c) => c.estado === "renderizado" || c.estado === "proposto",
    aprovado: (c) => c.estado === "aprovado",
    descartado: (c) => c.estado === "descartado",
    todos: () => true,
  };

  function filtrados() {
    let lista = estado.cortes.filter(ABAS[estado.aba]);
    if (estado.modos.size) lista = lista.filter((c) => estado.modos.has(c.modo));
    if (estado.busca) {
      lista = lista.filter((c) => (c.titulo + " " + c.canal + " " + c.video_titulo + " " + c.motivo).toLowerCase().includes(estado.busca));
    }
    const ordem = {
      novos: (a, b) => b.id - a.id,
      nota: (a, b) => b.nota - a.nota || b.id - a.id,
      curtos: (a, b) => a.duracao_s - b.duracao_s,
    }[estado.ordem];
    return lista.sort(ordem);
  }

  // ---------- grade ----------

  const corDaNota = (n) => (n >= 80 ? "#3ccf7a" : n >= 65 ? "#ffb02e" : "#ff6b70");

  function cartao(c, indice) {
    const selo = c.estado === "aprovado" ? '<span class="tag estado-aprovado">Aprovado</span>'
      : c.estado === "descartado" ? '<span class="tag estado-descartado">Descartado</span>'
      : c.estado === "falhou" ? '<span class="tag estado-falhou">Falhou</span>' : "";
    const voz = c.narracao === "narrado" ? '<span class="tag voz">Com voz</span>'
      : c.modo === "narrado" ? '<span class="tag">Sem voz</span>' : '<span class="tag">Original</span>';
    const marcado = estado.selecionados.has(c.id);
    const acoes = c.estado === "renderizado"
      ? `<button class="mini ok" data-acao="aprovado" title="Aprovar (A)">${icone("check")}</button>
         <button class="mini no" data-acao="descartado" title="Descartar (D)">${icone("x")}</button>`
      : `<button class="mini" data-acao="renderizado" title="Voltar para revisar">${icone("refazer")}</button>`;
    return `<article class="corte ${c.estado} ${marcado ? "selecionado" : ""}" data-id="${c.id}" style="animation-delay:${Math.min(indice, 12) * 30}ms">
      <div class="corte-imagem">
        ${c.miniatura ? `<img src="${c.miniatura}" alt="" loading="lazy">` : ""}
        <div class="corte-topo">
          <div class="nota" style="--p:${c.nota};--cor:${corDaNota(c.nota)}" title="Nota ${c.nota}"><span>${c.nota}</span></div>
          <div style="display:flex;flex-direction:column;gap:5px;align-items:flex-start">${voz}${selo}</div>
          <div class="espaco caixa-selecao" data-selecionar>${icone("check")}</div>
        </div>
        <div class="corte-titulo">${esc(c.titulo)}</div>
      </div>
      <div class="corte-pe">
        <div class="corte-fonte" title="${esc(c.video_titulo)}"><b>${esc(c.canal || "—")}</b> · ${Math.round(c.duracao_s)} s</div>
        ${acoes}
      </div></article>`;
  }

  function desenhar() {
    const n = estado.numeros;
    $("#n-revisar").textContent = n.revisar;
    $("#n-aprovados").textContent = n.aprovados;
    $("#n-hoje").textContent = n.cortes_hoje;
    const custos = estado.cortes.filter((c) => c.custo_usd > 0).map((c) => c.custo_usd);
    $("#n-custo").textContent = custos.length ? dolar(custos.reduce((a, b) => a + b, 0) / custos.length) : "–";
    $("#aba-revisar").textContent = n.revisar;
    $("#aba-aprovado").textContent = n.aprovados;
    $("#aba-descartado").textContent = n.descartados;
    $("#aba-todos").textContent = estado.cortes.length;

    const lista = filtrados();
    if (!estado.cortes.length) {
      grade.innerHTML = `<div class="cartao vazio" style="grid-column:1/-1">${arte()}
        <h2>Nenhum corte ainda</h2>
        <p>Cole o link de um vídeo do YouTube e a IA escolhe os melhores momentos, monta os cortes verticais e coloca legenda em português.</p>
        <button class="botao primario" onclick="Painel.abrirNovo()">${icone("mais")}Criar meu primeiro corte</button></div>`;
    } else if (!lista.length) {
      const porAba = { revisar: "Nada esperando revisão. Bom trabalho!", aprovado: "Você ainda não aprovou nenhum corte.",
                       descartado: "Nenhum corte descartado.", todos: "Nenhum corte combina com os filtros." };
      grade.innerHTML = `<div class="cartao vazio" style="grid-column:1/-1"><h2>${porAba[estado.aba]}</h2>
        <p>${estado.busca || estado.modos.size ? "Tente limpar a busca ou os filtros." : "Quando novos cortes ficarem prontos, eles aparecem aqui."}</p></div>`;
    } else {
      grade.innerHTML = lista.map(cartao).join("");
    }
    document.body.classList.toggle("modo-selecao", estado.selecao);
    atualizarBarraMassa();
  }

  const arte = () => `<svg class="arte" viewBox="0 0 160 160" fill="none"><defs><linearGradient id="ga" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#6a45ff"/><stop offset="1" stop-color="#ff4f8b"/></linearGradient></defs>
    <rect x="48" y="14" width="64" height="112" rx="14" fill="url(#ga)" opacity=".16"/><rect x="48" y="14" width="64" height="112" rx="14" stroke="url(#ga)" stroke-width="3"/>
    <path d="M73 52v32l26-16z" fill="url(#ga)"/><circle cx="32" cy="118" r="9" stroke="url(#ga)" stroke-width="3"/><circle cx="32" cy="146" r="9" stroke="url(#ga)" stroke-width="3"/>
    <path d="M40 124l60 18M40 140l60-18" stroke="url(#ga)" stroke-width="3" stroke-linecap="round"/></svg>`;

  // ---------- ações ----------

  async function definirEstado(ids, novo, { silencioso = false } = {}) {
    const anteriores = ids.map((id) => ({ id, estado: estado.cortes.find((c) => c.id === id)?.estado })).filter((x) => x.estado);
    try {
      await api("/api/cortes/estado", { metodo: "POST", corpo: { ids, estado: novo } });
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); return false; }
    await carregar();
    if (!silencioso) {
      const rotulo = { aprovado: "aprovado", descartado: "descartado", renderizado: "devolvido para revisão" }[novo];
      aviso(ids.length === 1 ? `Corte ${rotulo}.` : `${ids.length} cortes ${rotulo}s.`, {
        acao: async () => {
          for (const estadoAntigo of new Set(anteriores.map((a) => a.estado))) {
            await api("/api/cortes/estado", { metodo: "POST", corpo: { ids: anteriores.filter((a) => a.estado === estadoAntigo).map((a) => a.id), estado: estadoAntigo } });
          }
          carregar();
        },
      });
    }
    return true;
  }

  // Clique nos cartões (delegação).
  grade.addEventListener("click", (e) => {
    const alvo = e.target.closest(".corte");
    if (!alvo) return;
    const id = Number(alvo.dataset.id);
    const botao = e.target.closest("[data-acao]");
    if (botao) { e.stopPropagation(); definirEstado([id], botao.dataset.acao); return; }
    if (e.target.closest("[data-selecionar]") || estado.selecao || e.shiftKey || e.ctrlKey) {
      alternarSelecao(id);
      return;
    }
    abrir(id);
  });

  function alternarSelecao(id) {
    if (estado.selecionados.has(id)) estado.selecionados.delete(id); else estado.selecionados.add(id);
    desenhar();
  }

  // Prévia em movimento ao passar o mouse.
  grade.addEventListener("mouseover", (e) => {
    const alvo = e.target.closest(".corte");
    if (!alvo || alvo.dataset.previa) return;
    const c = estado.cortes.find((x) => x.id === Number(alvo.dataset.id));
    if (!c || !c.midia) return;
    alvo.dataset.previa = "1";
    const video = document.createElement("video");
    Object.assign(video, { src: c.midia, muted: true, loop: true, playsInline: true, preload: "auto" });
    video.addEventListener("loadeddata", () => video.classList.add("tocando"), { once: true });
    alvo.querySelector(".corte-imagem").insertBefore(video, alvo.querySelector(".corte-topo"));
    if (alvo.matches(":hover")) video.play().catch(() => {});
    alvo.addEventListener("mouseenter", () => video.play().catch(() => {}));
    alvo.addEventListener("mouseleave", () => { video.pause(); video.currentTime = 0; });
  });

  // ---------- seleção em massa ----------

  function atualizarBarraMassa() {
    const total = estado.selecionados.size;
    $("#barra-massa").classList.toggle("aberta", total > 0);
    $("#massa-texto").textContent = total === 1 ? "1 selecionado" : `${total} selecionados`;
  }
  $("#botao-selecionar").onclick = () => {
    estado.selecao = !estado.selecao;
    if (!estado.selecao) estado.selecionados.clear();
    $("#botao-selecionar").classList.toggle("primario", estado.selecao);
    desenhar();
  };
  $("#massa-aprovar").onclick = async () => { await definirEstado([...estado.selecionados], "aprovado"); estado.selecionados.clear(); desenhar(); };
  $("#massa-descartar").onclick = async () => { await definirEstado([...estado.selecionados], "descartado"); estado.selecionados.clear(); desenhar(); };
  $("#massa-limpar").onclick = () => { estado.selecionados.clear(); desenhar(); };

  // ---------- filtros ----------

  $("#abas").addEventListener("click", (e) => {
    const aba = e.target.closest(".aba");
    if (!aba) return;
    estado.aba = aba.dataset.aba;
    document.querySelectorAll(".aba").forEach((a) => a.classList.toggle("ativa", a === aba));
    desenhar();
  });
  document.querySelectorAll(".chip[data-modo]").forEach((chip) => chip.addEventListener("click", () => {
    const modo = chip.dataset.modo;
    if (estado.modos.has(modo)) estado.modos.delete(modo); else estado.modos.add(modo);
    chip.classList.toggle("ativo", estado.modos.has(modo));
    desenhar();
  }));
  $("#ordem").onchange = (e) => { estado.ordem = e.target.value; desenhar(); };
  document.addEventListener("busca", (e) => { estado.busca = e.detail; desenhar(); });
  document.addEventListener("fila:terminou", carregar);

  // ---------- janela de revisão ----------

  function abrir(id) {
    estado.aberto = id;
    modal.classList.add("aberto");
    preencherModal(true);
  }
  function fechar() {
    modal.classList.remove("aberto");
    player.pause(); player.removeAttribute("src"); player.load();
    estado.aberto = null;
  }

  function preencherModal(novoVideo = false) {
    const lista = filtrados();
    let indice = lista.findIndex((c) => c.id === estado.aberto);
    const c = estado.cortes.find((x) => x.id === estado.aberto);
    if (!c) { fechar(); return; }

    if (novoVideo || !player.src.endsWith(c.midia || "")) {
      player.src = c.midia || "";
      player.play().catch(() => {});
    }
    $("#corte-posicao").textContent = indice >= 0 ? `${indice + 1} de ${lista.length}` : "";
    const estadoSelo = { renderizado: '<span class="selo acento">Para revisar</span>', aprovado: '<span class="selo ok">Aprovado</span>',
                         descartado: '<span class="selo erro">Descartado</span>', falhou: '<span class="selo erro">Falhou</span>' }[c.estado] || "";
    $("#corte-selos").innerHTML = estadoSelo +
      `<span class="selo">${c.modo === "narrado" ? "Modo narrado" : "Áudio original"}</span>` +
      `<span class="selo">${Math.round(c.duracao_s)} s</span>`;
    $("#corte-titulo").textContent = c.titulo;
    const nota = $("#corte-nota");
    nota.style.setProperty("--p", c.nota); nota.style.setProperty("--cor", corDaNota(c.nota));
    nota.firstElementChild.textContent = c.nota;
    $("#corte-nota-texto").textContent = c.nota >= 80 ? "Corte forte" : c.nota >= 65 ? "Corte bom" : "Corte mediano";
    $("#corte-motivo").textContent = c.motivo;
    $("#corte-fonte").innerHTML = `<b>${esc(c.canal || "Canal desconhecido")}</b><br><span class="dica">${esc(c.video_titulo)}</span>`;
    $("#corte-original").href = c.video_url;
    $("#corte-baixar").href = c.midia || "#";
    $("#corte-baixar").setAttribute("download", `corte_${c.id}.mp4`);
    $("#corte-aprovar").disabled = c.estado === "aprovado";
    $("#corte-descartar").disabled = c.estado === "descartado";

    const narrando = Painel.fila().some((i) => i.tipo === "narrar" && i.alvo === String(c.id) && ["aguardando", "processando"].includes(i.estado));
    const botaoVoz = $("#corte-narrar"), textoVoz = $("#corte-voz-texto");
    if (narrando) {
      textoVoz.textContent = "Na fila: a narração está sendo feita…"; botaoVoz.disabled = true;
      botaoVoz.lastElementChild.textContent = "Narrando";
    } else if (c.narracao === "narrado") {
      textoVoz.innerHTML = "Este corte já tem <b>voz</b>. Você pode refazer o roteiro e a gravação."; botaoVoz.disabled = false;
      botaoVoz.lastElementChild.textContent = "Refazer";
    } else {
      textoVoz.innerHTML = c.narracao === "falhou" ? "A última tentativa de narrar falhou. Tente de novo."
        : "Sem narração. Narrar custa cerca de <b>US$ 0,10</b> de voz mais 1 centavo de IA.";
      botaoVoz.disabled = false; botaoVoz.lastElementChild.textContent = "Narrar";
    }
  }

  async function decidir(novo) {
    const c = estado.cortes.find((x) => x.id === estado.aberto);
    if (!c) return;
    const lista = filtrados();
    const indice = lista.findIndex((x) => x.id === c.id);
    const proximo = lista[indice + 1] || lista[indice - 1];
    if (await definirEstado([c.id], novo)) {
      // Fluxo de revisão: depois de decidir, já mostra o próximo da lista.
      const aindaNaLista = filtrados().some((x) => x.id === c.id);
      if (!aindaNaLista) {
        if (proximo && filtrados().some((x) => x.id === proximo.id)) { estado.aberto = proximo.id; preencherModal(true); }
        else fechar();
      }
    }
  }

  function navegar(passo) {
    const lista = filtrados();
    const indice = lista.findIndex((c) => c.id === estado.aberto);
    const alvo = lista[indice + passo];
    if (alvo) { estado.aberto = alvo.id; preencherModal(true); }
  }

  $("#corte-fechar").onclick = fechar;
  modal.addEventListener("mousedown", (e) => { if (e.target === modal) fechar(); });
  $("#corte-aprovar").onclick = () => decidir("aprovado");
  $("#corte-descartar").onclick = () => decidir("descartado");
  $("#corte-credito").onclick = async () => {
    const c = estado.cortes.find((x) => x.id === estado.aberto);
    const texto = `Vídeo original: ${c.video_titulo} — ${c.canal} (${c.video_url})`;
    try { await navigator.clipboard.writeText(texto); aviso("Crédito copiado."); }
    catch (e) { aviso("Não consegui copiar. Selecione o texto na tela.", { tipo: "erro" }); }
  };
  $("#corte-narrar").onclick = async () => {
    const c = estado.cortes.find((x) => x.id === estado.aberto);
    $("#corte-narrar").disabled = true;
    try {
      await api(`/api/cortes/${c.id}/narrar`, { metodo: "POST" });
      aviso("Narração adicionada à fila.");
      Painel.abrirGaveta();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
    preencherModal();
  };
  document.addEventListener("fila:mudou", () => { if (estado.aberto) preencherModal(); });

  document.addEventListener("keydown", (e) => {
    if (!modal.classList.contains("aberto") || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === "a") decidir("aprovado");
    else if (k === "d") decidir("descartado");
    else if (e.key === "ArrowRight") navegar(1);
    else if (e.key === "ArrowLeft") navegar(-1);
    else if (e.key === "Escape") fechar();
  });

  // Primeira carga: mostra esqueletos enquanto espera.
  grade.innerHTML = Array.from({ length: 6 }, () => '<div class="esqueleto"></div>').join("");
  carregar();
})();
