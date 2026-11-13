@echo off
rem Mostra as ultimas linhas do log do Canal Dark na VPS.
cd /d "%~dp0"
title Canal Dark - log da VPS
".venv\Scripts\python.exe" deploy\publicar.py --logs
pause
