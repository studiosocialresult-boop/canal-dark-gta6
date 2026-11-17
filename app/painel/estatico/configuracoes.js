/* Tela Configurações: ajustes dos cortes e estado do sistema. */
"use strict";

(() => {
  const { $, esc, api, aviso } = Painel;
  let originais = {}, atuais = {};

  function desenharAjustes(valores) {
    $("#ajustes").innerHTML = valores.map((v) => v.minimo === null ? `
      <div class="ajuste">
        <div class="ajuste-topo"><b>${esc(v.nome)}</b></div>
        <input class="campo" type="text" data-chave="${v.chave}" value="${esc(v.valor)}" placeholder="vazio = espalhar por igual" autocomplete="off">
        <small>${esc(v.ajuda)}</small>
      </div>` : v.minimo === 0 && v.maximo === 1 ? `
      <div class="ajuste">
        <label class="interruptor"><input type="checkbox" data-chave="${v.chave}" ${v.valor ? "checked" : ""}>${esc(v.nome)}</label>
        <small>${esc(v.ajuda)}</small>
      </div>` : `
      <div class="ajuste">
        <div class="ajuste-topo"><b>${esc(v.nome)}</b><output id="saida-${v.chave}">${v.valor}${esc(v.unidade)}</output></div>
        <input type="range" data-chave="${v.chave}" min="${v.minimo}" max="${v.maximo}" value="${v.valor}" step="1">
        <small>${esc(v.ajuda)}</small>
      </div>`).join("");
    document.querySelectorAll("#ajustes input[type=checkbox]").forEach((c) => c.addEventListener("change", () => {
      atuais[c.dataset.chave] = c.checked ? 1 : 0;
      $("#salvar").disabled = JSON.stringify(atuais) === JSON.stringify(originais);
    }));
    document.querySelectorAll("#ajustes input[type=text]").forEach((t) => t.addEventListener("input", () => {
      atuais[t.dataset.chave] = t.value;
      $("#salvar").disabled = JSON.stringify(atuais) === JSON.stringify(originais);
    }));
    document.querySelectorAll("input[type=range]").forEach((r) => r.addEventListener("input", () => {
      atuais[r.dataset.chave] = Number(r.value);
      const unidade = valores.find((v) => v.chave === r.dataset.chave).unidade;
      $("#saida-" + r.dataset.chave).textContent = r.value + unidade;
      $("#salvar").disabled = JSON.stringify(atuais) === JSON.stringify(originais);
    }));
  }

  function desenharSistema(s) {
    const linha = (ok, nome, ajuda, selo) => `<div class="estado-linha ${ok ? "" : "falta"}">
      <span class="ponto"></span><div><b>${nome}</b><small>${ajuda}</small></div>
      <span class="selo ${ok ? "ok" : "erro"}">${selo || (ok ? "Pronto" : "Faltando")}</span></div>`;
    $("#sistema").innerHTML =
      linha(s.anthropic, "Chave da Anthropic", "Usada pela IA que escolhe os cortes e escreve as narrações.") +
      linha(s.elevenlabs, "Chave da ElevenLabs", "Usada para gravar a voz da narração.") +
      linha(s.cookies, "Login do YouTube (cookies)", s.cookies ? "Permite baixar vídeos com restrição de idade." : "Opcional neste computador; obrigatório no servidor.", s.cookies ? "Pronto" : "Ausente") +
      linha(s.ffmpeg, "ffmpeg", "Corta os vídeos e coloca legenda e narração.") +
      linha(s.deno, "Deno", "Ajuda o download do YouTube a funcionar.") +
      `<div class="estado-linha"><span class="ponto"></span><div><b>Modelos de IA</b><small>Cérebro: ${esc(s.modelo_cerebro)} · Rápido: ${esc(s.modelo_rapido)}</small></div></div>` +
      `<div class="estado-linha"><span class="ponto"></span><div><b>Voz da narração</b><small>${esc(s.voz_id)} (George)</small></div></div>`;
  }

  async function carregar() {
    try {
      const dados = await api("/api/configuracoes");
      originais = Object.fromEntries(dados.valores.map((v) => [v.chave, v.valor]));
      atuais = { ...originais };
      desenharAjustes(dados.valores);
      desenharSistema(dados.sistema);
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  }

  // ---------- chaves e integracoes ----------
  const NOMES_REDE = { youtube: "YouTube", meta: "Instagram e Facebook", tiktok: "TikTok" };

  function desenharChaves(dados) {
    const grupos = new Map();
    for (const c of dados.chaves) { if (!grupos.has(c.grupo)) grupos.set(c.grupo, []); grupos.get(c.grupo).push(c); }
    $("#chaves").innerHTML = [...grupos].map(([grupo, itens]) => `
      <div class="grupo-chaves"><b class="grupo-titulo">${esc(grupo)}</b>
        ${itens.map((c) => `<form class="chave" data-nome="${c.nome}">
          <div class="chave-info"><span class="selo ${c.preenchida ? "ok" : "erro"}">${c.preenchida ? "Preenchida" : "Faltando"}</span>
            <div><b>${esc(c.rotulo)}</b><small>${esc(c.ajuda)}</small></div></div>
          <div class="chave-campo">
            <input class="campo" type="password" autocomplete="off" spellcheck="false" placeholder="${c.preenchida ? "Colar para trocar" : "Colar aqui"}" aria-label="${esc(c.rotulo)}">
            <button class="botao pequeno primario" type="submit">Salvar</button>
            ${c.preenchida ? '<button class="botao pequeno fantasma" type="button" data-apagar>Apagar</button>' : ""}
          </div></form>`).join("")}
        ${grupo === "Avisos no Telegram" ? `<div class="chave-acoes">
          <button class="botao pequeno" type="button" id="tg-descobrir">Descobrir conversa</button>
          <button class="botao pequeno" type="button" id="tg-testar">Mandar teste</button>
          <small class="dica">Depois de salvar o token, mande “oi” para o seu robô no Telegram e clique em <b>Descobrir conversa</b>.</small></div>` : ""}
      </div>`).join("");
    $("#retornos").innerHTML = Object.entries(dados.retornos).map(([rede, url]) => `
      <div class="retorno"><small>${NOMES_REDE[rede]}</small><code>${esc(url)}</code>
        <button class="botao pequeno fantasma" type="button" data-copiar="${esc(url)}">Copiar</button></div>`).join("");
  }

  async function carregarChaves() {
    try { desenharChaves(await api("/api/chaves")); }
    catch (erro) { $("#chaves").innerHTML = `<p class="erro-texto">${esc(erro.message)}</p>`; }
  }

  $("#chaves").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target, campo = form.querySelector("input");
    if (!campo.value.trim()) { campo.focus(); return; }
    try {
      await api("/api/chaves", { metodo: "PUT", corpo: { nome: form.dataset.nome, valor: campo.value } });
      campo.value = ""; aviso("Chave salva."); carregarChaves(); carregar();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  });

  $("#chaves").addEventListener("click", async (e) => {
    const alvo = e.target.closest("button"); if (!alvo) return;
    try {
      if (alvo.hasAttribute("data-apagar")) {
        const form = alvo.closest("form");
        if (!confirm("Apagar esta chave do servidor?")) return;
        await api("/api/chaves", { metodo: "PUT", corpo: { nome: form.dataset.nome, valor: "" } });
        aviso("Chave apagada."); carregarChaves(); carregar();
      } else if (alvo.id === "tg-descobrir") {
        await api("/api/chaves/telegram/descobrir", { metodo: "POST" }); aviso("Conversa encontrada e salva."); carregarChaves();
      } else if (alvo.id === "tg-testar") {
        await api("/api/chaves/telegram/testar", { metodo: "POST" }); aviso("Mensagem enviada. Confira o Telegram.");
      }
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  });

  $("#retornos").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-copiar]"); if (!b) return;
    try { await navigator.clipboard.writeText(b.dataset.copiar); aviso("Endereço copiado."); }
    catch { aviso("Não consegui copiar. Selecione o endereço e copie com Ctrl+C.", { tipo: "erro" }); }
  });

  carregarChaves();

  $("#salvar").onclick = async () => {
    $("#salvar").disabled = true;
    try {
      await api("/api/configuracoes", { metodo: "PUT", corpo: atuais });
      originais = { ...atuais };
      aviso("Configurações salvas.");
    } catch (erro) {
      aviso(erro.message, { tipo: "erro" });
      $("#salvar").disabled = false;
    }
  };
  carregar();
})();
