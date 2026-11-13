"""Liga o painel: python -m app.painel  (ou clique duas vezes em iniciar_painel.bat)."""
import threading
import webbrowser

import uvicorn

ENDERECO = "127.0.0.1"
PORTA = 8000

if __name__ == "__main__":
    # Abre o navegador um instante depois de o servidor ligar.
    threading.Timer(1.5, lambda: webbrowser.open(f"http://{ENDERECO}:{PORTA}")).start()
    print(f"\nPainel no ar em http://{ENDERECO}:{PORTA}  (feche esta janela para desligar)\n")
    uvicorn.run("app.painel.servidor:app", host=ENDERECO, port=PORTA, log_level="warning")
