# nucleo — el núcleo de firma del motor, en Go

Port de la capa pura de `core/` (totales → TED → XML del DTE → firma XMLDSig → sobre),
medido contra el corpus dorado del motor Python (`docs/DORADO.md`): misma entrada, mismos
bytes. Sin red, sin base de datos.

```bash
go build -o bin/nucleo-dorado ./cmd/nucleo-dorado && go build -o bin/nucleo-emitir ./cmd/nucleo-emitir
cd .. && .venv/bin/python test_dorado.py --port nucleo/bin/nucleo-dorado    # 15/15 idénticos (fase 1)
.venv/bin/python test_fase2.py                                               # Go y Python sobre la misma base (fase 2)
```

`nucleo-emitir` lee un documento JSON por stdin y emite contra `--db`/`--storage` con
`--cert` (clave en `NUCLEO_CERT_CLAVE`) y la resolución del emisor (`--resolucion-fecha/-numero`).
Escribe las mismas rutas (`storage/dtes/DTE_<t>_<f>.xml`, `EnvioDTE_…`, `BOLETA_…`) y la misma
fila que Python.

| paquete | qué replica |
|---|---|
| `totales` | `core/dte.py::calcular_totales` (half-up sobre la repr decimal, boleta con precio bruto) |
| `ted` | `core/caf.py::generar_ted` (DD aplanado, RSA-SHA1 en ISO-8859-1, CAF incrustado) |
| `xmlgen` | `GeneradorDTE.generar_documento_xml` y `generar_documento_boleta`, serializados como lxml |
| `c14n` | Canonical XML 1.0 inclusiva con el ápice "reparseado" (`core/crypto.py::_c14n_reparse`) |
| `firma` | PKCS#12, `firmar_xml_sii`, `firmar_documento_standalone`, `armar_sobre_firmado` |
| `almacen` | la misma base SQLite del motor: CAF activo, folio atómico (`BEGIN IMMEDIATE`), fila en `dtes` |
| `emision` | el orquestador: folio → TED → XML → firma → sobre → disco → BD (sin PDF, sin envío) |

**Contra el SII**: el 2026-10-05 un T34 de certificación emitido por `nucleo-emitir` fue
aceptado (ACEPTADOS=1, TrackID 261542052). Script: `fase3_envio.py`.

Regla (L15): si un byte difiere del corpus, el error está aquí o en Python, y se averigua cuál
contra el SII antes de tocar lo esperado. Plan y fases en `docs/PLAN-PORT.md`.
