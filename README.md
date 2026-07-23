# 🧾 DTE Chile — Motor de Documentos Tributarios y Boletas Electrónicas

Motor **self-hosted** en **Python + FastAPI** para emitir Documentos Tributarios Electrónicos
(DTE) y **boletas electrónicas** ante el **SII de Chile**. Firma, timbra, envía al SII por el
canal correcto, **repone folios solo**, y expone un buscador público de consulta.

> Pensado para **un dueño que opera varias empresas propias** (self-hosted), no como SaaS
> multi-tenant.

### 👉 ¿Primera vez? Empieza por la **[Guía de inicio rápido](docs/INICIO-RAPIDO.md)** — de cero a tu primer documento en ~20 min.

## Qué hace

- **Emite factura y boleta** (33/34/39/41/52/56/61) — un solo request: folio → TED → firma → sobre → envío al SII → PDF → BD.
- **Firma XMLDSig compatible con el SII** (RSA-SHA1 + C14N; DTE firmado *standalone* e insertado *verbatim* en el sobre — la forma que el SII acepta).
- **Envía por el canal correcto según tipo/ambiente**: boletas por REST (pangal/rahue); facturas y RVD por DTEUpload (maullin/palena). El **set de certificación de boletas** va por DTEUpload.
- **Resolución de carátula por empresa** (la saca del registro del SII por RUT — evita el `CRT-3-19`).
- **Reposición automática de folios** (estilo TUU/Haulmer): cuando bajan del umbral, pide un CAF nuevo al SII solo y avisa por un **webhook genérico**.
- **Buscador público de consulta** (`/consulta`) — el "Link de Consulta" que exige el SII, con descarga de PDF y XML.
- **PDF con timbre PDF417** (carta y 80 mm térmico para boletas).
- **Auth por JWT o API key**, y un **servidor MCP** para operar todo desde una IA/agente.

## Estado

**Listo para producción.** Pipeline de emisión verificado contra el SII vivo (facturas y
boletas aceptadas), certificación de boletas completada end-to-end, y desplegable por Docker.

## Instalación

### Docker (recomendado)
```bash
cp .env.example .env          # editar: SII_AMBIENTE, secretos, empresa
docker-compose up -d
docker-compose logs -f
```

### Local (Python 3.12+)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python setup.py               # crea .env, la BD SQLite y el usuario admin (imprime su clave 1 vez)
uvicorn main:app --reload --port 8000
```

Docs interactivas: **Swagger** en `/docs`, **ReDoc** en `/redoc`.

## Autenticación

Todo se autentica con `Authorization: Bearer <token>`. Hay dos formas:

- **JWT** (usuarios, para la UI/gestión): `POST /api/v1/auth/login` → token ~60 min. Se crea un **admin** en el primer arranque con clave aleatoria impresa una vez al log.
- **API key** (integraciones/agentes, no expira): créala en la UI **`/apikeys`** o con `POST /api/v1/apikeys` (requiere JWT). Se muestra una sola vez; en BD solo va su hash.

Para una **IA**, levanta el MCP: `MCP_AUTH_TOKEN=<clave> python mcp_server.py http 0.0.0.0 8090`.

## Endpoints principales

| Método | Ruta | Descripción | Auth |
|---|---|---|---|
| `POST` | `/api/v1/dte/emitir` | **Emitir** DTE/boleta orquestado (folio→firma→envío→BD) | Sí |
| `POST` | `/api/v1/dte/previsualizar` | Pre-vuelo (firma + PDF sin enviar) | Sí |
| `POST` | `/api/v1/estado/track` | Estado de un envío por TrackID | Sí |
| `GET` | `/api/v1/monitoreo/folios?rut=` | Salud de folios | Sí |
| `GET` | `/api/v1/db/dtes` | Listar DTE emitidos | Sí |
| `POST` · `GET` · `DELETE` | `/api/v1/apikeys` | Gestionar API keys | Sí (JWT) |
| `GET` · `POST` | `/consulta` · `/consulta/api` | **Buscador público** (+ `/consulta/pdf`, `/consulta/xml`) | No |
| `GET` | `/health` · `/docs` | Salud / Swagger | No |

**Seguridad:** `caf/*`, `certificado/*`, `dte/*`, `estado/*`, `db/*`, `keystore/*`, `monitoreo/*`,
`onboarding/*` están **protegidos** (JWT o API key). Público a propósito: solo `/consulta*`,
`/health`, `/docs`, `/auth/login`. **No expongas la API REST a Internet** — deja pública solo
`/consulta` (hay un middleware que acota el dominio público del buscador). Detalle en
[`docs/PLATAFORMA.md`](docs/PLATAFORMA.md) §5.

## Configuración (`.env`)

| Variable | Para qué |
|---|---|
| `SII_AMBIENTE` | `certificacion` / `produccion` |
| `DATABASE_URL` | Ruta de la BD SQLite |
| `DTE_MASTER_KEY` | Cifra los certificados del keystore (¡guárdala!) |
| `JWT_SECRET_KEY` | Firma los JWT (`openssl rand -hex 32`) |
| `MCP_AUTH_TOKEN` | Token del servidor MCP para IA/integraciones |
| `NOTIF_WEBHOOK_URL` | Webhook para notificar eventos de folios (tú lo cableas) |
| `FOLIOS_AUTO_*` | Umbral, lote, intervalo, cooldown de la reposición automática |
| `DOMINIO_PUBLICO_BOLETAS` | Host público restringido solo al buscador |

Los certificados `.p12/.pfx` se cifran en la BD (nunca en disco), y el `.env`/`.db`/`storage/` están gitignored.

## Tipos de DTE soportados

| Tipo | Nombre |
|---|---|
| 33 · 34 | Factura afecta · exenta |
| 39 · 41 | Boleta afecta · exenta |
| 52 | Guía de Despacho |
| 56 · 61 | Nota de Débito · Crédito |

## Documentación

- [`docs/INICIO-RAPIDO.md`](docs/INICIO-RAPIDO.md) — **empieza aquí**: de cero a emitir, paso a paso.
- [`docs/PLATAFORMA.md`](docs/PLATAFORMA.md) — guía de arranque e integración (para humano o IA).
- [`docs/CONSTITUCION.md`](docs/CONSTITUCION.md) — reglas inviolables del motor (firma, resolución, secretos).
- [`docs/LECCIONES-SII.md`](docs/LECCIONES-SII.md) — errores del SII y cómo se resolvieron (conocimiento caro).
- [`docs/CERTIFICACION.md`](docs/CERTIFICACION.md) · [`docs/MCP.md`](docs/MCP.md) · [`docs/MAPA.md`](docs/MAPA.md).

## Licencia

**Copyright © 2026 Extralatte.** Distribuido bajo la **GNU Affero General Public License v3.0
(AGPL-3.0)** — ver [`LICENSE`](LICENSE). En resumen: puedes usarlo, modificarlo y ofrecerlo como
servicio, pero **si lo ofreces por red (SaaS) debes publicar tus modificaciones** bajo la misma
licencia.

## Créditos y atribución

El formato de los documentos, sobres y reportes que exige el SII se implementó desde las
**especificaciones oficiales del SII** (XSD, instructivos, resoluciones). Se consultó
[**LibreDTE**](https://www.libredte.cl) (© SASCO SpA, AGPL-3.0) como **referencia** del
comportamiento correcto del SII en varios puntos. Este proyecto es una **implementación
independiente en Python**: no incluye código de LibreDTE, pero reconocemos su valor como fuente
de consulta de la comunidad DTE chilena.
