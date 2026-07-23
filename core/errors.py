"""
core/errors.py — Jerarquía de errores de dominio (compartida por la API REST y el
servidor MCP).

Objetivo: que la lógica de negocio (`core/*`) levante errores **tipados y con un
código estable** en vez de `ValueError`/`Exception` genéricos. Así:

  - La **API REST** los mapea a un JSON de error uniforme + status HTTP correcto
    (ver `api/errors.py`).
  - El **servidor MCP** los mapea a un error de herramienta legible para la IA
    (ver `mcp_server.py`).

Cada error lleva:
  - ``codigo``      : identificador estable, apto para máquinas (p.ej. ``"sin_folios"``).
                      NO cambiar sin razón: los clientes lo usan para ramificar.
  - ``mensaje``     : texto para humanos, en español.
  - ``detalle``     : dict opcional con contexto estructurado (folio, tipo_dte, etc.).
  - ``http_status`` : status HTTP sugerido (lo usa la capa REST).

Regla de oro: NUNCA meter secretos ni trazas internas en ``mensaje``/``detalle`` —
esos campos se serializan al cliente.
"""
from __future__ import annotations

from typing import Any, Optional


class DTEChileError(Exception):
    """Raíz de todos los errores de dominio del motor DTE.

    Usar las subclases; esta base solo se usa como 500 genérico controlado.
    """

    codigo: str = "error_interno"
    http_status: int = 500

    def __init__(
        self,
        mensaje: str,
        *,
        detalle: Optional[dict[str, Any]] = None,
        codigo: Optional[str] = None,
    ) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle = detalle or {}
        if codigo is not None:
            self.codigo = codigo

    def as_dict(self) -> dict[str, Any]:
        """Representación serializable (sin datos internos sensibles)."""
        d: dict[str, Any] = {"codigo": self.codigo, "mensaje": self.mensaje}
        if self.detalle:
            d["detalle"] = self.detalle
        return d

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.mensaje


# ---------------------------------------------------------------------------
# 4xx — errores atribuibles al cliente / a los datos de entrada
# ---------------------------------------------------------------------------
class ValidacionError(DTEChileError):
    """Datos de entrada inválidos (RUT malo, monto negativo, tipo no soportado…)."""

    codigo = "validacion"
    http_status = 422


class RecursoNoEncontrado(DTEChileError):
    """No existe el recurso pedido (DTE, CAF, negocio, certificado…)."""

    codigo = "no_encontrado"
    http_status = 404


class ConflictoError(DTEChileError):
    """El estado actual impide la operación (folio ya usado, duplicado…)."""

    codigo = "conflicto"
    http_status = 409


class FolioError(ConflictoError):
    """Problema con folios/CAF: fuera de rango, agotados, CAF vencido."""

    codigo = "folio"


class SinFoliosError(FolioError):
    """No quedan folios disponibles del tipo pedido (timbraje agotado/bloqueado)."""

    codigo = "sin_folios"


class CAFError(ValidacionError):
    """El CAF es inválido, corrupto, de otro RUT/tipo, o está vencido."""

    codigo = "caf"


class CertificadoError(ValidacionError):
    """El certificado .p12/.pfx no carga (clave errada, corrupto, vencido)."""

    codigo = "certificado"


class AutenticacionError(DTEChileError):
    """Credenciales faltantes o inválidas (login, token JWT)."""

    codigo = "autenticacion"
    http_status = 401


class AutorizacionError(DTEChileError):
    """Autenticado pero sin permiso para la operación."""

    codigo = "autorizacion"
    http_status = 403


# ---------------------------------------------------------------------------
# 5xx / servicio externo — el SII
# ---------------------------------------------------------------------------
class SIIError(DTEChileError):
    """Fallo comunicándose con el SII (red, timeout, HTTP 5xx, SOAP roto).

    Es un 502 porque el error es de un servicio *aguas arriba*, no nuestro.
    """

    codigo = "sii_comunicacion"
    http_status = 502


class SIIRechazoError(DTEChileError):
    """El SII procesó el documento y lo RECHAZÓ (trae su código, p.ej. DTE-3-101).

    Distinto de `SIIError`: aquí el SII respondió bien, pero rechazó el DTE. Se
    mapea a 422 (el documento/entrada no cumple las reglas del SII).
    """

    codigo = "sii_rechazo"
    http_status = 422

    def __init__(
        self,
        mensaje: str,
        *,
        codigo_sii: Optional[str] = None,
        detalle: Optional[dict[str, Any]] = None,
    ) -> None:
        det = dict(detalle or {})
        if codigo_sii:
            det["codigo_sii"] = codigo_sii
        super().__init__(mensaje, detalle=det)
        self.codigo_sii = codigo_sii
