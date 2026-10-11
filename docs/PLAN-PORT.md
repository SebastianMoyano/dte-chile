# Plan: portar el núcleo del motor a un lenguaje compilado

> Estado: **plan aprobado para empezar, sin código del port todavía.** Fecha: 2026-10-04.
> Herramienta de medición: `test_dorado.py --port` ([`DORADO.md`](DORADO.md)).

## Por qué (y por qué no)

Lo que se busca con el port no es velocidad ni "seguridad de memoria": es **un solo binario
que se instala y funciona** sin Python ni `.venv`, y un núcleo de firma que se pueda auditar
en pocas líneas. Lo que NO se busca es reescribir el motor entero: la parte que cambia
seguido (portal MIPYME, RCV, F29, captura) se queda en Python, donde iterar es barato.

El motor Python sigue siendo la **implementación de referencia**: está verificada contra el
SII (TrackID 253113966 aceptado, T34 de certificación aceptados). Un port no se juzga por
parecer correcto sino por producir **los mismos bytes** (L15). Por eso el plan no toca al SII
hasta la fase 3.

## Lenguaje: Go, salvo que se decida Rust a propósito

Recomendación: **Go**. Razones: el cascarón de la app ya es Go (`app/`), así el producto
final es un binario de un solo lenguaje; la biblioteca estándar trae RSA, SHA-1, PKCS#12 y
X.509; el equipo que mantiene esto es pequeño y Go se lee rápido. Rust daría lo mismo en
corrección y un binario igual de autónomo, pero suma un lenguaje más al repo y una curva
más larga; se justifica solo si quien lo va a mantener lo domina. **El plan es idéntico en
ambos casos**: el contrato son archivos, no una API de lenguaje.

## Principios

1. **El corpus manda.** Cada paso se da por hecho cuando `test_dorado.py --port` dice
   "bytes idénticos" en todos los casos. No antes.
2. **Por partes, de adentro hacia afuera**: primero lo puro (totales → TED → XML del DTE →
   firma → sobre), después lo que tiene estado (CAF en BD, folio atómico), al final lo que
   habla con el SII.
3. **Mismo contrato HTTP.** La API (`/api/v1/...`) y la app no cambian. El port entra por
   detrás, reemplazando funciones, no por delante cambiando interfaces.
4. **Nada real hasta la fase 3**, y en la fase 3 solo el ambiente de certificación.

## Fases

### Fase 0 — Preparar la vara (Python, 1-2 días)

- [x] Reloj único (`core/reloj.py`) y corpus dorado con 5 casos.
- [x] Runner para ports externos (`--port`) y port de ejemplo que lo valida.
- [x] Corpus de 15 casos: ND (56), guía (52), descuentos por línea, cantidad decimal,
      afecto + exento, crédito con vencimiento y tildes, NC parcial, boleta mixta con
      `IndServicio`, sobre con 3 DTE, sobre con 2 boletas, receptor mínimo. Los 15 validan XSD.
- [x] Corpus privado: `tests/dorado/privado.py` (datos en `storage/dorado_privado/`, fuera de git).
- [x] Especificación de bytes en `DORADO.md` (totales, TED, DTE firmado, sobre) y modo
      `--parcial` del harness para medir un port a medio camino.

### Fase 1 — Núcleo puro en Go (`nucleo/`, 1-2 semanas)

> Estado 2026-10-04: **fase 1 cerrada en local.** `nucleo/bin/nucleo-dorado` produce TED, DTE
> firmado y sobre **idénticos byte a byte en los 15 casos** (`test_dorado.py --port nucleo/bin/nucleo-dorado`).
> Pendiente de la fase: el corpus privado de aceptados reales (1.6, el XSD en Go, se cerró en la fase 7 paso 5).

Un módulo Go sin red ni BD, con un ejecutable `nucleo-dorado` que cumple el contrato del
runner (`<entrada.json> <fixtures/> <salida/>`). Orden, y cada paso se cierra con el corpus:

| paso | qué | compara contra | trampa conocida |
|---|---|---|---|
| 1.1 ✅ | `calcular_totales` (redondeo half-up CLP, boleta con IVA incluido, exentos) → `nucleo/totales` | `totales.json` | boleta: precio bruto, neto derivado |
| 1.2 ✅ | parseo del CAF y **TED**: `<DD>` aplanado, firma RSA-SHA1 con la clave del CAF, `<CAF>` incrustado tal cual → `nucleo/ted` | `ted.xml` | los saltos de línea del TED son parte de lo firmado |
| 1.3 ✅ | generación del `<DTE>` sin firma: orden de tags según XSD, ISO-8859-1, `Id="T{tipo}F{folio}"` | diff estructural (sin `<Signature>`) | orden de elementos; "é" en ISO-8859-1 |
| 1.4 ✅ | **C14N** (xml-c14n 2001) + XMLDSig RSA-SHA1 del `<Documento>` standalone | `dte.xml` | C14N exactamente como lxml: namespaces, atributos ordenados, sin xsi del sobre |
| 1.5 ✅ | **sobre** por concatenación de strings con el DTE verbatim, firma del `SetDTE` | `envio.xml` | nunca re-serializar el DTE firmado (L1, DTE-3-505) |
| 1.6 ✅ | validación XSD: el núcleo expone el gancho `Contexto.Validar` **antes de persistir**; primero se conectó a `POST /dte/validar-xml` del motor Python y desde la fase 7 paso 5 lo atiende `nucleo/xsd` (validador propio del subconjunto de XSD que usa el SII, paridad con lxml por 1.070 vectores) | `TestParidadConLxml` | el folio ya está consumido al validar (igual que en Python) |

Criterio de salida: `test_dorado.py --port ./nucleo/bin/nucleo-dorado` → todos idénticos
(**cumplido para los 15 casos públicos el 2026-10-04**), incluido el corpus privado de
aceptados (pendiente).

Lo que el corpus atrapó durante el port, en orden: nada en totales ni TED (salieron a la
primera); en el sobre, el `xmlns:xsi` redeclarado en la `<Signature>` (54 bytes). Lo demás
(C14N con ápice reparseado, escapes, ISO-8859-1, KeyInfo envuelto a 64) coincidió al primer
intento porque estaba escrito en la especificación de bytes antes de programar.

### Fase 2 — Estado: CAF, folios y persistencia (1 semana) ✅

> Estado 2026-10-04: **cerrada.** `nucleo/almacen` (SQLite, `BEGIN IMMEDIATE`) y
> `nucleo/emision` (orquestador) con `nucleo/bin/nucleo-emitir`. `test_fase2.py` (21
> comprobaciones): Go → Python → Go → Python dan folios 1-4 sin repetir; lo que Go deja en
> disco y en `dtes.xml_firmado` es byte a byte lo del pipeline Python con ese folio; 3
> procesos Go + 3 hilos Python emitiendo a la vez → 94 boletas, sin duplicados ni huecos;
> los sobres de Go validan XSD. (Entonces Go no generaba PDF ni enviaba; hoy sí: fase 5 `nucleo/sii`, fase 7 `nucleo/pdf`.)

- Lectura de CAF desde la BD SQLite existente (mismo esquema, mismo archivo).
- Folio atómico con `BEGIN IMMEDIATE` (reproducir exactamente `consumir_siguiente_folio`).
- Guardar DTE/PDF/sobre con las mismas rutas y filas que hoy, para que la API Python y la app
  sigan viendo lo mismo.
- Prueba: emitir con el port y con Python alternadamente sobre la misma BD de prueba; los
  folios no se repiten ni se saltan. (`test_fase2.py`, hecho.)

### Fase 3 — Contra el SII de certificación (1 semana, con folios de Maullín)

> Estado 2026-10-05, parte A (local, privada) **cerrada**: `tests/dorado/privado.py` reconstruye
> la entrada de cada sobre real de `storage/dtes/`, y Python puro y Go reproducen byte a byte,
> con el certificado real (clave desde el Llavero) y el CAF real (elegido por el módulo de la
> clave que lleva el TED): la factura exenta **34/111 aceptada por el SII (TrackID 253113966)**
> y la boleta 39/1 de producción. Los sobres de julio anteriores a `core/sobre.py` se omiten.
> Hallazgo del port: **los CAF del SII traen claves RSA de 512 bits** y Go ≥ 1.24 las rechaza;
> los binarios llevan `//go:debug rsa1024min=0`.
>
> Parte B (envío) **iniciada y con el primer aceptado**: el 2026-10-05 `fase3_envio.py` emitió
> con `nucleo-emitir` una factura exenta (T34) de certificación, Python verificó en local que
> la reproducía byte a byte, la envió con `core/sii.py` y el SII respondió **EPR con
> ACEPTADOS=1 (TrackID 261542052)**. Falta el set de pruebas completo, que depende de folios
> T33/T61 de certificación (bloqueo conocido, ver memoria).

- El port emite el **set de pruebas** completo (`dry_run_certificacion.py` como guía) y se
  envía con el cliente SOAP Python existente (el envío no se porta todavía).
- Resultado esperado: `ACEPTADOS` iguales a los que logra Python con las mismas entradas.
  Cualquier `RECHAZADO` o `DTE-3-505` detiene la fase: se vuelve a la fase 1 con ese caso
  agregado al corpus.

### Fase 4 — Integración en el producto (1 semana)

> Estado 2026-10-05: **la app emite con el núcleo Go** (`app.go::EmitirNucleo`, ver
> `docs/APP.md`): certificado en PEM desde el keystore por `contexto-emision`, emisión con
> `nucleo/emision`, PDF por Python (`POST /dte/documentos/{id}/pdf` + `core/dte_xml.py`).
> CI: `.github/workflows/dorado.yml` corre el corpus contra Python y contra Go en cada push.
> Firma macOS: `app/firmar-mac.sh`. **Instalador sin repo: hecho** (`app/empaquetar-mac.sh`:
> motor congelado con PyInstaller dentro del bundle, datos en la carpeta del usuario, `.env`
> con secretos generados la primera vez). Pendiente: Windows/Linux, DMG.

- El cascarón Go (`app/`) llama al núcleo directo para generar/firmar; Python queda como
  servicio para MIPYME, RCV, F29, portal y envío SOAP.
- Instalador: un binario Go + un Python embebido solo para esos servicios (o PyInstaller del
  motor) hasta que se decida si el envío SOAP también se porta. (Hecho con PyInstaller.)
- Corpus dorado corriendo en CI contra Python y contra el port, en cada commit. (Hecho.)

### Fase 5 — Decidir qué más (abierto)

> Estado 2026-10-05: **cliente SII en Go hecho** (`nucleo/sii`): semilla, firma de la semilla
> (byte a byte igual a Python, `tests/dorado/sii/`), token, envío por DTEUpload y estado por
> TrackID con lectura de Aceptados/Rechazados/Reparos; reintentos ante 5xx. Probado en vivo
> contra Maullín: token obtenido y el TrackID 261542052 leído como EPR, aceptados 1.
> `nucleo/bin/nucleo-sii token|estado|enviar`. También `nucleo/valores` (UF/UTM/dólar oficiales,
> caché compartida, refresco diario dentro de la app). Con esto el núcleo puede emitir Y enviar sin
> Python; falta decidir si la app lo usa para enviar (hoy envía Python). PDF/PDF417 y
> EnvioBOLETA (REST de boletas) siguen pendientes.

Con fases 1-4 hechas, se mira el valor de portar: envío SOAP y semilla/token (sencillo),
PDF con PDF417 (hay librerías en Go), boletas EnvioBOLETA + RVD. El portal MIPYME (SII engine)
se porta en la fase 6 con la captura del navegador como vara: es scraping vivo, pero con
evidencia byte a byte deja de ser adivinanza.

### Fase 6 — El SII engine en Go, por segmentos (abierta, 2026-10-08)

> **Vocabulario.** El producto tiene un motor base y una expansión. **SII engine**: la app
> opera los sistemas del propio SII por la empresa (facturas por el portal MIPYME, boletas por
> eboleta); el SII pone folio, timbre y firma; sirve para quien no quiere cambiar nada. **Motor
> propio**: software certificado, con CAF, timbre y firma nuestros; es la expansión, por familia
> de documento (el SII exige exclusividad por familia: una empresa puede tener facturas en el SII
> engine y boletas en el motor propio, como Moyoli Tech). Las dos vías son gratis para quien
> las usa; "gratuito" es solo el nombre que el SII le pone a su sistema. Mismo almacén, misma
> pantalla: un documento es un documento venga de donde venga (`dtes.estado = emitido_mipyme`
> marca el canal). El punto de entrada de emisión rutea por empresa y familia según lo que el
> SII tiene autorizado (diagnóstico del onboarding), y migrar de una vía a la otra no pierde
> historial.

El SII engine es una unidad cerrada (sesión, formularios, envío, PDF y XML, registro en la BD)
que no toca firma ni CAF: se porta aparte, en `nucleo/siiengine`, con el mismo almacén SQLite
que el motor propio. La vara es la misma de las fases 1-3: **mismo HTML de entrada, mismo cuerpo
byte a byte** que `core/sii_mipyme.py`, verificado contra las evidencias reales (captura de la
factura 62; cuerpos de la factura 63 y la NC 60, `storage/mipyme_fallidos/…/T34_F63_*` y
`T61_F60_*`). Ningún folio se gasta para verificar; una sola corrida real por segmento cuando
el cuerpo ya es idéntico. Python queda como referencia hasta que cada segmento pase en real, y
después como historia (no se mantienen los dos).

| segmento | qué | verificación | estado |
|---|---|---|---|
| 1 | sesión (login, empresa, cierre real) y lectura: historial, PDF, XML por firma central, form pre-llenado; importar al almacén | solo lectura en vivo, sin riesgo | **hecho 2026-10-08**: `nucleo-siiengine sesion|listar|importar`; en vivo: sesión y cierre real, 51 documentos listados (los mismos que la BD), PDF y XML por firma central idénticos a los de Python salvo lo que el SII regenera (fecha de creación del PDF, firma del sobre al descargar; el `<DTE>` es byte a byte igual) |
| 2 | factura exenta: validar (DisplayPreView), vista previa, GenXMLFirma, firma central, SendXML | cuerpos idénticos a los de la factura 63 | **hecho en seco 2026-10-08**: los 3 cuerpos (validar 54, GenXMLFirma 243, SendXML 250) byte a byte iguales a Python y a la evidencia aceptada de la factura 63; falta UNA corrida real desde Go para entrar a `CadenasVerificadas` |
| 3 | NC de anulación | cuerpos idénticos a los de la NC 60 | **hecho en seco 2026-10-08**: GenXMLFirma (243) idéntico a Python sobre la misma página; SendXML idéntico a la evidencia de la NC 60; guardarraíl del total por XML (firma central) en vez de PDF; falta una corrida real desde Go |
| 4 | NC de corrección de montos y nota de débito | captura de la NC 59 / ND 1; sin corrida real todavía en Python tampoco | **hecho en seco 2026-10-08**: validar (60) y GenXMLFirma (244) idénticos a Python; sin corrida real (tampoco en Python). La nota de débito no existe en Python: nada que portar |
| 5 | eboleta (boletas por el SII) | exige una captura real de una boleta emitida en eboleta.sii.cl | pendiente, sin captura |
| app | el cascarón usa `nucleo/siiengine` en vez del motor Python | "Traer lo emitido" → `App.SIIEngineSincronizar` (claves recordadas por `mipyme/contexto-siiengine`) | **hecho 2026-10-08** para sincronizar; **2026-10-09**: Cobrar y Corregir (NC de anulación desde el portal) validan en el SII por Go (dry-run, probado en vivo) y emiten solo cuando `CadenasVerificadas` tenga el tipo |

**Cómo se verifica sin gastar folios** (`tools/paridad_siiengine.py` + `nucleo-siiengine … --trazas`):
Python y Go corren el mismo dry-run contra el portal y se comparan los cuerpos que cada uno
mandaría (validar y GenXMLFirma) y las páginas que recibieron; además `TestParidadEvidencia`
reconstruye el cuerpo de `mipeSendXML` desde la página de firma y la respuesta de postFirma de
las emisiones aceptadas (`storage/mipyme_fallidos/*/T34_F63_*`, `T61_F60_*`) y exige igualdad
byte a byte con lo que viajó; `TestParidadTrazas` hace lo mismo con las trazas privadas
(`storage/siiengine_paridad/`). Resultado 2026-10-08: todo idéntico en los tres flujos.
`CadenasVerificadas` de Go sigue vacía hasta la primera corrida real desde Go (la lanza el
usuario: una factura de $1.000 entre empresas propias y su NC de anulación).

Reglas que el Go repite del Python: claves solo del Llavero, del keystore de la app o de la
consola (nunca por argumento ni `.env`); una sola sesión por corrida y cierre siguiendo el 302
(tope ~10 por RUT); sin reintentos en los pasos que gastan folio; el guardarraíl del total de
la NC se toma del XML del envío (firma central), no del PDF, para no depender de una librería
de PDF en Go.

### Fase 7 — Dejar de usar Python: el motor entero en Go (abierta, 2026-10-09)

Meta: la app y el navegador funcionan con un solo binario Go; Python queda para herramientas
(MCP, correos, captura, certificación ocasional). La base sigue en **SQLite**: es lo correcto
para una app de escritorio y para un servidor de sala de clases; Postgres solo si un día hace
falta un servidor grande (la capa `database/sql` lo deja abierto). Lo que sí cambia es la
**propiedad del esquema**: pasa de `core/database.py::SCHEMA_SQL` a migraciones numeradas en Go.

**Método (patrón estrangulador):** un servidor Go atiende `/api/v1` y reenvía a Python lo que
aún no está portado; la app y el navegador no cambian. Cada endpoint se porta con un *contrato
dorado*: misma petición → misma respuesta JSON, comparado contra Python antes de apagarlo
(como `test_dorado.py --port` para los bytes y `tools/paridad_siiengine.py` para el portal).
Cuando el último endpoint pasa, se quita el sidecar (PyInstaller) y queda un binario.

| orden | bloque | hoy en Python | dificultad | cómo se verifica |
|---|---|---|---|---|
| 0 | corrida real del SII engine desde Go (cierra la fase 6) | — | la lanza el usuario | factura + NC reales, `CadenasVerificadas` |
| 1 | esquema con migraciones + servidor Go con reenvío | `core/database.py`, `main.py` | baja | **hecho 2026-10-09**: `nucleo/almacen/migraciones` (0001_base + columnas garantizadas, tabla `migraciones`), `tools/esquema_dorado.py` → 23 objetos idénticos a Python; `nucleo-servidor servir` atiende `/`, `/api/v1/valores*` y `/app`, reenvía el resto a Python; `tools/contrato_api.py` → 19 rutas idénticas (JSON, status, códigos de error, 401) |
| 2 | auth, usuarios, API keys, keystore (Fernet compatible) | `core/auth.py`, `core/apikeys.py`, `core/keystore.py` | baja | **hecho 2026-10-10**: `servidor/{usuarios,apikeys,keystore,fernet}.go`; sha256_crypt de passlib (535000 rondas) y Fernet implementados en Go con vectores cruzados; contrato dorado con escenarios `auth`, `apikeys`, `keystore`, `contexto`: todo idéntico, incluidos los cruces (cada motor verifica hashes y descifra blobs del otro) y el PEM del certificado real byte a byte. Quedan en Python (reenviadas) las rutas del keystore que consultan el portal del SII: alta de negocio, `/empresa`, timbraje, estado, f29, empresas del certificado. La resolución del emisor en Go sale del caché o del default (sin consulta al portal hasta portar `sii_portal`) |
| 3 | práctica (empresa demo) y listados/consulta de documentos | `core/simulacion.py`, `api/routes/dte.py`, `consulta.py` | baja | **hecho 2026-10-11** (`servidor/{simulacion,demo,documentos}.go`): la práctica emite con `nucleo/emision` (CAF demo y certificado demo generados en Go), anula, lista, reinicia; documentos: listado, emisores, PDF, XML, emisor. Contrato `simulacion`: 20 pasos idénticos. XSD y PDF quedaron en Python hasta los pasos 4 y 5 (hoy en Go); `consulta.py` (buscador público) y `POST /dte/emitir` del motor propio siguen reenviados |
| 4 | PDF + PDF417 | `core/pdf_gen.py`, `core/dte_xml.py` | media | **hecho 2026-10-11**: `nucleo/pdf` (carta y boleta 80 mm con go-pdf/fpdf, reconstrucción desde el XML firmado) y `nucleo/pdf417` (port fiel de pdf417gen: tablas generadas desde Python con `tools/generar_pdf417.py`, 48 vectores idénticos fila por fila (datos ficticios); el PNG del timbre es píxel a píxel el de Python; en el PDF va como vectores para que se lea a cualquier resolución, verificado con pdf417decoder). `POST /dte/documentos/{id}/pdf` en Go; la práctica y la app (`EmitirNucleo`) dibujan con el núcleo. Lección: la librería Go de PDF417 que se probó primero daba códigos ilegibles; por eso el port con vectores |
| 5 | validación XSD | `core/schema_validator.py` (lxml) | **alta** (no hay XSD puro en Go) | **hecho 2026-10-11**: se midió el subconjunto de XSD que usan los 6 esquemas del SII (sequence, choice, simpleContent/extension, atributos fijos, 9 facetas, 1 patrón, ~19 tipos primitivos) y se escribió `nucleo/xsd`, un intérprete de ESE subconjunto (cualquier constructo fuera de él hace fallar la carga, nunca pasa en silencio), sin cgo. Vara: `tools/generar_xsd_vectores.py` muta el corpus dorado + un ConsumoFolios firmado (1.070 vectores: estructura, atributos, valores, codificaciones, mal formados) y guarda el veredicto de lxml; `TestParidadConLxml` exige mismo veredicto, mismo `tipo_xml` y mismo elemento del primer error: 1.070/1.070. Rarezas de libxml2 reproducidas a propósito: base64Binary IGNORA los caracteres que no son base64 (cuenta solo los válidos), `date`/`dateTime` no toleran blancos alrededor pero los numéricos sí, `anyURI`/`ID` colapsan blancos, `xs:ID` sí exige unicidad, `anySimpleType` compara el valor fijo tal cual. `POST /dte/validar-xml` en Go (contrato `xsd` 8/8), y la práctica y la app validan con `nucleo/xsd` (ya no llaman a Python para esto) |
| 6 | emisión del motor propio por API + boletas: EnvioBOLETA REST, RVD, programador | `api/routes/dte.py` (emitir, previsualizar, enviar), `status.py`, `core/sii_boleta.py`, `rvd.py`, `scheduler.py` | media | **hecho 2026-10-11** (sin corrida real contra el SII todavía): `POST /dte/emitir` (certificado de la petición → `.env` → `firma.pfx`; errores de dominio con los códigos de `core/errors.py` vía `emision.Error`), `/dte/previsualizar` (certificado del keystore, CAF activo, sin consumir folio), `/dte/enviar` (XSD → DTEUpload; 422 `sii_rechazo` cuando el SII respondió mal = `ValueError` de Python, 502 si no respondió; se copió hasta la rareza de Python de responder 502 a una boleta por este camino), `/estado/track`, `/estado/dte`. Contrato `emitir`: 28 pasos idénticos (incluidos los que pegan al SII con el certificado ficticio). `nucleo/sii/boleta.go` = `ClienteBoletaSII` (hosts asimétricos apicert/pangal, token propio, multipart, JSON) con la semilla firmada byte a byte igual a Python (`tests/dorado/sii/semilla_firmada_boleta.xml`); rutas solo-Go `POST /boletas/enviar` y `/boletas/estado` (Python nunca las expuso). `nucleo/rvd` = `core/rvd.py` byte a byte (`tests/dorado/rvd/`: ConsumoFolios sin firmar y firmado con hora fija) + `servidor/rvd.go` (programador en goroutine, catch-up de 7 días, `GET /rvd/estado`, `POST /rvd/procesar`, `GET /rvd/registros/{rut}`); el programador Go solo corre cuando el Go está solo (sin `--motor`), para no reportar dos veces desde la misma base. Falta la vara real: una boleta de Moyoli Tech aceptada por el REST desde Go y un RVD aceptado |
| 7 | RCV, F29, onboarding, portal del SII (timbraje, postulación) | `core/rcv.py`, `onboarding.py`, `sii_portal.py`, `postulacion.py` | media | captura del navegador como vara, igual que el SII engine. **Paso 6b hecho 2026-10-11**: `db/*` (7), `caf/*`, `certificado/*`, `dte/generar`, `generar-simple`, `pdf`, `pdf-simple`, `estado/lote`, `monitoreo/folios[/cartera]` y `mipyme/diagnostico|importar|sincronizar` (con `nucleo/siiengine`) en Go; contrato `rutas` 49 pasos idénticos (incluido el TED de marcador de posición de `GeneradorDTE` cuando no hay CAF, copiado tal cual). De paso se arregló `POST /mipyme/diagnostico` en Python (usaba `usuario` sin recibirlo → 500). **Paso 7a hecho 2026-10-11**: `nucleo/portal` = `core/sii_portal.py` (auth por certificado mutual-TLS o por clave, timbrajes, empresa autorizada (pública), software registrado, empresas asociadas, anulables, anular, situación de folios, solicitar/generar/descargar CAF con los guardarraíles anti-acaparamiento) + `core/onboarding.py` (clasificar, diagnosticar, cartera) + `core/negocios.py` (alta con auto-relleno, estado cacheado). Gate: `tests/dorado/portal/` (HTML sintético por cada página + la página pública REAL del RUT de prueba del SII + dobles del portal para 6 diagnósticos) → `TestParidadConPython` 16/16 bloques. Rutas en Go: `keystore/empresa`, `certificados/{id}/empresas`, `keystore/negocios` (POST), `negocios/{id}/estado|timbraje`, `onboarding/diagnostico|cartera`; contrato `portal` 16/16 (incluye la consulta pública real). GOTCHA: el portal responde ISO-8859-1 → decodificar por charset antes de las regex (`N°`). **Paso 7b hecho 2026-10-11**: `nucleo/rcv` = `core/rcv.py` (facade RCV: payload y cabeceras calcados del navegador, normalización del CSV del Export y de los dicts, upsert en `rcv_documentos`, resumen y desglose del F29, casilleros oficiales); gate `tests/dorado/rcv/` (datos ficticios) 19/19 bloques; `GET negocios/{id}/f29` en Go. **Con esto las 69 rutas de la API Python están en Go** (más 7 solo-Go: `/boletas/*`, `/rvd/*`); contrato dorado completo idéntico. Lo que sigue en Python: `consulta.py` (buscador público HTML), el MCP y las herramientas del operador |
| 8 | certificación (set, declaración) | scripts | baja prioridad | se usa pocas veces; al final |
| 9 | quitar el sidecar Python de la app: `app/` usa `nucleo/servidor` en proceso | `app/motor.go`, `app/empaquetar-mac.sh` | media | **hecho 2026-10-11**: `Motor.iniciarGo` levanta el servidor Go en el mismo proceso (puerto libre, clave efímera; `App.API` sigue por HTTP así que la interfaz y el puente no cambian); `asegurarAdmin` en el servidor (lo que hacía `main.py`); `/app` desde el FS embebido de Wails; `DTE_MOTOR=python` conserva el sidecar para comparar; `empaquetar-mac.sh` sin PyInstaller (opcional con `DTE_MOTOR_PYTHON_BUNDLE=1`). Gate: `app/motor_test.go` (carpeta de datos vacía → .env, base, admin, 401 sin clave, /app/, boleta de práctica con PDF, todo sin Python) |
| 10 | lo que `main.py` servía fuera de la API: buscador público `/consulta` (HTML, `/api`, `/xml`, `/pdf`, POST), páginas del panel (`/certificados`, `/onboarding`, `/apikeys`, `/documentos`, `/static/*`, `/favicon.ico`) y el acotamiento por `DOMINIO_PUBLICO_BOLETAS` | `api/routes/consulta.py`, `main.py` | baja | **hecho 2026-10-11**: `servidor/consulta.go` (misma página autocontenida, mismo candado de 5 datos, PDF guardado o regenerado desde el XML con el TED verbatim) y `servidor/static/` (copias de `static/*.html` con `TestStaticIgual`). Contrato `consulta` 19/19 (HTML byte a byte del mismo tamaño; el PDF regenerado difiere porque es `nucleo/pdf`, no ReportLab). **Con esto el motor Go cubre todo lo que servía `main.py`**; en Python quedan el MCP, los scripts de certificación y las herramientas del operador |

No se porta: `mcp_server.py`, la skill de correos y `tools/captura-sii` (herramientas del operador).

**Cómo se porta una ruta** (desde el paso 1): se escribe en `nucleo/servidor` con el mismo JSON y
los mismos códigos (envoltorio `{"error": {codigo, mensaje, detalle?, request_id}}`, 422
`validacion`, 404 `no_encontrado`, 401 `autenticacion`), se agrega a `tools/contrato_api.py`, se
corren los dos motores con el mismo `APP_SHELL_KEY` y se exige "idéntico" antes de quitarla de
Python. Auth en Go (`servidor/auth.go`): JWT HS256 con `JWT_SECRET_KEY`, `APP_SHELL_KEY` como el
usuario dueño, API keys `dte_…` por sha256; los mismos tokens sirven en los dos motores.

### Fase 8 — Transcripción final a Rust (decidida como meta, 2026-10-11)

Criterio de quien opera el proyecto: el código es para la IA, no para el humano; lo que importa
son los docs y los gates; y "lo mejor que se puede hacer" vale aunque no sea estrictamente
necesario. Con eso, la forma final del producto es **Rust**, y **Go es la fase de iteración
rápida**: se porta todo a Go primero (fase 7), porque es el camino más corto para tener el
motor entero bajo gates, y después se transcribe a Rust módulo por módulo contra esos mismos
gates (corpus dorado, contrato dorado, esquema dorado, paridad de cuerpos son "bytes de entrada
→ bytes de salida" y no saben en qué lenguaje está el que los pasa).

Orden de transcripción, por valor de la rigidez de Rust: 1) el núcleo puro (totales, TED,
xmlgen, c14n, firma, sobre): determinista, verificado byte a byte, donde la corrección importa
más; 2) SII engine y cliente SII (HTTP, cuerpos exactos); 3) servidor HTTP (contrato dorado);
4) almacén y migraciones; 5) cascarón de escritorio (Tauri en vez de Wails).

Reglas desde hoy para que la transcripción sea barata: módulos puros y chicos con la frontera
en bytes; biblioteca estándar, sin frameworks ni generadores de código; cada bloque nace con su
gate automático. Y cadena de suministro vigilada en los dos lenguajes: pocas dependencias,
versiones fijadas con sumas (go.sum / Cargo.lock), escáner de vulnerabilidades en CI
(`govulncheck` / `cargo audit`), y revisión de cada dependencia nueva. Dato (2026-10-11): el
núcleo Go tiene 3 dependencias directas y ~13 con las indirectas; el motor Python, 66 paquetes;
un servidor Rust equivalente (tokio, axum, reqwest, rustls, serde, rusqlite, RustCrypto, …)
trae del orden de 100-150 crates transitivos: la biblioteca estándar de Rust es mínima a
propósito, la de Go trae HTTP, TLS, criptografía, JSON, XML y SQL.

## Riesgos y cómo se mitigan

- **C14N distinta** entre lxml y la librería del port. Es el riesgo mayor. Mitigación: la fase
  1.4 se hace con casos mínimos (un `<Documento>` de 3 tags) antes del corpus completo, y la
  especificación de bytes de la fase 0.
- **Codificación**: ISO-8859-1 en todo lo que ve el SII; UTF-8 solo en la API. Un port que
  escriba UTF-8 "porque es lo normal" falla en el byte de la primera tilde. El corpus tiene
  tildes a propósito.
- **Regenerar el corpus para que pase.** Prohibido por L15. Si el port "necesita" otro byte,
  el port está mal, o lo está Python y entonces se prueba contra el SII antes de cambiar.
- **Dos implementaciones divergiendo** con el tiempo. Mitigación: el corpus corre contra ambas
  en CI; la que falla se arregla, no se excluye.

## Qué NO es parte del plan

- Cambiar la API o la app por el port.
- Portar la extensión de captura o el F29 (el SII engine sí se porta: fase 6).
- Tocar producción con el port antes de que certifique en Maullín.
