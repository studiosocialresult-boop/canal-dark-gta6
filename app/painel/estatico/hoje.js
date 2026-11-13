/* Tela Hoje: ranking da busca diaria, botao de buscar e canais acompanhados. */
"use strict";

(() => {
  const { $, esc, icone, api, aviso } = Painel;
  let dados = null, relogio = null;

  const milhar = (n) => (n == null ? "–" : n >= 1e6 ? (n / 1e6).toFixed(1).replace(".", ",") + " mi" : n >= 1e3 ? Math.round(n / 1e3) + " mil" : String(n));
  const horas = (h) => (h == null ? "–" : h < 1 ? "menos de 1 h" : h < 48 ? `há ${Math.round(h)} h` : `há ${Math.round(h / 24)} dias`);
  const DESTINO = {
    enfileirado: '<span class="selo ok">Na fila</span>', ja_processado: '<span class="selo">Já processado</span>',
    fora_da_meta: '<span class="selo acento">Fora da meta</span>', ignorado: '<span class="selo">Ignorado</span>',
  };
  const quando = (iso) => (iso ? new Date(iso.replace(" ", "T") + "Z").toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "");

  function linha(r) {
    const acelera = r.aceleracao != null && r.velocidade && r.aceleracao > r.velocidade * 1.2
      ? `<span class="selo aviso" title="Está ganhando views mais rápido que a média desde a última busca">Acelerando</span>` : "";
    const podeProcessar = ["fora_da_meta"].includes(r.destino);
    return `<div class="rank" data-id="${r.id}">
      <div class="rank-pos">${r.posicao}</div>
      <img class="rank-mini" src="${r.miniatura}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
      <div class="rank-info">
        <a class="rank-titulo" href="${esc(r.url)}" target="_blank" rel="noopener" title="${esc(r.titulo)}">${esc(r.titulo)}</a>
        <small>${esc(r.canal)}${r.origem === "canal" ? " · canal acompanhado" : ""} · ${horas(r.horas)}</small>
        <div>${DESTINO[r.destino] || ""} ${acelera} <small>${esc(r.motivo || "")}</small></div>
      </div>
      <div class="rank-num"><strong>${milhar(Math.round(r.velocidade))}</strong><small>views/hora</small></div>
      <div class="rank-num"><strong>${milhar(r.views)}</strong><small>views</small></div>
      <div class="rank-acao">${podeProcessar ? `<button class="botao pequeno" data-acao="processar">${icone("tesoura")}Gerar cortes</button>` : ""}</div>
    </div>`;
  }

  function desenhar() {
    const d = dados;
    $("#n-estado").textContent = d.ativa ? "Ligada" : "Desligada";
    $("#n-proxima").textContent = d.ativa && d.proxima
      ? `próxima: ${d.proxima.slice(8, 10)}/${d.proxima.slice(5, 7)} às ${d.proxima.slice(11, 16)}`
      : "ligue em Configurações";
    $("#n-ranking").textContent = d.ranking.length;
    $("#n-janela").textContent = `postados nas últimas ${d.janela_h} h`;
    $("#n-fila").textContent = d.enfileirados;
    $("#n-meta").textContent = `meta: ${d.meta_cortes} cortes por dia`;

    const caixa = $("#aviso-busca");
    caixa.hidden = !(d.rodando || d.erro);
    caixa.className = "cartao aviso-busca" + (d.erro && !d.rodando ? " erro" : "");
    caixa.textContent = d.rodando ? "Buscando agora… leva cerca de 1 minuto." : (d.erro ? `A última busca falhou: ${d.erro}` : "");
    $("#buscar-agora").disabled = $("#buscar-sem-fila").disabled = d.rodando;

    $("#ranking").innerHTML = d.ranking.length
      ? `<div class="cartao"><div class="rank-cab"><h3>Ranking · ${d.busca ? quando(d.busca.terminada_em) : ""}</h3><small>${esc(d.busca ? d.busca.resumo || "" : "")}</small></div>${d.ranking.map(linha).join("")}</div>`
      : `<div class="cartao vazio"><h2>Nenhuma busca ainda</h2><p>Clique em <b>Buscar agora</b> para ver os vídeos de GTA 6 que mais crescem. A busca leva cerca de 1 minuto e não gasta créditos de IA; só quando um vídeo vai para a fila é que o corte gasta.</p></div>`;

    $("#canais").innerHTML = d.canais.length
      ? d.canais.map((c) => `<span class="chip" data-canal="${c.id}"><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.nome)}</a><button type="button" aria-label="Parar de acompanhar ${esc(c.nome)}">${icone("x")}</button></span>`).join("")
      : '<p class="dica" style="margin:12px 0 0">Nenhum canal acompanhado ainda.</p>';

    $("#historico").innerHTML = d.historico.length
      ? d.historico.map((h) => `<div class="hist"><b>${h.dia.slice(8)}/${h.dia.slice(5, 7)}</b> ${h.estado === "pronta" ? '<span class="selo ok">Pronta</span>' : h.estado === "falhou" ? '<span class="selo erro">Falhou</span>' : '<span class="selo aviso">Rodando</span>'} <small>${esc(h.resumo || h.erro || "")}</small></div>`).join("")
      : '<p class="dica" style="margin:0">Ainda não houve buscas.</p>';
  }

  async function carregar() {
    clearTimeout(relogio);
    try { dados = await api("/api/hoje"); desenhar(); }
    catch (erro) { $("#ranking").innerHTML = `<div class="cartao vazio"><h2>Não consegui carregar</h2><p>${esc(erro.message)}</p></div>`; }
    relogio = setTimeout(carregar, dados && dados.rodando ? 3000 : 30000);
  }

  async function buscar(enfileirar) {
    try { await api("/api/hoje/buscar", { metodo: "POST", corpo: { enfileirar } }); aviso("Busca iniciada."); carregar(); }
    catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  }
  $("#buscar-agora").onclick = () => buscar(true);
  $("#buscar-sem-fila").onclick = () => buscar(false);

  $("#ranking").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-acao='processar']"); if (!b) return;
    try { await api("/api/hoje/processar", { metodo: "POST", corpo: { id: b.closest("[data-id]").dataset.id } }); aviso("Vídeo enviado para a fila de cortes."); carregar(); }
    catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  });

  $("#form-canal").onsubmit = async (e) => {
    e.preventDefault();
    const campo = $("#canal-novo"); $("#canal-erro").textContent = "";
    if (!campo.value.trim()) return;
    $("#canal-add").disabled = true;
    try { const r = await api("/api/canais", { metodo: "POST", corpo: { url: campo.value } }); campo.value = ""; aviso(`Acompanhando ${r.canal.nome}.`); carregar(); }
    catch (erro) { $("#canal-erro").textContent = erro.message; }
    finally { $("#canal-add").disabled = false; }
  };
  $("#canais").addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    try { await api(`/api/canais/${b.closest("[data-canal]").dataset.canal}`, { metodo: "DELETE" }); carregar(); }
    catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  });

  carregar();
})();
