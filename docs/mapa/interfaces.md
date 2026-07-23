# Mapa — Interfaces (API REST, MCP, frontend)

> Hoja del [`MAPA.md`](../MAPA.md). Cárgala solo si trabajas en `main.py`, `api/`,
> `mcp_server.py` o `static/`.

## Arquitectura: hay DOS generaciones de API conviviendo

Esto explica casi todo lo raro de esta capa:

| | **vieja** | **nueva** |
|---|---|---|
| certificado | en el **body** de cada request | `cert_id` → keystore cifrado |
| auth | **ninguna** | JWT |
| routers | `certificado`, `caf`, `dte/generar\|enviar`, `estado/track\|dte` | `keystore`, `onboarding`, `monitoreo`, `dte/emitir\|previsualizar`, `estado/lote` |
| quién la usa | **nadie** (solo el README) | frontend y **MCP** |

La vieja **no está deprecada ni cerrada**, y es la que carga los agujeros de auth. Los
endpoints nuevos y mejor diseñados son justo los "huérfanos" del frontend: su consumidor
real es el **MCP**, no el HTML.

## `main.py` — composición

Lifespan (`main.py:51-115`), en orden: banner → **gate de seguridad** (avisa siempre;
**aborta si `es_produccion`**, `:61-67`) → `ensure_directories()` → `init_db()` → **admin con
password aleatoria** mostrada una sola vez (`:78-97`) → **scheduler RVD** (`:103-107`).
Al apagar: `await programador.detener()`.

- **Gate** (`core/config.py:143-158`): JWT por defecto/corto, `DTE_MASTER_KEY` ausente, CORS `*`.
- **CORS**: `allow_credentials = not _cors_wildcard` (`:183`) — la spec prohíbe `*` + credenciales.
- Rutas de páginas: `/certificados` (`:209`), `/onboarding` (`:216`), `/health` (`:237`).

## Endpoints — dónde mirar

11 routers bajo `/api/v1`: `auth`, `certificado`, `caf`, `dte`, `status`, `db`, `keystore`,
`onboarding`, `monitoreo`, `apikeys`, `consulta`.

`certificado`, `caf`, `dte` y `status` están protegidos **a nivel de router** en `main.py`
(`dependencies=[Depends(requerir_autenticacion)]`); el resto (`db/*`, `keystore/*`,
`onboarding/*`, `monitoreo/*`, `auth/usuarios|me`) lo exige **por endpoint** con la misma
dependencia. `requerir_autenticacion` acepta indistintamente un **JWT o una API key**
(`core/apikeys.py`, gestionadas vía `/apikeys` con JWT — una key no puede crear más keys).

Los que importan para emitir:
- `POST /api/v1/dte/emitir` (`dte.py:281`) — orquestado; **rutea 39/41 a EnvioBOLETA** (`:287`).
- `POST /api/v1/dte/previsualizar` — firma+TED+XSD+PDF **sin enviar ni consumir folio**.
- `GET /api/v1/keystore/negocios/{id}/f29` — **solo lectura, NO declara nada al SII** (`keystore.py:260`).
- `GET /api/v1/keystore/negocios/{id}/estado` — máquina de estados de migración
  (`keystore.py:183-190`): `emitiendo` → `certificado` → `certificando` → `sin_propio`.

**Errores** (`api/errors.py`): envelope `{"error":{codigo,mensaje,detalle?,request_id?}}`.
`DTEChileError` → su `http_status` sin traza (`:91`); `Exception` → 500 genérico con
`logger.exception` (**traza al log, nunca al cliente**, `:109`). Middleware `_request_context`
inyecta `X-Request-ID`. `codigo` es **contrato estable**: no cambiarlo (`core/errors.py:14`).

**Uploads** (`api/util.py`): `leer_upload()`, tope **5 MB**, nunca lee el archivo entero en
RAM. Cobertura completa de los `UploadFile` del proyecto.

## MCP (`mcp_server.py`) — 20 herramientas

- **Los certificados NO viajan por el protocolo** (`:11-15`): se pasa `cert_id`; el server
  descifra a un PEM transitorio **600, borrado en `finally`** (`core/keystore.py:171-198`).
- `@herramienta` (`:91-110`): serializa → `DTEChileError` → `ToolError("[codigo] mensaje")` →
  cualquier otra excepción se loguea con traza y devuelve mensaje genérico.
- `PortalSIICtx` (`:118-134`): keystore → PEM transitorio → `PortalSII` → `autenticar()`.
- **Auth** (`:395-435`): en **stdio no aplica** (la frontera es el proceso); sobre **HTTP**
  exige `Authorization: Bearer` — acepta `MCP_AUTH_TOKEN` (con `hmac.compare_digest`, `:407`)
  o un JWT del proyecto. Middleware **ASGI puro** para no bufferizar el streaming (`:415`).

**Acciones reales** (marcadas en sus docstrings): `solicitar_folios` (consume cupo de
timbraje), `anular_folios` (**irreversible**), `enviar_dte` (envía al SII), `emitir_dte`
(consume folio y persiste; **no** envía).

## Frontend (`static/`)

Dos páginas enlazadas entre sí: `onboarding.html` (wizard, estado en el objeto plano `S`,
router = cascada de guardas en `render()`) y `certificados.html` (panel: certs, negocios,
timbraje, estado, F29). Estado compartido: solo `localStorage` (`dte_token`, `dte_theme`)
→ same-origin con header `Authorization`, **sin cookies**.

Promesas de confianza que la UI le hace al usuario (y que el código debe honrar):
*"Tu certificado no sale de tu equipo"* (`onboarding.html:306`), *"Se guarda cifrado en tu
equipo"* (`:190`), *"nunca en texto plano"* (`certificados.html:276`).

## ⚠️ Deuda conocida (verificada 2026-07-16)

| Sev | Qué | Dónde |
|:-:|---|---|
| 🔴 | **`POST /auth/registro` NO exige JWT** aunque su docstring afirma que sí → registro abierto ⇒ token válido ⇒ acceso a keystore, negocios, F29 y BD | `api/routes/auth.py:99-131` |
| 🟡 | `except Exception: pass` traga el fallo al desactivar el CAF anterior → quedan **dos CAF activos**, violando en silencio el invariante declarado 8 líneas antes | `db.py:240-249` |
| 🟡 | El FE lee `d.detail` pero el envelope es `{error:{mensaje}}` ⇒ **nunca muestra el error real** | `certificados.html:437,626` |
| 🟡 | `certificados.html` no maneja 401 salvo en `cargarCerts`/`cargarNegs` → token expirado se ve como "No se pudo consultar el SII" | `certificados.html:501-512` |
| 🟡 | El botón "Autorizar y hacer" del wizard es un **no-op**: dice que registra el consentimiento y no registra nada | `onboarding.html:313-324` |
| 🟡 | El comentario de sección del MCP clasifica como "ESCRITURA" a `estado_envios` y `previsualizar_dte`, que son de lectura | `mcp_server.py:280-282` |
| 🔵 | Import muerto `obtener_usuario_por_username` | `main.py:27` |
| 🔵 | 7 endpoints huérfanos: `dte/validar-xml`, `dte/previsualizar`, `dte/emitir`, `estado/lote`, `onboarding/cartera`, `monitoreo/folios`, `monitoreo/folios/cartera` | — |

**Resuelto desde la auditoría** (2026-07-22): `certificado/firmar-datos`, `dte/generar`,
`dte/enviar`, `estado/track`, `estado/dte` ya no aceptan `.p12`+password sin auth — sus routers
(`certificado`, `dte`, `status`) quedaron protegidos **a nivel de router** en `main.py`.
