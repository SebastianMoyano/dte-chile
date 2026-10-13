# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> ## 🛑 Antes de tocar nada: lee `docs/CONSTITUCION.md`
>
> Son **leyes inviolables**, cada una pagada con días de trabajo o con plata real del
> contribuyente. Es corto. La #1 en importancia: **la firma del DTE se hace solo con
> `core/sobre.py`** — firmar el DTE embebido en el sobre, o re-serializar después de firmar,
> hace que el SII lo rechace con `DTE-3-505`.
>
> **Descubrimiento progresivo** — carga solo lo que necesites:
>
> | archivo | cuándo |
> |---|---|
> | [`docs/CONSTITUCION.md`](docs/CONSTITUCION.md) | **siempre**, antes de escribir código |
> | [`docs/MAPA.md`](docs/MAPA.md) | para ubicar algo en el repo (índice → hojas) |
> | [`docs/LECCIONES-SII.md`](docs/LECCIONES-SII.md) | ante **cualquier error del SII** o si tocas firma/certificación |
>
> Agentes especializados en `.claude/agents/`: `dte-navegador` (buscar), `dte-code-writer`
> (implementar), `dte-code-reviewer`, `dte-doc-reviewer`, `dte-orquestador` (coordinar).
>
> **Lección más cara del proyecto**: la solución al `DTE-3-505` llevaba días escrita en un
> comentario de `certificacion_sii.py` mientras se probaban 11 variantes de firma contra el
> SII vivo. **Lee el repo antes de experimentar.**

> There is also an `AGENTS.md` with overlapping, more command-oriented notes. This file focuses on the "why" and the cross-file architecture. When they disagree, prefer what the code says.

## What this is

**Faro** (antes "DTE Chile"; repositorio `SebastianMoyano/faro-dte`, **beta**) es un proyecto para bajar las barreras de la
facturación electrónica en Chile: hecho por un emprendedor para emprendedores. Está **migrando de servidor a app de escritorio**
(la facilidad de uso manda) y el motor existe en Python (referencia), Go y Rust para correr en toda plataforma sin instalar nada.
Los principios P1 a P5 están al final de `docs/CONSTITUCION.md`; léelos junto con las leyes.

Chilean electronic-invoicing engine (**DTE** = Documento Tributario Electrónico) for the **SII** (Chile's tax authority). FastAPI REST API plus a set of standalone scripts used to drive SII **certification** (the SII's mandatory 16-case test suite that must pass before a company can emit real documents). Codebase, comments, and identifiers are in **Spanish** — match that when writing new code.

## Commands

```bash
# Always use the project venv (Python 3.14). Interpreter: .venv/bin/python
source .venv/bin/activate

python setup.py                              # create .env, SQLite DB, admin user
uvicorn main:app --reload --port 8000        # run API (docs at /docs, /redoc)
docker-compose up -d                         # run containerized (volume: dte-chile-data)

# Tests are plain scripts, not pytest — run them directly:
.venv/bin/python test_mvp.py                 # core modules smoke test (no server)
.venv/bin/python test_orchestrator.py        # end-to-end orchestrator integration test

# Certification workflow (see docs/CERTIFICACION.md):
.venv/bin/python dry_run_certificacion.py    # generate+validate 16 cases locally, NO network
.venv/bin/python certificacion_sii.py        # generate + SOAP-send 16 cases to SII (needs cert password)
./ejecutar_certificacion.sh                  # wrapper: prompts cert password, then runs the above
.venv/bin/python solicitar_caf_sii.py --tipo 61 --cantidad 100   # request CAF folios from SII
.venv/bin/python load_cafs.py                # load CAF XML files into the DB
```

Admin user created on first boot with a **random password** printed once to the log (or `ADMIN_PASSWORD` if set).

## Architecture

Request/CLI flow: **assign folio → build TED (stamp) → generate DTE XML → sign → package into EnvioDTE → send to SII → persist**. `core/orchestrator.py::OrquestadorDTE.emitir_dte` is the canonical implementation of this whole pipeline and the best single file to read first — the certification scripts reimplement the same steps inline.

**El paso de firma+empaquetado es el más delicado de todo el motor y vive en `core/sobre.py`.**
El SII verifica la firma del DTE extrayéndolo como documento independiente, así que el DTE se
firma *standalone* y el sobre se arma **concatenando strings** con el DTE insertado verbatim —
nunca se re-serializa lo firmado. Verificado contra el SII (TrackID 253113966 → `ACEPTADOS: 1`).
Ver [`docs/LECCIONES-SII.md`](docs/LECCIONES-SII.md).

**`core/` — business logic (no FastAPI imports):**
- `orchestrator.py` — orchestrates the full emission pipeline (folio → TED → XML → sign → PDF → EnvioDTE → DB).
- `dte.py` — Pydantic models (`DTEInput`, `EmisorModel`, `ReceptorModel`, `ItemDTE`), `GeneradorDTE` (builds the DTE + `EnvioDTE` XML), `calcular_totales`, and the `TipoDTE` enum (33/34/39/41/52/56/61). **Element order in the XML is XSD-significant** — the SII rejects out-of-order tags; changes here are validated against `core/xsd/`.
- `caf.py` — `ManejadorCAF` parses the SII's CAF folio-authorization file and generates the **TED** (the PDF417 stamp). Critically: the TED is signed with **the CAF's own private key**, NOT the taxpayer's certificate.
- `crypto.py` — `CertificadoDigital` (loads `.p12`/`.pfx` in memory) and `firmar_documento_xml` (XMLDSig). Must be **RSA-SHA1 + C14N** for SII compatibility, not SHA-256.
- `sii.py` — `ClienteSII` SOAP client. Auth is seed→sign→token (`obtener_semilla`/`obtener_token`, token ~1h). `AmbienteSII` selects Maullín (certificación) vs Palena (producción) URLs.
- `database.py` / `models.py` — thin SQLite layer + CRUD. Tables: `dtes`, `cafs`, `audit_log`, `usuarios`. Folio consumption (`consumir_siguiente_folio`) is **atomic via `BEGIN IMMEDIATE`** to avoid a TOCTOU race — preserve that when touching folio logic.
- `pdf_gen.py` — ReportLab PDF with the PDF417 TED stamp; `NOMBRES_DTE` maps type→label.
- `rut.py` — Chilean RUT validator (módulo 11). `auth.py` — JWT; passwords use `sha256_crypt` (deliberately not bcrypt — a passlib/bcrypt version incompatibility).

**`api/routes/` — FastAPI routers**, one per domain (`apikeys`, `auth`, `caf`, `certificado`, `consulta`, `db`, `dte`, `keystore`, `mipyme`, `monitoreo`, `onboarding`, `simulacion`, `status`, `valores` — 14 total), all mounted under `/api/v1` in `main.py`. `certificado`, `caf`, `dte` y `status` están protegidos a nivel de router (`dependencies=[Depends(requerir_autenticacion)]` en `main.py`); `requerir_autenticacion` (`core/auth.py`) acepta **JWT o API key** (`core/apikeys.py`, UI en `/apikeys`).

**`core/config.py`** — single `settings` singleton (pydantic-settings, reads `.env`). Import it, don't read env vars directly.

**El motor también existe en Rust** (`nucleo-rs/`, fase 8 de `docs/PLAN-PORT.md`, 2026-10-12): mismos gates que Go
(corpus dorado 15/15, esquema dorado 23/23, contrato dorado Python vs Rust 203/203, MCP con 20 tools), ver
`nucleo-rs/README.md`. **Rust es el destino final del port.** La app de escritorio se llama **Faro** desde 2026-10-12 (antes "DTE Chile";
carpeta de datos `Faro`, la antigua se renombra sola; nombres internos sin cambio: paquete `dtechile`, binarios `nucleo-*`, conector MCP `dte-chile`).
Hay dos apps con **la misma interfaz** (`app/frontend/dist`): **Faro en Tauri (`app-rs/`, motor Rust adentro) es la que se publica**;
la Wails (`app/`, motor Go adentro; define los mismos 15 bindings desde Go, mientras que en Tauri los define `tauri.js`) es la construcción alternativa mientras dura la transición.
Dirección: de servidor + panel web a app fácil de usar; la versión web (`/app`, servida por cualquiera de los motores) queda para la sala de clases.

**El motor también existe en Go** (`nucleo/`, fase 7 de `docs/PLAN-PORT.md`, cerrada 2026-10-11): `nucleo/servidor` atiende
todas las rutas de la API Python con el mismo contrato que FastAPI (`tools/contrato_api.py` lo exige idéntico) más las
propias de Go (boletas REST, RVD, MCP), y la app de escritorio (`app/`) lo corre en su propio proceso, sin Python.
Lo que quedó distinto a propósito (PDF no byte a byte, sin Swagger) está decidido en `docs/COMPARACION-PYTHON-GO.md`. Python sigue siendo la referencia que fija el
comportamiento (corpus dorado, contrato dorado); cualquier cambio en una ruta se hace en los tres motores (Python, Go, Rust) y se mide.

## Conventions & gotchas

- **XML for the SII is `ISO-8859-1`, not UTF-8**, and sent without pretty-printing. The DB stores the signed XML decoded as ISO-8859-1.
- **`EPR` NO significa "aceptado"** — significa "Envío Procesado" (el *sobre* se procesó). El veredicto está en `ACEPTADOS`/`RECHAZADOS`. Este malentendido tuvo al proyecto creyendo que el pipeline funcionaba mientras el SII rechazaba todo.
- **La resolución del SII depende del ambiente y de la empresa** (L4): para la carátula usa `core.resolucion.resolucion_emisor(rut)`; `settings.resolucion` es solo el valor por defecto del ambiente. Nunca `sii_fecha_resolucion`/`sii_numero_resolucion` a pelo (son los de producción → `CRT-3-19` en certificación).
- `.p12`/`.pfx` certificates are processed **in memory only** — never persist them to disk or the DB. A local `firma.pfx` (path configurable via `DTE_CERT_PATH`) is used as a dev fallback.
- Certification status: the boleta certification (39/41) is **complete** (2026-07-22, `docs/CERTIFICACION.md`); facturas in certification are accepted but the full 16-case set still depends on T33/T61 folios the SII rate-limits (`docs/LECCIONES-SII.md`). Read those two docs before working on certification; the old `task.md` is a local, git-ignored history file.
- Generated artifacts live under `storage/` (`dtes/`, `pdfs/`, `cafs/`, and `dtes_cert/`/`pdfs_cert/` for certification runs); results summaries are `storage/resultados_*.json`.
- Adding a new DTE type: extend `TipoDTE` in `core/dte.py`, add to `NOMBRES_DTE` in `core/pdf_gen.py`, and handle exempt-IVA logic in `calcular_totales`.
