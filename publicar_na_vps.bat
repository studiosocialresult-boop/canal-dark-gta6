@echo off
rem Atualiza o Canal Dark na VPS com a ultima versao salva no git (leva tambem o .env e o cookies.txt).
cd /d "%~dp0"
title Canal Dark - publicar na VPS
".venv\Scripts\python.exe" deploy\publicar.py %*
pause
