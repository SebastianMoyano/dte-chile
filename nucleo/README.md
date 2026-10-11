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
| `emision` | el orquestador: folio → TED → XML → firma → sobre → [XSD por gancho] → disco → BD (sin PDF) |
| `valores` | UF, UTM y dólar desde las páginas oficiales del SII (fallback mindicador.cl), caché en la tabla `valores` del SQLite; `get` (fecha exacta), `vigente` (último valor hábil) y `demonio` (refresco diario in-process) |
| `sii` | cliente SOAP del SII: semilla, token (firma byte a byte igual a Python), DTEUpload, estado por TrackID |
| `servidor` | el motor HTTP (fase 7): mismo contrato que FastAPI en `/api/v1`, auth (JWT/APP_SHELL_KEY/API key), envoltorio de errores y request-id, `/app` (la interfaz), y reenvío a Python de lo no portado. Portado: `/`, `/api/v1/valores*`, `/api/v1/auth/*`, `/api/v1/apikeys`, keystore local (certificados cifrados con Fernet, claves del SII, negocios, contexto-emision), `mipyme/contexto-siiengine`, la práctica (`/api/v1/simulacion/*`, emite con `nucleo/emision`; XSD y PDF los pide a Python mientras no estén en Go) y los documentos (`/api/v1/dte/documentos*`, `/dte/emisor`); sha256_crypt (passlib) y Fernet compatibles con Python. Contrato dorado: `tools/contrato_api.py` |
| `almacen/migraciones` | el esquema completo en SQL numerado (`0001_base.sql`), aplicado al abrir (`AbrirYMigrar`); idéntico al de Python (`tools/esquema_dorado.py`) |
| `siiengine` | el **SII engine** (la app operando el portal MIPYME del SII, `core/sii_mipyme.py` entero): sesión por clave tributaria, empresa, cierre real, historial, PDF, XML por firma central, importación a `dtes`, y la emisión: factura exenta (validar → GenXMLFirma → firma central → SendXML), NC de anulación y NC de corrección de montos, con evidencia y gate `CadenasVerificadas` (fase 6 de `docs/PLAN-PORT.md`) |

**Contra el SII**: el 2026-10-05 un T34 de certificación emitido por `nucleo-emitir` fue
aceptado (ACEPTADOS=1, TrackID 261542052; script `fase3_envio.py`), y `nucleo-sii` obtuvo
token y leyó ese estado desde Go. Binarios: `nucleo-dorado`, `nucleo-emitir`, `nucleo-sii`,
`nucleo-valores` (UF/UTM/dólar del SII; `actualizar`/`get`/`vigente`/`demonio`). `nucleo-siiengine sesion|listar|importar|factura|nc-anular|nc-corregir`
opera el portal MIPYME en producción; `nucleo-servidor servir|migrar` es el motor HTTP en Go (reenvía a Python lo no portado) (claves por `NUCLEO_CLAVE_TRIBUTARIA`/`_CERTIFICADO` o el
Llavero, nunca por argumento). Lectura verificada en vivo y emisión en seco el 2026-10-08: cuerpos
byte a byte iguales a Python y a las emisiones aceptadas (`go test ./siiengine/`, paridad con
`tools/paridad_siiengine.py`); `--emitir` exige `--acepto-riesgo-folio` hasta la primera corrida real.

Regla (L15): si un byte difiere del corpus, el error está aquí o en Python, y se averigua cuál
contra el SII antes de tocar lo esperado. Plan y fases en `docs/PLAN-PORT.md`.
