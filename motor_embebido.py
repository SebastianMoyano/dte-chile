#!/usr/bin/env python3
"""
motor_embebido.py — Punto de entrada del motor cuando va EMPAQUETADO dentro de la app.

PyInstaller congela este archivo (ver `motor.spec`) en `app/build/motor/`, y el cascarón Go
lo arranca así:

    motor --host 127.0.0.1 --port <libre>        (cwd = carpeta de datos del usuario)

Todo lo relativo (`.env`, `dte_database.db`, `storage/`, `logs/`) se resuelve desde el cwd,
que el cascarón fija en la carpeta de datos (`~/Library/Application Support/DTE Chile` en
macOS). Nada se escribe dentro del paquete de la app.
"""
import argparse
import os
import sys


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--log-level", default="info")
    a = p.parse_args()
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    # Las páginas y los XSD van dentro del paquete; main.py y core/ los buscan junto a su
    # propio archivo, que PyInstaller deja en la carpeta del ejecutable.
    import uvicorn

    import main as motor  # noqa: F401 — importa la app FastAPI (y configura logging)

    uvicorn.run(motor.app, host=a.host, port=a.port, log_level=a.log_level)


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        # cwd lo fija el cascarón; si se arranca a mano, que al menos no escriba en el paquete
        if os.getcwd().startswith(getattr(sys, "_MEIPASS", "\0")):
            os.chdir(os.path.expanduser("~"))
    main()
