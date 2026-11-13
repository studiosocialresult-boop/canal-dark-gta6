@echo off
rem Manda o cookies.txt novo para a VPS (use quando o painel avisar que o YouTube pediu login).
cd /d "%~dp0"
title Canal Dark - trocar cookies na VPS
".venv\Scripts\python.exe" deploy\publicar.py --cookies
pause
