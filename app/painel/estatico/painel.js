/* Canal Dark — comportamento comum a todas as telas:
   avisos, tema, fila ao vivo, janela "Novo corte" e atalhos de teclado. */
"use strict";

const Painel = (() => {
  const $ = (sel, raiz = document) => raiz.querySelector(sel);

  /** Texto seguro para colocar em HTML (títulos vêm do YouTube e da IA). */
  function esc(texto) {
    return String(texto ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  const icone = (nome, estilo = "") => `<svg class="i" style="${estilo}"><use href="#i-${nome}"/></svg>`;

  async function api(caminho, opcoes = {}) {
    const pedido = { method: opcoes.metodo || "GET", headers: {} };
    if (opcoes.corpo !== undefined) {
      pedido.headers["Content-Type"] = "application/json";
      pedido.body = JSON.stringify(opcoes.corpo);
    }
    let resposta;
    try {
      resposta = await fetch(caminho, pedido);
    } catch (e) {
      throw new Error("Não consegui falar com o painel. Ele ainda está ligado?");
    }
    const dados = await resposta.json().catch(() => ({}));
    if (!resposta.ok) throw new Error(dados.erro || "Algo deu errado.");
    return dados;
  }

  function aviso(texto, { tipo = "", acao = null, rotulo = "Desfazer", duracao = 5200 } = {}) {
    const caixa = document.createElement("div");
    caixa.className = "aviso " + tipo;
    caixa.innerHTML = `<span>${esc(texto)}</span>`;
    if (acao) {
      const botao = document.createElement("button");
      botao.textContent = rotulo;
      botao.onclick = () => { acao(); caixa.remove(); };
      caixa.appendChild(botao);
    }
    $("#avisos").appendChild(caixa);
    setTimeout(() => caixa.remove(), duracao);
  }

  const dolar = (v) => "US$ " + Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // ---------- tema ----------
  function trocarTema() {
    const escuro = document.documentElement.dataset.tema !== "escuro";
    document.documentElement.dataset.tema = escuro ? "escuro" : "";
    try { localStorage.setItem("tema", escuro ? "escuro" : "claro"); } catch (e) { /* sem armazenamento: tudo bem */ }
  }
  $("#botao-tema").onclick = trocarTema;

  // ---------- gasto na barra lateral ----------
  async function atualizarGasto() {
    try {
      const n = await api("/api/numeros");
      $("#gasto-hoje").textContent = dolar(n.gasto_hoje_usd);
      $("#gasto-total").textContent = "Total: " + dolar(n.gasto_usd);
      $("#gasto-barra").style.width = Math.min(100, (n.gasto_hoje_usd / 2) * 100) + "%";
    } catch (e) { /* o painel segue sem o cartão */ }
  }

  // ---------- fila ao vivo ----------
  const gaveta = $("#gaveta"), fundoGaveta = $("#fundo-gaveta");
  let ativosAntes = new Set(), itensDaFila = [], temporizador = null;

  const abrirGaveta = () => { gaveta.classList.add("aberta"); fundoGaveta.classList.add("aberto"); atualizarFila(); };
  const fecharGaveta = () => { gaveta.classList.remove("aberta"); fundoGaveta.classList.remove("aberto"); };
  $("#botao-fila").onclick = () => (gaveta.classList.contains("aberta") ? fecharGaveta() : abrirGaveta());
  $("#gaveta-fechar").onclick = fecharGaveta;
  fundoGaveta.onclick = fecharGaveta;
  $("#gaveta-novo").onclick = () => abrirNovo();

  const tempo = (texto) => (texto ? new Date(texto.replace(" ", "T") + "Z") : null);
  function ha(texto) {
    const d = tempo(texto);
    if (!d) return "";
    const s = Math.max(0, Math.round((Date.now() - d) / 1000));
    if (s < 60) return "agora há pouco";
    if (s < 3600) return `há ${Math.floor(s / 60)} min`;
    if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
    return `há ${Math.floor(s / 86400)} d`;
  }

  function desenharFila(itens) {
    const lista = $("#gaveta-lista");
    if (!itens.length) {
      lista.innerHTML = `<div class="vazio" style="padding:40px 10px"><h2>Fila vazia</h2>
        <p>Cole o link de um vídeo para começar. Os cortes aparecem aqui conforme ficam prontos.</p></div>`;
      return;
    }
    lista.innerHTML = itens.map((i) => {
      const ativo = i.estado === "processando", espera = i.estado === "aguardando";
      const selo = ativo ? `<span class="selo acento">Processando</span>`
        : espera ? `<span class="selo">Na fila</span>`
        : i.estado === "pronto" ? `<span class="selo ok">Pronto</span>` : `<span class="selo erro">Falhou</span>`;
      const tipo = i.tipo === "narrar" ? "Narração: " : "";
      const detalhe = ativo ? esc(i.progresso || "Começando") : espera ? "Aguardando a vez" : esc(i.resultado || "");
      return `<div class="tarefa">
        <div class="tarefa-topo">${ativo ? '<div class="giro"></div>' : ""}
          <div class="tarefa-titulo" title="${esc(i.rotulo)}">${tipo}${esc(i.rotulo)}</div>${selo}</div>
        ${ativo ? '<div class="trilho"><i></i></div>' : ""}
        <small>${detalhe}${i.terminado_em ? " · " + ha(i.terminado_em) : ""}</small></div>`;
    }).join("");
  }

  async function atualizarFila() {
    clearTimeout(temporizador);
    let dados;
    try { dados = await api("/api/fila"); } catch (e) { temporizador = setTimeout(atualizarFila, 6000); return; }
    itensDaFila = dados.itens;
    const contador = $("#contador-fila");
    contador.hidden = dados.ativos === 0;
    contador.textContent = dados.ativos;

    const ativosAgora = new Set(dados.itens.filter((i) => ["aguardando", "processando"].includes(i.estado)).map((i) => i.id));
    const terminados = [...ativosAntes].filter((id) => !ativosAgora.has(id));
    ativosAntes = ativosAgora;
    for (const id of terminados) {
      const item = dados.itens.find((i) => i.id === id);
      if (item) {
        aviso(item.estado === "pronto" ? `${item.rotulo}: ${item.resultado}` : `Falhou: ${item.resultado || item.rotulo}`,
              { tipo: item.estado === "pronto" ? "" : "erro", duracao: 7000 });
      }
    }
    if (terminados.length) { document.dispatchEvent(new CustomEvent("fila:terminou")); atualizarGasto(); }
    document.dispatchEvent(new CustomEvent("fila:mudou", { detail: dados.itens }));

    if (gaveta.classList.contains("aberta")) desenharFila(dados.itens);
    const rapido = dados.ativos > 0 || gaveta.classList.contains("aberta");
    temporizador = setTimeout(atualizarFila, rapido ? 2500 : 9000);
  }

  // ---------- novo corte ----------
  const modalNovo = $("#modal-novo"), campoLink = $("#campo-link"), erroLink = $("#erro-link");
  function abrirNovo() {
    erroLink.textContent = "";
    modalNovo.classList.add("aberto");
    setTimeout(() => campoLink.focus(), 50);
  }
  const fecharNovo = () => modalNovo.classList.remove("aberto");
  $("#novo-cancelar").onclick = fecharNovo;
  modalNovo.addEventListener("mousedown", (e) => { if (e.target === modalNovo) fecharNovo(); });
  const botaoNovo = $("#botao-novo");
  if (botaoNovo) botaoNovo.onclick = abrirNovo;

  $("#form-novo").onsubmit = async (e) => {
    e.preventDefault();
    const enviar = $("#novo-enviar");
    enviar.disabled = true; erroLink.textContent = "";
    try {
      await api("/api/links", { metodo: "POST", corpo: { url: campoLink.value.trim() } });
      campoLink.value = "";
      fecharNovo();
      aviso("Link adicionado à fila.");
      abrirGaveta();
    } catch (erro) {
      erroLink.textContent = erro.message;
    } finally { enviar.disabled = false; }
  };

  // ---------- busca e atalhos ----------
  const busca = $("#busca");
  busca.addEventListener("input", () => document.dispatchEvent(new CustomEvent("busca", { detail: busca.value.trim().toLowerCase() })));

  document.addEventListener("keydown", (e) => {
    const digitando = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
    if (e.key === "Escape") {
      if (modalNovo.classList.contains("aberto")) fecharNovo();
      else if (gaveta.classList.contains("aberta")) fecharGaveta();
      else if (digitando && document.activeElement === busca) busca.blur();
      return;
    }
    if (digitando || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "/") { e.preventDefault(); busca.focus(); }
    else if (e.key.toLowerCase() === "n" && !document.querySelector(".fundo-modal.aberto")) { e.preventDefault(); abrirNovo(); }
    else if (e.key.toLowerCase() === "f" && !document.querySelector(".fundo-modal.aberto")) { e.preventDefault(); abrirGaveta(); }
  });

  atualizarGasto();
  atualizarFila();

  return { $, esc, icone, api, aviso, dolar, abrirNovo, abrirGaveta, atualizarGasto,
           fila: () => itensDaFila };
})();
