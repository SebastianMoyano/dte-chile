# Mapa del repo

> Índice para ubicarte. **Carga solo la hoja que necesites** — no leas todo.
> Las reglas están en [`CONSTITUCION.md`](CONSTITUCION.md); el conocimiento caro del SII, en
> [`LECCIONES-SII.md`](LECCIONES-SII.md).

## Qué es esto

Motor de **facturación electrónica chilena (DTE)** para el **SII**: API REST + servidor MCP +
scripts de certificación. Un usuario, varias empresas propias, **self-hosted** (no SaaS).
Código y comentarios **en español**.

## Empieza por aquí según lo que vayas a hacer

| Quiero… | Lee |
|---|---|
| Entender el pipeline de emisión | `core/orchestrator.py::emitir_dte` + [`mapa/core.md`](mapa/core.md) |
| **Tocar la firma o el sobre** | 🛑 [`CONSTITUCION.md`](CONSTITUCION.md) L2 → `core/sobre.py` → [`LECCIONES-SII.md`](LECCIONES-SII.md) |
| Entender un **error del SII** | [`LECCIONES-SII.md`](LECCIONES-SII.md) (tiene índice por código) |
| **Saber POR QUÉ el SII rechazó** algo | skill **`correos-sii`** — el código solo llega por correo |
| Trabajar en la API o el MCP | [`mapa/interfaces.md`](mapa/interfaces.md) |
| Trabajar en scripts, tests o CAFs | [`mapa/scripts-y-tests.md`](mapa/scripts-y-tests.md) |
| Trabajar en boletas | [`LECCIONES-SII.md`](LECCIONES-SII.md#boletas-infraestructura-aparte) + `core/boleta.py`, `core/sii_boleta.py` |
| Entender la **certificación** (postular, proveedor, boleta vs factura) | [`CERTIFICACION.md`](CERTIFICACION.md) |
| Entender un **término** (CAF, TED, folio, RVD, voucher…) | [`GLOSARIO.md`](GLOSARIO.md) |
| Saber **con qué RUT/clave entrar a cada trámite del SII** (el rebote clásico) | [`IDENTIDADES-SII.md`](IDENTIDADES-SII.md) |
| **UF, UTM y dólar del día** (páginas oficiales del SII, caché en la tabla `valores`; el dólar oficial llega con rezago) | `nucleo/valores/` → `nucleo-valores actualizar|get|vigente|demonio`; lectura `GET /api/v1/valores` (+ `/historico?anio=`, `/{ind}/serie`); histórico desde 2015 cargado una vez (`nucleo-valores historico`), la app refresca el año en curso |
| **Endpoints internos del portal SII** (facade SDI/AA, auth por clave, verificación de actividades, TIBVS) | [`SII-ENDPOINTS.md`](SII-ENDPOINTS.md) → `tools/captura-sii/` |
| **Anular una boleta** (NC de anulación, portal MIPYME, trámites SII) | [`ANULAR-BOLETA.md`](ANULAR-BOLETA.md) |
| **Modelo de emisión** (voucher vs boleta, tarjetas, código 48, convivir con un POS) | [`MODELO-EMISION.md`](MODELO-EMISION.md) |
| **Emitir por el gratuito del SII** (empresa en MiPyme, NC de anulación por el portal) | [`MIPYME.md`](MIPYME.md) → `core/sii_mipyme.py` |
| **Volver a dibujar el PDF de un documento** (solo XML: emitidos por Go o importados) | `core/dte_xml.py` → `POST /api/v1/dte/documentos/{id}/pdf` |
| **App de escritorio** (Go + Wails, motor como sidecar o empaquetado con PyInstaller, clave efímera) | [`APP.md`](APP.md) → `app/`, `motor.spec` |
| **Portar el núcleo a Go/Rust** (plan por fases, criterios, riesgos) | [`PLAN-PORT.md`](PLAN-PORT.md) → `nucleo/` (Go; fases 1-4; `test_fase2.py`, `fase3_envio.py`, CI `.github/workflows/dorado.yml`) |
| **RVD / consumo de folios de boletas en Go** (programador, catch-up, registro) | `nucleo/rvd/` + `nucleo/servidor/rvd.go` (`GET /api/v1/rvd/estado`, `POST /rvd/procesar`, `GET /rvd/registros/{rut}`); vector dorado `tests/dorado/rvd/` |
| **Enviar boletas por el REST del SII desde Go** | `nucleo/sii/boleta.go` → `POST /api/v1/boletas/enviar`, `/boletas/estado` (solo Go; Python tenía el cliente sin ruta) |
| **Validar un XML contra el XSD del SII** (en Python y en Go, mismo veredicto) | `core/schema_validator.py` (lxml) · `nucleo/xsd/` (sin libxml2; vectores de paridad `tools/generar_xsd_vectores.py`) · `POST /api/v1/dte/validar-xml` en los dos motores |
| **Verificar que la salida no cambió / probar un port** (byte a byte, sin SII) | [`DORADO.md`](DORADO.md) → `test_dorado.py`, `tests/dorado/`, `core/reloj.py` |
| **Practicar sin riesgo** (EMPRESA DEMO SPA: mismo pipeline, CAF y certificado ficticios, sin envío) | [`APP.md`](APP.md) → `core/simulacion.py`, `test_simulacion.py` |
| **Enseñar a facturar y declarar** (curso por tramos, app para quien no sabe nada, videos) | [`aprender/00-plan.md`](aprender/00-plan.md) |

## El flujo, en una línea

```
folio (atómico) → TED (firmado con la llave del CAF) → XML del DTE
      → firma STANDALONE  →  sobre por STRING  →  envío al SII  →  persistencia
                    └────── core/sobre.py ──────┘
```

Punto de entrada único que rutea por tipo: **`core/orchestrator.py::emitir_documento`**
(39/41 → `EnvioBOLETA` + REST; el resto → `EnvioDTE` + SOAP).

## Estructura

| Ruta | Qué hay |
|---|---|
| `core/` | **Toda la lógica de negocio.** 35 módulos + `__init__` → [`mapa/core.md`](mapa/core.md) |
| `core/xsd/` | Esquemas oficiales del SII (ISO-8859-1 → usa `grep -a`) |
| `api/routes/` | 12 routers bajo `/api/v1` (incl. `mipyme`) → [`mapa/interfaces.md`](mapa/interfaces.md) |
| `main.py` | Composición: lifespan, gate de seguridad, scheduler del RVD |
| `mcp_server.py` | 20 herramientas MCP (los certs **no** viajan por el protocolo) |
| `static/` | 4 páginas: `onboarding.html` (wizard), `certificados.html` (panel, incl. Portal SII), `documentos.html` (emitidos, con PDF/XML), `apikeys.html` |
| Scripts en la raíz | Certificación, CAFs, F29, keystore → [`mapa/scripts-y-tests.md`](mapa/scripts-y-tests.md) |
| `test_*.py` | **Scripts planos, NO pytest** |
| `storage/` | Artefactos: `dtes/`, `pdfs/`, `cafs/`, `rvd/`, `resultados_*.json` |
| `.claude/agents/` | Agentes especializados (abajo) |
| `.claude/skills/` | `correos-sii`: lee los correos del SII y extrae el código de error |
| `tools/captura-sii/` | Extensión de Chrome Grabar/Detener para capturar un flujo real del portal del SII (con claves tachadas) + comparador contra lo que manda el módulo |

## Agentes

| agente | para qué |
|---|---|
| `dte-navegador` | buscar y explicar lo que ya existe (**empieza siempre por aquí**) |
| `dte-code-writer` | implementar respetando la constitución |
| `dte-code-reviewer` | revisar código contra la constitución y las trampas del SII |
| `dte-doc-reviewer` | revisar que los docs sigan siendo **verdad** |
| `dte-orquestador` | coordinar trabajo de varios pasos |

## Comandos

```bash
source .venv/bin/activate                     # Python 3.14
uvicorn main:app --reload --port 8000         # API (/docs, /redoc)

# Tests: scripts planos, no pytest
.venv/bin/python test_sobre.py                # ⭐ Ley L2: la firma que el SII acepta
.venv/bin/python test_boleta.py               # boletas + RVD + scheduler + guardarraíles
.venv/bin/python test_robustez.py             # errores, MCP, reintentos, hardening
.venv/bin/python test_mvp.py                  # smoke de módulos core
.venv/bin/python test_mipyme.py               # canal MIPYME en seco (no gasta folios)
```

## Estado del motor (2026-07-22)

| Área | Estado |
|---|---|
| **Emisión de facturas** | ✅ **verificada contra el SII** (TrackID 253113966 → `ACEPTADOS: 1`) |
| Firma (`core/sobre.py`) | ✅ verificada; la usan facturas, boletas, preview y la API |
| Timbraje de folios | ✅ automatizado (T34/T39/T41 libres; **T33 y T61 bloqueados** por anti-acaparamiento) |
| Emisión de boletas | ✅ **cableada y en producción** (`core/orchestrator_boleta.py` + `core/sii_boleta.py`, folio 1 aceptado con EPR) |
| RVD diario | ✅ se envía por `DTEUpload`/SOAP (`core/rvd.py::enviar_rvd`); **no es obligatorio en producción** desde 2022-08-01 (Res. Ex. SII 53/2022) |
| RCV / F29 | ✅ RCV **verificado en vivo** (2026-10-04, Auxin, sesión por clave: ventas y compras cuadran con la propuesta del SII) · F29: API de propuesta mapeada, envío (GWT-RPC) pendiente |
| Certificación de facturas | 🔴 bloqueada: folios T33/T61 en anti-acaparamiento |
| Certificación de boletas | ✅ **completa** — SOFTWARE DEMO SPA (78111111-2) autorizada en producción, emite boletas reales |
| Canal MIPYME (gratuito por httpx) | ✅ lectura, importación (PDF+XML), firma central y **emisión** verificadas desde el repo (2026-10-08: factura 63 + NC 60 de anulación, `CADENAS_VERIFICADAS` = {34, 61}) · NC de corrección de montos, ND y boletas siguen con `--acepto-riesgo-folio` · **en Go**: `nucleo/siiengine` segmento 1 (sesión, historial, PDF, XML, importar) verificado en vivo 2026-10-08; emisión aún solo en Python |

⚠️ `task.md` es un **registro histórico** con partes obsoletas. Cuando discrepe con el código,
**manda el código**.
