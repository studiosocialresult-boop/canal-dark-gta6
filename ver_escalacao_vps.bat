@echo off
rem Mostra o que o modo automatico postaria nas proximas 24 h, com os dados da VPS (nao agenda nada).
cd /d "%~dp0"
title Canal Dark - previa da escalacao
".venv\Scripts\python.exe" deploy\previa_escalacao_vps.py
pause
