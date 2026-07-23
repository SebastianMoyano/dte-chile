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
| `core/` | **Toda la lógica de negocio.** 34 módulos + `__init__` → [`mapa/core.md`](mapa/core.md) |
| `core/xsd/` | Esquemas oficiales del SII (ISO-8859-1 → usa `grep -a`) |
| `api/routes/` | 11 routers bajo `/api/v1` → [`mapa/interfaces.md`](mapa/interfaces.md) |
| `main.py` | Composición: lifespan, gate de seguridad, scheduler del RVD |
| `mcp_server.py` | 20 herramientas MCP (los certs **no** viajan por el protocolo) |
| `static/` | 2 páginas: `onboarding.html` (wizard) y `certificados.html` (panel) |
| Scripts en la raíz | Certificación, CAFs, F29, keystore → [`mapa/scripts-y-tests.md`](mapa/scripts-y-tests.md) |
| `test_*.py` | **Scripts planos, NO pytest** |
| `storage/` | Artefactos: `dtes/`, `pdfs/`, `cafs/`, `rvd/`, `resultados_*.json` |
| `.claude/agents/` | Agentes especializados (abajo) |
| `.claude/skills/` | `correos-sii`: lee los correos del SII y extrae el código de error |

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
```

## Estado del motor (2026-07-22)

| Área | Estado |
|---|---|
| **Emisión de facturas** | ✅ **verificada contra el SII** (TrackID 253113966 → `ACEPTADOS: 1`) |
| Firma (`core/sobre.py`) | ✅ verificada; la usan facturas, boletas, preview y la API |
| Timbraje de folios | ✅ automatizado (T34/T39/T41 libres; **T33 y T61 bloqueados** por anti-acaparamiento) |
| Emisión de boletas | ✅ **cableada y en producción** (`core/orchestrator_boleta.py` + `core/sii_boleta.py`, folio 1 aceptado con EPR) |
| RVD diario | ✅ se envía por `DTEUpload`/SOAP (`core/rvd.py::enviar_rvd`); **no es obligatorio en producción** desde 2022-08-01 (Res. Ex. SII 53/2022) |
| RCV / F29 | ⚠️ lógica lista · falta smoke-test (solo hay datos en producción) |
| Certificación de facturas | 🔴 bloqueada: folios T33/T61 en anti-acaparamiento |
| Certificación de boletas | ✅ **completa** — SOFTWARE DEMO SPA (78111111-2) autorizada en producción, emite boletas reales |

⚠️ `task.md` es un **registro histórico** con partes obsoletas. Cuando discrepe con el código,
**manda el código**.
