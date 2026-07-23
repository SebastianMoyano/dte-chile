# Manejo de errores — API REST

Toda respuesta de error de la API usa un **envelope uniforme**. No hay respuestas de
error ad-hoc ni trazas internas filtradas al cliente.

Implementación: [`core/errors.py`](../core/errors.py) (errores de dominio) +
[`api/errors.py`](../api/errors.py) (handlers globales, request-id, logging).

## Esquema de la respuesta de error

```json
{
  "error": {
    "codigo": "sin_folios",
    "mensaje": "No quedan folios T61 disponibles",
    "detalle": { "tipo_dte": 61 },
    "request_id": "d2b6f0f0bb8a"
  }
}
```

- **`codigo`** — identificador estable, para máquinas. Ramifica tu cliente por este
  campo, no por el texto. No cambia entre versiones sin aviso.
- **`mensaje`** — texto para humanos, en español.
- **`detalle`** — contexto estructurado opcional (folio, tipo, errores de validación…).
- **`request_id`** — id de la petición; también viene en el header `X-Request-ID`.
  Cítalo al reportar un problema: correlaciona con los logs del servidor.

## Códigos de error

| `codigo` | HTTP | Significado | Origen (`core/errors`) |
|---|:--:|---|---|
| `validacion` | 422 | Datos de entrada inválidos (RUT, monto, tipo…). | `ValidacionError` |
| `no_encontrado` | 404 | El recurso no existe (DTE, CAF, negocio, cert). | `RecursoNoEncontrado` |
| `conflicto` | 409 | El estado impide la operación. | `ConflictoError` |
| `folio` | 409 | Folio fuera de rango / CAF inválido o vencido. | `FolioError` |
| `sin_folios` | 409 | Timbraje agotado o bloqueado (anti-acaparamiento). | `SinFoliosError` |
| `caf` | 422 | CAF inválido, corrupto, de otro RUT/tipo, o vencido. | `CAFError` |
| `certificado` | 422 | El `.p12`/`.pfx` no carga (clave errada, vencido). | `CertificadoError` |
| `autenticacion` | 401 | Credenciales faltantes o inválidas. | `AutenticacionError` |
| `autorizacion` | 403 | Autenticado pero sin permiso. | `AutorizacionError` |
| `sii_comunicacion` | 502 | Fallo hablando con el SII (red, timeout, HTTP 5xx). | `SIIError` |
| `sii_rechazo` | 422 | El SII procesó y **rechazó** el DTE (trae `codigo_sii`). | `SIIRechazoError` |
| `error_interno` | 500 | Bug/fallo inesperado. Traza al log, mensaje genérico. | (catch-all) |

Para `sii_rechazo`, `detalle.codigo_sii` trae el código del SII (ej. `DTE-3-101`
folio duplicado, `CAF-3-517` CAF vencido, `TED-2-510` timbre inválido).

## Cómo levantar errores en el código

En `core/` o en las rutas, levanta el error tipado — el handler global hace el resto:

```python
from core.errors import SinFoliosError, CAFError

if stock == 0:
    raise SinFoliosError("No quedan folios T61 disponibles", detalle={"tipo_dte": 61})
if not caf.es_folio_valido(folio):
    raise CAFError(f"El folio {folio} está fuera del rango del CAF")
```

No hace falta envolver cada ruta en `try/except`: cualquier excepción no manejada la
captura el handler global y se convierte en un `500` genérico (con la traza en el log,
nunca en la respuesta). Los errores de dominio conservan su `codigo` y status.

## Observabilidad

Cada petición recibe un `request_id` (header `X-Request-ID`, generado o tomado del
que envíe el cliente) y se registra una línea de acceso:

```
GET /api/v1/estado/track → 200 (48 ms) [rid=d2b6f0f0bb8a]
```

## Prueba

```bash
.venv/bin/python test_robustez.py    # verifica envelope, 404/422/500, request-id y MCP
```
