#!/usr/bin/env python3
"""Claves del SII en el keystore (canal gratuito): se guardan cifradas solo a pedido, el estado
no revela valores, se descifran solo para uso interno, y se olvidan. Base temporal."""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="claves_"))
os.environ["DATABASE_URL"] = f"sqlite:///{TMP}/k.db"
os.environ["DTE_MASTER_KEY"] = "N5XocTCf4chC1T6lnoGbPbbl84WAIx-RiZMeTy4jkvM="
sys.path.insert(0, str(Path(__file__).parent))
from core import database, keystore  # noqa: E402

assert str(database.DATABASE_PATH).startswith(str(TMP))
database.init_db()
ok = 0


def check(c, m):
    global ok
    print(("  ✓ " if c else "  ✗ ") + m)
    if not c:
        sys.exit(1)
    ok += 1


e = keystore.estado_claves_sii(1, "77777777-7")
check(not e["tiene_tributaria"] and not e["tiene_certificado"], "sin claves al inicio")
keystore.guardar_claves_sii(1, "77777777-7", "12345678-5", "clave-trib-demo", None)
e = keystore.estado_claves_sii(1, "77777777-7")
check(e["tiene_tributaria"] and not e["tiene_certificado"] and e["rut_usuario"] == "12345678-5", "guarda tributaria + rut usuario, sin certificado")
check("clave-trib-demo" not in str(e), "el estado no revela la clave")
fila = database.obtenerUno("SELECT tributaria_cifrada FROM claves_sii")
check(b"clave-trib-demo" not in bytes(fila["tributaria_cifrada"]), "en la base va cifrada")
keystore.guardar_claves_sii(1, "77777777-7", None, None, "clave-cert-demo")
c = keystore.obtener_claves_sii(1, "77777777-7")
check(c == {"rut_usuario": "12345678-5", "tributaria": "clave-trib-demo", "certificado": "clave-cert-demo"}, "actualizar certificado conserva lo demás")
check(keystore.obtener_claves_sii(2, "77777777-7")["tributaria"] == "", "otra cuenta no ve nada")
check(keystore.eliminar_claves_sii(1, "77777777-7") and not keystore.estado_claves_sii(1, "77777777-7")["tiene_tributaria"], "olvidar")
import shutil; shutil.rmtree(TMP, ignore_errors=True)
print(f"\nTodo OK ({ok} checks)")
