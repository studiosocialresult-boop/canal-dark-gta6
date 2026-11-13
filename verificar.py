"""Verifica se Python, ffmpeg, yt-dlp e Deno estao funcionando.

Rodar: .venv\\Scripts\\python.exe verificar.py
"""
import subprocess
import sys


def rodar(args):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
        saida = (r.stdout or r.stderr).strip().splitlines()
        return r.returncode == 0, (saida[0] if saida else "")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def main():
    testes = [
        ("Python 3.12", [sys.executable, "--version"]),
        ("ffmpeg", ["ffmpeg", "-version"]),
        ("yt-dlp", [sys.executable, "-m", "yt_dlp", "--version"]),
        # O YouTube exige um programa de JavaScript para liberar os formatos de video.
        ("Deno (ajudante do YouTube)", ["deno", "--version"]),
    ]
    tudo_ok = True
    for nome, args in testes:
        ok, info = rodar(args)
        if nome == "Python 3.12" and not info.startswith("Python 3.12"):
            ok = False
        print(("[OK]    " if ok else "[FALHOU]"), nome, "-", info)
        tudo_ok = tudo_ok and ok
    print()
    print("Tudo pronto!" if tudo_ok else "Algo falhou. Veja acima.")
    return 0 if tudo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
