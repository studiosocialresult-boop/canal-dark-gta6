/* Tela Configurações: ajustes dos cortes e estado do sistema. */
"use strict";

(() => {
  const { $, esc, api, aviso } = Painel;
  let originais = {}, atuais = {};

  function desenharAjustes(valores) {
    $("#ajustes").innerHTML = valores.map((v) => `
      <div class="ajuste">
        <div class="ajuste-topo"><b>${esc(v.nome)}</b><output id="saida-${v.chave}">${v.valor}${esc(v.unidade)}</output></div>
        <input type="range" data-chave="${v.chave}" min="${v.minimo}" max="${v.maximo}" value="${v.valor}" step="1">
        <small>${esc(v.ajuda)}</small>
      </div>`).join("");
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
