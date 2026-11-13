@echo off
rem Liga o painel do Canal Dark e abre o navegador. Para desligar, feche esta janela.
cd /d "%~dp0"
title Canal Dark - painel
if not exist ".venv\Scripts\python.exe" (
  echo Nao achei o ambiente do projeto ^(.venv^). Fale com o Claude para refazer a instalacao.
  pause
  exit /b 1
)
rem O Windows so enxerga programas recem-instalados em janelas novas; aqui puxamos o caminho atualizado.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"`) do set "PATH=%%P"
".venv\Scripts\python.exe" -m app.painel
pause
