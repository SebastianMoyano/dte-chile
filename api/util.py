"""
api/util.py — utilidades compartidas de las rutas.
"""
from fastapi import UploadFile

from core.errors import ValidacionError

# Tope de tamaño de archivos subidos. CAF y certificados pesan KB; 5 MB sobra y evita
# que un upload gigante (accidental o malicioso) cargue toda la RAM (OOM/DoS).
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


async def leer_upload(archivo: UploadFile, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Lee un `UploadFile` ACOTADO a `max_bytes`; levanta `ValidacionError` si se pasa.

    No lee más de `max_bytes + 1`, así que un archivo enorme nunca entra entero en RAM.
    """
    limite_mb = max_bytes // (1024 * 1024)
    if getattr(archivo, "size", None) and archivo.size > max_bytes:
        raise ValidacionError(f"Archivo demasiado grande (máximo {limite_mb} MB).")
    data = await archivo.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValidacionError(f"Archivo demasiado grande (máximo {limite_mb} MB).")
    return data
