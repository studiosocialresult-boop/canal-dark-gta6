#!/usr/bin/env bash
# Instala (ou atualiza) o Canal Dark na VPS. Roda na propria VPS, chamado pelo deploy/publicar.py.
# Pode rodar quantas vezes quiser: so instala o que falta e reinicia o servico.
set -euo pipefail

PASTA="$HOME/canal-dark"
cd "$PASTA"

echo "==> Programas do sistema"
if ! command -v ffmpeg >/dev/null || ! dpkg -s python3.12-venv >/dev/null 2>&1; then
    sudo apt-get update -q
    sudo apt-get install -y -q ffmpeg python3.12-venv
fi
if [ ! -x "$HOME/.deno/bin/deno" ]; then
    echo "==> Instalando o Deno (o yt-dlp precisa dele para o YouTube)"
    curl -fsSL https://deno.land/install.sh | sh -s -- -y
fi

echo "==> Ambiente Python"
[ -d .venv ] || python3.12 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt

echo "==> Pastas e banco"
.venv/bin/python -c "from app import banco, config; config.garantir_pastas(); banco.criar_tabelas()"
chmod 600 .env cookies.txt 2>/dev/null || true

echo "==> Servico"
sudo cp deploy/canal-dark.service /etc/systemd/system/canal-dark.service
sudo systemctl daemon-reload
sudo systemctl enable -q canal-dark
sudo systemctl restart canal-dark
for _ in $(seq 1 30); do
    if curl -fs -o /dev/null http://127.0.0.1:8000/cortes; then
        echo "==> Painel no ar."
        exit 0
    fi
    sleep 2
done
echo "==> O painel nao subiu. Ultimas linhas do log:"
sudo journalctl -u canal-dark -n 30 --no-pager
exit 1
