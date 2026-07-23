# Servidor MCP — DTE Chile

El motor expone su toolkit del SII como un **servidor MCP** (Model Context Protocol),
para que una IA (Claude Desktop, Claude Code u otro cliente MCP) pueda ejecutar
acciones sobre el SII: consultar autorización de empresas, gestionar folios y
consultar el estado de envíos. Reusa el mismo `core/` que la API REST — una sola
lógica, una sola fuente de verdad.

Archivo: [`mcp_server.py`](../mcp_server.py). SDK: [`mcp`](https://pypi.org/project/mcp/) (FastMCP).

## Ejecutar

```bash
# stdio (para clientes MCP locales) — sin red, seguridad = frontera del proceso
.venv/bin/python mcp_server.py
# o con el CLI del SDK
.venv/bin/mcp run mcp_server.py

# HTTP (expone red → EXIGE bearer token, ver "Autenticación")
MCP_AUTH_TOKEN=un-secreto .venv/bin/python mcp_server.py --http 0.0.0.0 8090
```

Config en un cliente MCP (ej. Claude Desktop, `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "dte-chile": {
      "command": "/ruta/al/proyecto/.venv/bin/python",
      "args": ["mcp_server.py"],
      "cwd": "/ruta/al/proyecto",
      "env": { "MCP_CUENTA_ID": "1" }
    }
  }
}
```

## Manejo de credenciales (importante)

Los certificados **nunca** viajan por el protocolo. Cada herramienta que necesita
firma o mutual-TLS recibe un `cert_id` que apunta al **keystore cifrado**
(`core/keystore`, Fernet). El servidor descifra el `.p12` en memoria o lo escribe a un
PEM transitorio (permisos `600`, borrado al terminar) y nunca lo expone. La cuenta por
defecto es `MCP_CUENTA_ID` (env, default `1`).

Para ver los `cert_id` disponibles, usa la herramienta `listar_certificados`.

## Herramientas

| Herramienta | Cert | Qué hace |
|---|:--:|---|
| `salud` | — | Estado del servidor (ambiente, cuenta, nº de certificados). |
| `listar_certificados` | — | Certificados del keystore (id, RUT, nombre, vencimiento). |
| `listar_negocios` | — | Empresas registradas en la cuenta y su cert asociado. |
| `empresa_autorizada` | — | **Público:** DTE que un RUT está autorizado a emitir + resolución. |
| `diagnostico` | ✔ | Solo lectura: estado de una empresa en el SII + plan de acciones (`modo`: auto/consentimiento/humano). Primer paso del onboarding. |
| `diagnostico_cartera` | ✔ | Solo lectura: `diagnostico` para TODAS las empresas del certificado (resumen por empresa). |
| `salud_folios` | — | Solo local (sin SII): CAF vencidos (`CAF-3-517`, 6 meses) y folios agotándose de una empresa. |
| `salud_folios_cartera` | — | Solo local: `salud_folios` para todas las empresas cargadas, ordenado por urgencia. |
| `situacion_folios` | ✔ | Por tipo: si puede timbrar y si está bloqueado. |
| `timbrajes` | ✔ | Rangos de folios ya autorizados para un RUT/tipo. |
| `datos_software` | ✔ | Software de emisión registrado y resolución del contribuyente. |
| `empresas_del_certificado` | ✔ | Empresas asociadas al titular del certificado (mandatario). |
| `folios_anulables` | ✔ | Rangos de folios anulables (no recepcionados). |
| `estado_envio` | ✔ | Estado de un envío por TrackID (EPR/aceptado/rechazado + glosa). |
| `estado_envios` | ✔ | Estado de VARIOS TrackID de una vez + resumen accionable (aceptados/rechazados/pendientes/todos_resueltos). |
| `solicitar_folios` | ✔ | **Escritura:** timbra folios nuevos (consume cupo). |
| `anular_folios` | ✔ | **Escritura, irreversible:** anula un rango de folios no recepcionados. |
| `previsualizar_dte` | ✔ | Solo lectura: genera el DTE firmado+timbrado+XSD+PDF **sin enviar ni consumir folio** — "ver la factura" antes de emitir. |
| `emitir_dte` | ✔ | **Escritura:** emite un DTE completo (folio→TED→firma→PDF→EnvioDTE→BD). |
| `enviar_dte` | ✔ | **Escritura:** envía el EnvioDTE firmado al SII y devuelve el TrackID. |

Flujo completo de emisión con la IA: `emitir_dte` → tomar `xml_envio_b64` → `enviar_dte`
→ `estado_envio` (con el TrackID).

Convenciones de parámetros:
- **RUT**: con guión y DV, ej. `76111111-6`.
- **tipo_dte**: `33` Factura, `34` Factura Exenta, `39`/`41` Boletas, `52` Guía,
  `56` Nota Débito, `61` Nota Crédito.
- **ambiente**: `certificacion` (Maullín, pruebas) o `produccion` (Palena). Default:
  el de `settings.sii_ambiente`.

## Autenticación

- **stdio** (default): el cliente MCP lanza el proceso localmente; no expone red. La
  seguridad es la frontera del proceso del sistema operativo — no hay auth por request.
- **HTTP** (`--http`): expone red, así que **exige** un bearer token en cada request:
  `Authorization: Bearer <token>`, donde el token es:
  - el **secreto compartido** `MCP_AUTH_TOKEN` (env), útil para clientes máquina; o
  - un **JWT del proyecto** (el mismo que emite `POST /api/v1/auth/login`), verificado
    con `core/auth`.
  Sin un token válido, el gate ASGI responde `401` antes de tocar cualquier herramienta.

> Modelo (NO es SaaS): **un solo usuario autohospedado administra varias empresas
> propias**. Por eso hay UNA cuenta (`MCP_CUENTA_ID`, default 1) que agrupa todas las
> empresas (`negocios`), y la auth solo protege el acceso al servidor. No hay
> multi-tenant por diseño — es correcto que la cuenta sea única.

## Errores

Las herramientas convierten los [errores de dominio](./ERRORES-API.md) en un
`ToolError` legible con el código estable entre corchetes, ej.
`[sin_folios] No quedan folios T61 disponibles`. Los fallos inesperados se registran
con traza completa en el log del servidor y devuelven un mensaje genérico (sin filtrar
internos).

## Añadir una herramienta

```python
@herramienta                       # registra en MCP + unifica manejo de errores
def mi_accion(rut: str, cert_id: int, ambiente: str = AMBIENTE_DEFECTO) -> dict:
    """Docstring = descripción que ve la IA. Sé claro y conciso."""
    with _portal_con_cert(cert_id, ambiente) as portal:
        return portal.mi_metodo(rut)
```

Levanta errores de `core/errors` (`ValidacionError`, `SinFoliosError`, `SIIError`, …);
el decorador los mapea solo. Devuelve dicts/listas/dataclasses (se serializan solos).
