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

# Certification workflow (see "SII certification" below):
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

**`api/routes/` — FastAPI routers**, one per domain (`apikeys`, `auth`, `caf`, `certificado`, `consulta`, `db`, `dte`, `keystore`, `monitoreo`, `onboarding`, `status` — 11 total), all mounted under `/api/v1` in `main.py`. `certificado`, `caf`, `dte` y `status` están protegidos a nivel de router (`dependencies=[Depends(requerir_autenticacion)]` en `main.py`); `requerir_autenticacion` (`core/auth.py`) acepta **JWT o API key** (`core/apikeys.py`, UI en `/apikeys`).

**`core/config.py`** — single `settings` singleton (pydantic-settings, reads `.env`). Import it, don't read env vars directly.

## Conventions & gotchas

- **XML for the SII is `ISO-8859-1`, not UTF-8**, and sent without pretty-printing. The DB stores the signed XML decoded as ISO-8859-1.
- **`EPR` NO significa "aceptado"** — significa "Envío Procesado" (el *sobre* se procesó). El veredicto está en `ACEPTADOS`/`RECHAZADOS`. Este malentendido tuvo al proyecto creyendo que el pipeline funcionaba mientras el SII rechazaba todo.
- **La resolución del SII depende del ambiente**: usa `settings.resolucion`, nunca `sii_fecha_resolucion`/`sii_numero_resolucion` a pelo (son los de producción → `CRT-3-19` en certificación).
- `.p12`/`.pfx` certificates are processed **in memory only** — never persist them to disk or the DB. A local `firma.pfx` (path configurable via `DTE_CERT_PATH`) is used as a dev fallback.
- Certification is currently blocked (see `task.md`): the test cert is not yet registered as mandatario for the emisor RUT, so the real T61 CAF can't be issued. `task.md` tracks the live status of the certification effort — read it before working on certification.
- Generated artifacts live under `storage/` (`dtes/`, `pdfs/`, `cafs/`, and `dtes_cert/`/`pdfs_cert/` for certification runs); results summaries are `storage/resultados_*.json`.
- Adding a new DTE type: extend `TipoDTE` in `core/dte.py`, add to `NOMBRES_DTE` in `core/pdf_gen.py`, and handle exempt-IVA logic in `calcular_totales`.
