# Plataforma DTE Chile — Guía de arranque e integración

Motor **self-hosted** de emisión de Documentos Tributarios Electrónicos (DTE) y **boletas
electrónicas** para el SII de Chile. Firma, timbra, envía al SII, repone folios solo y expone
un buscador público de consulta. Pensado para **1 dueño que opera varias empresas propias**
(no SaaS multi-tenant).

> Este documento está hecho para copiarse tal cual y pasárselo a una IA que vaya a integrar o
> operar la plataforma. Todo lo esencial está aquí; los detalles internos viven en `docs/`.

---

## 1. Qué es automático vs. qué es manual

### ✅ Automático (el motor lo hace solo)
| Cosa | Cómo |
|---|---|
| **Emitir un DTE/boleta** | Un solo request: folio → TED → firma → sobre → envío al SII → PDF → BD. |
| **Resolución de carátula por empresa** | Se saca del registro del SII por RUT (`core/resolucion.py`); evita el `CRT-3-19`. |
| **Reposición de folios (estilo TUU/Haulmer)** | Cuando bajan del umbral, pide un CAF nuevo al SII solo (`core/folios_auto.py`). |
| **Notificación de eventos de folios** | POST a un webhook genérico que tú cableas a lo que quieras (`NOTIF_WEBHOOK_URL`). |
| **Consulta pública de boletas** | Buscador web + API en `/consulta` (el link que exige el SII). |
| **Envío por el canal correcto** | Boletas → REST (pangal/rahue); facturas/RVD → DTEUpload (maullin/palena). Automático por tipo/ambiente. |

### 🖐️ Autoatendido (guiado en la plataforma, con tu consentimiento)
- **Diagnóstico de puesta en marcha** (`/api/v1/onboarding/diagnostico`): lee tu situación en el SII y dice qué falta.
- **Certificación de boletas** (postular set, inscribir, declarar cumplimiento): automatizado por playwright con consentimiento explícito. Requiere tu **certificado del representante legal**.

### 🔴 Manual obligatorio (SÍ o SÍ humano; ver §2)
- Tener y subir el **certificado digital** (`.pfx`) del representante legal.
- El **proceso de certificación** ante el SII (esperar correos del SII, decisiones del rep legal).
- La **Verificación de Actividades** presencial en la Unidad del SII, si el SII la exige.
- **Nota RVD:** el Resumen de Ventas Diarias **ya NO es obligatorio** (Res. Ex. SII 53/2022, desde 2022-08-01). No hay que enviarlo. Correcciones se hacen con Nota de Crédito (tipo 61).

---

## 2. Arranque para un usuario nuevo (paso a paso obligatorio)

1. **Certificado digital.** Consíguelo (e-cert, etc.) a nombre del **representante legal** de la empresa. Súbelo una vez: `POST /api/v1/keystore/certificados` (multipart `.pfx` + password). Se guarda **cifrado** en BD, nunca en disco.
2. **Registra la empresa (negocio).** `POST /api/v1/keystore/negocios` con el RUT → se auto-completa razón social y se asocia al certificado (mandatario).
3. **Diagnostica.** `GET /api/v1/onboarding/diagnostico?rut=...&cert_id=...` → te dice si estás autorizado, qué tipos puedes emitir y qué falta.
4. **Certifica boletas** (si vas a emitir boletas y aún no estás habilitado): postular set → emitir los casos → enviar → solicitar revisión → **Declaración de Cumplimiento** (rep legal). Requiere declarar tu **Link de Consulta** (el buscador `/consulta` de tu dominio). El SII responde por correo con el V°B° y te habilita.
5. **Folios.** Baja los primeros folios (`solicitar_folios`); de ahí en adelante **se reponen solos**.
6. **Emite.** `POST /api/v1/dte/emitir` (ver §3). ✅ Operando.

> Muchas partes de la certificación (postulación, set, envío, declaración) están automatizadas
> con consentimiento; lo único no automatizable es **esperar los correos del SII** y los
> trámites presenciales que el SII exija.

---

## 3. API — emitir y operar (REST)

Base: `http://<host>:8000` (o tu dominio). Auth: `Authorization: Bearer <token>` (ver §5).

### Emitir un DTE o boleta (el endpoint que importa)
`POST /api/v1/dte/emitir` — rutea por tipo (39/41 = boleta; 33/34/56/61 = factura). Devuelve folio, TrackID, PDF y estado.

```bash
curl -X POST http://localhost:8000/api/v1/dte/emitir \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "dte": {
      "tipo_dte": 39, "emisor": {"rut": "78111111-2", ...},
      "receptor": {"rut": "66666666-6", "razon_social": "CONSUMIDOR FINAL"},
      "items": [{"numero_linea": 1, "nombre": "Servicio", "cantidad": 1, "precio_unitario": 1000}]
    }
  }'
```

### Otros endpoints útiles
| Método | Ruta | Para qué | Auth |
|---|---|---|---|
| POST | `/api/v1/dte/emitir` | Emitir (folio→firma→envío→BD) | Sí |
| POST | `/api/v1/dte/previsualizar` | Pre-vuelo (firma+PDF sin enviar) | Sí |
| GET | `/api/v1/estado/...` | Estado de un envío por TrackID | mixto |
| GET | `/api/v1/monitoreo/folios?rut=` | Salud de folios (restantes/estado) | Sí |
| GET | `/api/v1/db/dtes` | Listar DTE emitidos | Sí |
| GET | `/consulta` · `/consulta/api` | **Buscador público** (sin auth) | No |
| GET | `/health` · `/docs` | Salud / Swagger | No |

El buscador (`/consulta`) es **público a propósito** (es el Link de Consulta del SII); todo lo
demás debería quedar **detrás de auth y sin exponer a Internet** (ver §5).

---

## 4. Integración con IA (servidor MCP) — la vía recomendada

El motor incluye un **servidor MCP** (`mcp_server.py`) con ~20 herramientas listas para que una
IA opere el SII: `salud`, `diagnostico`, `salud_folios`, `situacion_folios`, `solicitar_folios`,
`previsualizar_dte`, **`emitir_dte`**, `enviar_dte`, `estado_envio`, `empresa_autorizada`, etc.

```bash
# Levantar el MCP por HTTP (auth por bearer)
MCP_AUTH_TOKEN="<una-clave-larga-aleatoria>" python mcp_server.py http 0.0.0.0 8090
```

- **Auth**: header `Authorization: Bearer <MCP_AUTH_TOKEN>` (o un JWT del proyecto).
- **Local sin red**: `python mcp_server.py` (stdio) — ideal para un agente en la misma máquina.
- Una IA solo necesita **la URL del MCP + el token**. Con eso descubre las herramientas y opera.

Este es el camino más simple para "pasar a una IA": apúntala al MCP con su token y ya entiende
todo el dominio (emitir, folios, estado, diagnóstico) sin que le expliques la API a mano.

---

## 5. Seguridad de endpoints — estado y recomendaciones

### Estado actual
- **Dos formas de auth, ambas por `Authorization: Bearer <token>`:**
  - **JWT** (usuarios): `POST /api/v1/auth/login` (usuario/clave) → token ~60 min. Para la UI y la gestión. Se crea un **usuario admin** en el 1er arranque con clave aleatoria impresa una vez al log.
  - **API key** (integraciones/agentes): clave estática `dte_...` que **no expira**. Créala en la UI **`/apikeys`** o con `POST /api/v1/apikeys` (requiere JWT). Se muestra **una sola vez**; en BD solo va su hash. Revocable.
- **Protegidos** (JWT o API key): prácticamente **todo** — `db/*`, `keystore/*`, `monitoreo/*`, `onboarding/*`, `caf/*`, `certificado/*`, `dte/*`, `estado/*`. La gestión de keys y usuarios exige **JWT** (una key no crea más keys).
- **Público a propósito**: solo `/consulta*` (buscador), `/health`, `/docs`, `/auth/login`.
- **MCP**: bearer `MCP_AUTH_TOKEN` o JWT.
- **Dominio público** (`boletas.tu-dominio.cl`): middleware que lo acota a **solo `/consulta*`**; el resto responde 404. Internet NO ve la API interna.

### Recomendaciones (lo justo para operar seguro)
1. **No expongas la API REST a Internet.** Deja pública solo `/consulta` (ya está). El NAT solo abre 80/443 → reverse proxy; el puerto del motor queda en la LAN.
2. **Para integraciones/IA: una API key** (UI `/apikeys`) o el **MCP con `MCP_AUTH_TOKEN`**. Ambas son bearer estáticos que no expiran — ideal para agentes. Rota/revoca cuando quieras.
3. **Mantén el usuario admin** solo para gestión (UI/REST) y **cambia su clave** tras el 1er arranque. Guarda `JWT_SECRET_KEY` y `DTE_MASTER_KEY` (cifra el keystore) fuera del repo.
4. **Una key por integración** (nómbralas): revocas una sin afectar las demás y ves el último uso en la UI.

---

## 6. Operación (lo que corre solo)

- **Despliegue**: contenedor Docker (Dockge), datos en volumen, `.env` montado. Ver `docs/` del repo.
- **Folios**: se reponen solos (`FOLIOS_AUTO_*`); si el SII bloquea (anti-acaparamiento), avisa "requiere humano" por el webhook.
- **Buscador**: `https://<tu-dominio>/consulta` — público, muestra solo boletas reales.
- **Ambiente**: `SII_AMBIENTE=certificacion|produccion` conmuta endpoints y resolución.

### Variables de entorno clave
| Variable | Para qué |
|---|---|
| `SII_AMBIENTE` | `certificacion` / `produccion` |
| `DATABASE_URL` | Ruta de la BD (SQLite) |
| `DTE_MASTER_KEY` | Cifra los certificados del keystore (¡guárdala!) |
| `JWT_SECRET_KEY` | Firma los JWT |
| `MCP_AUTH_TOKEN` | Token (API key) del servidor MCP para IA/integraciones |
| `NOTIF_WEBHOOK_URL` | A dónde notificar eventos de folios (tú lo cableas) |
| `FOLIOS_AUTO_*` | Umbral, lote, intervalo, cooldown, cert de respaldo |
| `DOMINIO_PUBLICO_BOLETAS` | Host público restringido solo al buscador |

---

## 7. TL;DR para una IA que va a integrar

1. Consíguete el **token MCP** (`MCP_AUTH_TOKEN`) y la **URL del MCP** (`.../mcp`, puerto 8090).
2. Descubre las herramientas; para emitir usa **`emitir_dte`** con un `DTEInput` (tipo 39 = boleta).
3. Vigila folios con **`salud_folios`** — pero se reponen solos; solo actúa si te llega un evento `folios_bloqueado`/`folios_error`.
4. Consulta estado con **`estado_envio`** por TrackID.
5. Nunca toques la firma ni el armado del sobre: el motor lo hace bien (regla dura del proyecto).
