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
| `emision` | el orquestador: folio → TED → XML → firma → sobre → XSD (gancho) → disco → BD; `Previsualizar` (sin folio ni disco) y errores de dominio tipados (`emision.Error`: mismos códigos y status que `core/errors.py`) |
| `valores` | UF, UTM y dólar desde las páginas oficiales del SII (fallback mindicador.cl), caché en la tabla `valores` del SQLite; `get` (fecha exacta), `vigente` (último valor hábil) y `demonio` (refresco diario in-process) |
| `sii` | cliente SOAP del SII: semilla, token (firma byte a byte igual a Python), DTEUpload, estado por TrackID y por documento; y `ClienteBoleta` (`boleta.go`): el REST de boletas (semilla/token en apicert/api, ENVÍO en pangal/rahue, estado por TrackID de 15 dígitos), semilla firmada idéntica a Python |
| `rvd` | `core/rvd.py`: el ConsumoFolios diario de boletas (resúmenes por tipo, rangos, firma `#RVD…`, XSD) byte a byte con `tests/dorado/rvd/`; envío por DTEUpload; tabla `rvd_envios` |
| `servidor` | el motor HTTP (fase 7): mismo contrato que FastAPI en `/api/v1`, auth (JWT/APP_SHELL_KEY/API key), envoltorio de errores y request-id, `/app` (la interfaz), y reenvío a Python de lo no portado. Portado: `/`, `/api/v1/valores*`, `/api/v1/auth/*`, `/api/v1/apikeys`, keystore local (certificados cifrados con Fernet, claves del SII, negocios, contexto-emision), `mipyme/contexto-siiengine`, la práctica (`/api/v1/simulacion/*`, emite con `nucleo/emision`, XSD con `nucleo/xsd`, PDF con `nucleo/pdf`), `POST /dte/validar-xml`, el motor propio (`POST /dte/emitir`, `/dte/previsualizar`, `/dte/enviar`, `/estado/track`, `/estado/dte`), boletas por REST (`/boletas/enviar`, `/boletas/estado`), el RVD (`/rvd/*` + programador en goroutine), los documentos (`/api/v1/dte/documentos*`, `/dte/emisor`), las tablas (`/db/*`), CAF y certificado (`/caf/*`, `/certificado/*`), `dte/generar[-simple]`, `dte/pdf[-simple]`, `estado/lote`, `monitoreo/*` y el portal MIPYME (`mipyme/diagnostico|importar|sincronizar` con `nucleo/siiengine`). Sin portar: 9 rutas del portal del SII con certificado (`sii_portal.py`); sha256_crypt (passlib) y Fernet compatibles con Python. Contrato dorado: `tools/contrato_api.py` |
| `almacen/migraciones` | el esquema completo en SQL numerado (`0001_base.sql`), aplicado al abrir (`AbrirYMigrar`); idéntico al de Python (`tools/esquema_dorado.py`) |
| `pdf417` | port fiel de pdf417gen (Python): mismas tablas (generadas con `tools/generar_pdf417.py`), mismas filas de códigos (48 vectores en el test); imagen 2×6 px con margen 20 como `render_image(scale=2, ratio=3)` |
| `pdf` | representación gráfica desde el XML firmado (`DesdeXML` = `core/dte_xml.py`): carta (`Carta`) y boleta 80 mm (`Boleta80mm`), timbre PDF417 nivel 5 y 12 columnas dibujado como vectores; CLI `nucleo-pdf` |
| `xsd` | validación contra los XSD oficiales del SII (copias embebidas de `core/xsd`, test de igualdad) sin libxml2: intérprete del subconjunto de XSD que esos esquemas usan; paridad con lxml por `testdata/vectores.json.gz` (1.070 vectores de `tools/generar_xsd_vectores.py`: mismo veredicto, tipo y elemento del primer error) |
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
