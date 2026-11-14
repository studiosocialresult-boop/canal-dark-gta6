@echo off
chcp 65001 >nul
set FFMPEG="%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"
set PASTA=%~dp0deploy\marca
if not exist "%PASTA%" mkdir "%PASTA%"
set ARQUIVO=%PASTA%\video_demo_tiktok.mp4

echo ======================================================
echo   Gravando a tela. Para PARAR, clique nesta janela
echo   preta e aperte a tecla  Q
echo ======================================================
echo.

%FFMPEG% -y -f gdigrab -framerate 15 -i desktop -vf "scale=1280:-2" -c:v libx264 -preset veryfast -pix_fmt yuv420p -crf 28 "%ARQUIVO%"

echo.
echo Gravacao salva em: %ARQUIVO%
pause
