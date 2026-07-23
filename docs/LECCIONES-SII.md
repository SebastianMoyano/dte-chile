# Lecciones del SII (conocimiento caro)

> Cada sección aquí costó horas de trabajo o varios envíos al SII. **Léela antes de
> investigar un error**, no después. Complementa la [`CONSTITUCION.md`](CONSTITUCION.md),
> que tiene las reglas; esto tiene el **por qué** y la evidencia.
>
> Todo lo de aquí está **verificado contra el SII vivo**, con TrackID cuando aplica.

## Índice

| Si te topas con… | Ve a |
|---|---|
| `DTE-3-505 Firma DTE Incorrecta` | [Firma del DTE](#firma-del-dte-dte-3-505) |
| `CRT-3-19 Fecha/Numero Resolucion Invalido` | [Resolución por ambiente](#resolución-por-ambiente-crt-3-19) |
| `EPR` y no sabes si se aceptó | [EPR no es aceptado](#epr-no-es-aceptado) |
| `LOK` en un libro, o "¿ya certifiqué?" | [Estados que parecen aceptación](#los-estados-del-sii-que-parecen-aceptación-y-no-lo-son) |
| `401 NO ESTA AUTENTICADO` en boletas | [Mensajes engañosos](#mensajes-engañosos-del-sii) |
| `HED-3-861 Actividad Económica no registrada` | [Datos del emisor](#datos-reales-del-emisor) |
| `DTE-3-101`, `CAF-3-517` | [Folios y CAF](#folios-y-caf) |
| `SRH` en un libro, o reparos de datos | [El XSD no alcanza](#️-el-xsd-no-alcanza-las-reglas-de-negocio-viven-en-los-pdf-de-formato) |
| Vas a tocar la firma XMLDSig | [Perfil restringido](#el-sii-usa-un-perfil-restringido-de-xmldsig) |
| Vas a trabajar en boletas | [Boletas: infraestructura aparte](#boletas-infraestructura-aparte) |
| `El Documento no está en el envío` (cert boletas) | [El SET va por DTEUpload, no REST](#boletas-infraestructura-aparte) |
| ¿El RVD/RCOF es obligatorio? | [El RVD ya no es obligatorio](#boletas-infraestructura-aparte) |
| `Estado=10 Error Interno` al pedir token | [Mensajes engañosos](#mensajes-engañosos-del-sii) |
| `REF-3-750 DTE referenciado no recibido` | [Folios y CAF](#folios-y-caf) |

---

## Firma del DTE (`DTE-3-505`)

**Causa**: el SII verifica la firma del DTE **extrayéndolo como documento independiente**,
sin el `xmlns:xsi` que declara la raíz del sobre. Dos formas de romperlo:

1. **Firmar el DTE ya embebido** en el sobre → el `xmlns:xsi` entra al C14N del
   `<Documento>` → el SII recomputa otro digest → 505.
2. **Re-serializar después de firmar** (`etree.tostring` del sobre completo) → cambian los
   bytes → el digest deja de calzar.

**Solución** (`core/sobre.py`): firmar standalone + armar el sobre **por strings** con el
DTE **verbatim** + insertar la firma del `SetDTE` también por string. Nunca reformatear.

> Referencia externa: cryptosys.net/pki/xmldsig-ChileSII — *"no xmlns attributes in the
> individual DTE when signed"*, *"do not reformat after signing"*. Es lo mismo que hace
> LibreDTE (`EnvioDte.php` usa `str_replace`, no un append de árbol).

**Verificado**: TrackID `253113960` (manual) y `253113966` (orquestador) → `ACEPTADOS: 1`.

**Para VERIFICAR un TED** (no generarlo) hay que canonicalizar **igual que al generarlo**:
C14N no-exclusiva + aplanado (`>\s+<` → `><`) + re-encode a **ISO-8859-1**. Con otra
canonicalización el digest da distinto y marca inválida una firma correcta
(`dry_run_certificacion.py:227-237`).

**Detalle que importa**: el `uri` de la referencia debe ser **`#T{tipo}F{folio}`**, el ID
real del `<Documento>` (`core/dte.py`). El viejo `#DTE-{tipo}-{folio}` **no existía**:
`firmar_xml_sii` no lo encontraba y caía en silencio a firmar el `<DTE>` completo, dejando
una `Reference` colgante.

### Callejones sin salida (NO volver a probarlos)

Se probaron **11 variantes** contra el SII vivo con CAF real; todas dieron el mismo 505:

reparse · substring (`_c14n_en_contexto`) · c14n de lxml sobre subárbol adjunto ·
transform `c14n` · transform `enveloped-signature` · standalone · embebido ·
`saveHTML` (serialización cruda del SignedInfo, como LibreDTE) · `firmar_documento_xml` ·
`signxml` · digest sin namespace en el ápice.

**La invarianza del error era la pista**: si cambias el método de firma y el error no se
mueve, la causa NO es el método. Lo que fallaba era *dónde* se firmaba y *qué pasaba
después*, no *cómo*.

---

## Los estados del SII que PARECEN aceptación y no lo son

El SII tiene varios estados que suenan a éxito y no cierran nada. **Este patrón ya engañó al
proyecto dos veces**; verifica siempre en el nivel correcto:

| Estado | Qué significa DE VERDAD | Dónde está el veredicto real |
|---|---|---|
| **`EPR`** | el **sobre** se procesó | `ACEPTADOS`/`RECHAZADOS` por documento |
| **`LOK`** / `LTC` | el libro **cuadra consigo mismo** | el **SET**: hay que declararlo, y el SII revisa los DATOS aparte |
| **`REC`** (boletas) | el envío se **recibió** | consultar el TrackID después |
| **`EN REVISION`** | el set fue **declarado** | espera el veredicto: `REVISADO CONFORME` o **`SRH`** (rechazado) |

🔴 **Prueba del costo (2026-07-17)**: el Libro de Compras estaba **`LOK`** desde el 12-07 y aun
así el SII rechazó el set (**`SRH`**) por *"El Monto Total No Cuadra"* en el Doc 46. **`LOK` dice
que el libro es internamente consistente, NO que los datos cumplan las reglas del SII.**

⚠️ **`LOK` ≠ set certificado.** Verificado contra el SII el 2026-07-17: los libros de ventas
(track 252999610) y compras (track 253000022) están `LOK` desde el 2026-07-12, y el portal
**sigue mostrando ambos sets como `POR REALIZAR`**. Falta **declarar el TrackID** en el portal
(`pe_avance3`). Enviar y que te acepten **no avanza la certificación por sí solo**.

## `EPR` no es "aceptado"

`EPR` = **"Envío Procesado"**: el **sobre** se procesó. El veredicto por documento va en
`ACEPTADOS`/`RECHAZADOS`/`REPAROS` (`estadistica` en el REST de boleta).

Leerlo como aceptación tuvo al proyecto creyendo que el pipeline funcionaba mientras el SII
rechazaba **todo**. Usar `todo_aceptado`, nunca `estado == "EPR"`.

**El detalle del rechazo**:
- **Facturas (SOAP `QueryEstUp`)**: solo da **conteos**, sin código de error. El código
  (`DTE-3-505`, `HED-3-861`…) llega **solo por correo** → usa la skill **`correos-sii`**
  (pide el token al usuario; ver L5).
- **Boletas (REST)**: devuelve el **código exacto por documento** (`detalle_rep_rech`) en
  segundos. **Por eso conviene usar boletas como banco de pruebas.**

---

## Los sets de certificación tienen ORDEN DE DEPENDENCIA

**Verificado 2026-07-17**: el SII rechazó el `SET LIBRO DE VENTAS` con un único reparo:

> *"**No Tiene un SET Basico Aprobado**"*

⇒ **El SET BÁSICO debe estar aprobado ANTES** de que se pueda aprobar el Libro de Ventas.
Los sets **no son independientes**, aunque el portal los liste como si lo fueran y permita
declararlos en cualquier orden (deja declarar, y **después** rechaza).

⚠️ Se asumió que declarar los libros era "fruta al alcance, no depende del bloqueo de folios".
**Falso**: el Libro de Ventas depende del Set Básico, que depende de folios T33/T61, que están
bloqueados por anti-acaparamiento. **Antes de declarar un set, pregúntate de qué depende.**

(El Libro de **Compras** sí parece independiente del Set Básico: su rechazo fue por datos, no
por dependencia. Pero eso es inferencia de un solo caso, no una regla verificada.)

## Resolución por ambiente (`CRT-3-19`)

La `<Caratula>` lleva `FchResol`/`NroResol`, y **son distintos por ambiente**:

| ambiente | FchResol | NroResol |
|---|---|---|
| certificación | **2026-07-08** | **0** |
| producción (EMPRESA DEMO SPA) | **2014-10-21** | **99** |

Usar siempre **`core.resolucion.resolucion_emisor(rut)`** — la resolución **es de la EMPRESA**,
no del ambiente ni del sistema: cambia con cada contribuyente y el SII la valida por RUT.
`resolucion_emisor` la saca del registro del SII (`info_empresa`, con caché) y cae al global
`settings.resolucion` solo como fallback. ⚠️ **NO usar `settings.resolucion` directo** (le sirve
a UNA empresa y rechaza a otra): a SOFTWARE DEMO SPA 78111111-2 le tocaba **2026-07-19 / 0** en
cert y **99 / 2014-10-21** en prod, no el global 2026-07-08 → daba `CRT-3-19`. La tabla de arriba
es para EMPRESA DEMO SPA 76111111-6. Cableado en orchestrator(_boleta)/preview/scheduler. Ver
`core/resolucion.py`.

**Confírmala SIEMPRE contra el SII**, nunca la copies:
```python
negocios.info_empresa(rut, "produccion")["resolucion"]   # → {'numero': '99', 'fecha': '21-10-2014'}
```

> 🔴 **Caso real (2026-07-17)**: `.env` traía `80 / 2014-08-22` — **que no es la resolución de
> la empresa**. El SII dice **99 / 21-10-2014**. Nadie lo notó porque en certificación esos valores
> no se usan; el día que se pasara a producción, **toda emisión habría muerto con `CRT-3-19`**.
> Corregido. Moraleja: un valor de configuración que el ambiente activo no ejercita **no está
> probado** — verifícalo contra la fuente antes de confiar.

---

## Mensajes engañosos del SII

El SII miente en los errores. Casos confirmados:

| Lo que dice | Lo que era |
|---|---|
| `401 NO ESTA AUTENTICADO` (envío de boleta) | **Faltaba el header `User-Agent`** de navegador. El token estaba perfecto. |
| `500 SOAP Fault "Acceso Denegado"` | Se mandó el **envío** a `apicert`/`api` en vez de `pangal`/`rahue`. |
| `Error 500` al bajar el CAF | Faltaba el header **`Referer`**. |
| `Estado=10 "Error Interno"` al pedir token | Un `<SignedInfo>` con prefijo `ds:` **distinto del que se firmó** (`solicitar_caf_sii.py:435-438`). |
| `HTTP 500` en el facade del RCV | Pedía `Accept: application/json`; **exige `Accept: */*`** (`test_rcv_live.py:38`). |
| `Disponible 0 / Máximo Autorizado 0` | Igual autorizó los folios. |

**Moraleja**: verifica la causa, no la etiqueta. Y el mismo capricho del `User-Agent` ya
estaba documentado para `DTEUpload` en `core/sii.py` — otra vez, leer el repo.

---

## Datos reales del emisor

`HED-3-861 "Actividad Económica no registrada"`: el `Acteco` debe ser uno **real** del
contribuyente, no inventado. EMPRESA DEMO SPA (76111111-6) → **463014** (venta de alimentos al
por mayor). Constantes buenas en `certificacion_sii.py`.

---

## Folios y CAF

**Orden de validación del SII** (un error temprano **enmascara** los siguientes):

```
folio ya recibido (DTE-3-101) → CAF vencido (CAF-3-517) → timbre TED → firma DTE
```

⇒ Para probar la **firma** necesitas folio **fresco** y CAF **vigente**, o no verás nada.

- **`CAF-3-517` (CAF vencido)**: `Firma_DTE − FA_CAF > 6 meses`.
- **Anti-acaparamiento**: el SII bloquea el timbraje si acumulas folios sin usar.
  Estado actual: **T33 y T61 bloqueados**; **T34, T39, T41 libres**.
- **`REF-3-750` ("DTE referenciado no recibido")**: una nota de crédito referencia un DTE que el
  SII aún no procesó. Se resuelve enviando **por olas** (esperar que la ola previa sea aceptada
  antes de mandar la que la referencia) — ver `reenviar_certificacion.py:4-14`.
- **`CrFolio.jws` NO existe en certificación** (Maullín devuelve 404); solo en producción. Por
  eso el timbraje va por **scraping del portal** (`core/sii_portal.py`), no por web service.
- **Un CAF sintético NO sirve para probar firma**: `<FRMA>` es la firma del SII sobre
  `<DA>`, y `<DA>` contiene `TD` y `RNG` → al alterarlos, el SII detecta el CAF adulterado.
  Sirve solo para XSD/estructura/PDF.

### Timbrar folios por el portal (`core/sii_portal.py`)

Flujo real: `of_confirma_folio` → `of_genera_folio` → `of_genera_archivo`. Dos trampas:
1. Para **boletas** el portal pide **DOS** `of_confirma_folio`: el primero devuelve otro
   form pidiendo `FOLIO_INICIAL`, no el `of_genera_folio` que el código espera.
2. `of_genera_archivo` da **Error 500 sin el header `Referer`**.

---

## ⚠️ El XSD NO alcanza: las reglas de negocio viven en los PDF de formato

**Caso real (2026-07-17)**: el Libro de Compras fue rechazado (`SRH`) por dos reparos de datos.
Se probaron **tres variantes** contra `LibroCV_v10.xsd` —incluida **la que el SII rechazó**— y
**las tres pasan**. El XSD comparte el mismo `<Detalle>` entre Libro de Compras y de Ventas y
**no discrimina**.

⇒ **Validar contra el XSD da falsa confianza.** Es necesario, no suficiente. Las reglas están en
**`formato_iecv.pdf`** ("Formato de Información Electrónica de Compras y Ventas", v3.0):
`sii.cl/factura_electronica/factura_mercado/formato_iecv.pdf`

### La regla del t46 con retención total (Libro de COMPRAS)

`IVARetTotal` **es un campo del Libro de VENTAS**, no de Compras. El XSD lo anota:
*"IVA Retenido Total **(LV)**"*. En **Compras**, la retención va en **`<OtrosImp>`**:

| campo | valor | fuente |
|---|---|---|
| `MntIVA` | **el IVA completo** (0.19 × neto) — **NO 0** | formato §3.4 campo 15 |
| `MntTotal` | Neto + Exento + IVA **− IVA retenido** | formato §3.4 campo 25 |
| `OtrosImp` | `CodImp=15`, `TasaImp=19.00`, `MntImp=<IVA>` | formato §3.4 campos 21-23, §7 |
| `IVARetTotal` | **NO va** | es de Ventas (§2.4 campo 28) |
| Resumen | `TotOtrosImp{CodImp=15, TotMntImp}` — **no** `TotIVARetTotal` | formato §3.3 |

Ejemplo real (set 4943175, factura de compra folio 9, neto 10866):
`MntIVA=2065` · `MntTotal=10866` · `OtrosImp{15, 19.00, 2065}`. Se mandó `MntTotal=12931` +
`IVARetTotal=2065` → *"El Monto Total No Cuadra"* + *"No Informa Adecuadamente IVA Retenido Total"*.

**Retención parcial** es distinta: cod 30-41 con la parte retenida, más `<IVANoRetenido>`.

⚠️ **LibreDTE diverge aquí**: emite `IVARetTotal` **también** en compras. Si es inocuo o dañino
**no está determinado** — no copiar sin verificar.

### El redondeo del IVA: half-up, NUNCA `round()` nativo

`round()` de Python usa **banker's rounding** (redondea al par): `round(256.5) → 256`. El SII
recalcula los totales con **half-up**: `256.5 → 257`. La diferencia de **$1** en los netos que
caen justo en `.5` (neto·19 múltiplo de 50: 150, 250, …, 1350…) hace que el SII rechace con
*"El Monto Total No Cuadra"*.

- Usar **`core.dte.redondear`** (Decimal + ROUND_HALF_UP) en toda aritmética tributaria. Nunca
  `round()`. Ya mordió en `core/dte.py` (documentado) y **reapareció en `core/libro.py`** al
  agregar el t46 — lo cazó una revisión, no el test.
- ⚠️ **Un test con un solo monto NO detecta esto**: hay que elegir un neto que caiga en `.5`
  (ej. **1350** → 257 correcto / 256 con el bug). `test_libro.py` tiene ese caso a propósito.

### Trampa al leer los XSD

Son **ISO-8859-1** → `grep` los trata como binarios y **suprime la salida en silencio**:
`grep -c MntIVA LibroCV_v10.xsd` devuelve **vacío, no "0"** — un falso negativo que parece un
"no existe". **Usa siempre `grep -a`.**

## El SII usa un perfil restringido de XMLDSig

`core/xsd/xmldsignature_v10.xsd` es **más estricto** que el W3C:

- **`Transform`: `maxOccurs="1"`** → un solo transform.
- **`KeyValue`/`RSAKeyValue` obligatorios y ANTES de `X509Data`**.

Por eso **no se puede usar una librería estándar tal cual**: `signxml` emite dos transforms
y no emite `KeyValue` ⇒ su firma nunca pasa el esquema. Y **`signxml` tampoco sirve como
verificador**: rechaza firmas que el SII acepta.

---

## Boletas: infraestructura aparte

Res. Ex. SII N° 74 de 2020. Las boletas (39/41) **no comparten nada** con facturas:

| | facturas | boletas |
|---|---|---|
| protocolo | SOAP | **REST** |
| token | de factura | **propio** (el de factura NO sirve) |
| semilla/token/consulta | maullin / palena | `apicert.sii.cl` / `api.sii.cl` |
| **envío** | maullin / palena | **`pangal.sii.cl` / `rahue.sii.cl`** ⚠️ **host distinto** |
| respuesta del envío | XML | **JSON** (`estado=="REC"` → `trackid`) |
| reporte | libro mensual | RVD diario — **ya NO obligatorio** (Res. 53/2022, ver abajo) |

⚠️ **La tabla de arriba es la infraestructura de PRODUCCIÓN de boletas.** El **SET de
certificación** NO va por ese REST — ver la lección siguiente.

⚠️ **El envío de boletas (rahue/pangal) VALIDA el User-Agent (`401 engañoso`).** Verificado en
vivo (2026-07): con **Chrome real → 401**, **Mozilla genérico → 401**, y el **UA de-facto de
LibreDTE** (`Mozilla/5.0 (compatible; PROG 1.0; +https://www.libredte.cl)`) → **EPR aceptado**. O
sea el SII tiene un allowlist de User-Agents (de proveedores registrados). El portal de folios NO
es picky. Por eso el UA es **configurable** (`SII_USER_AGENT`, `core/config.py`) — el default del
repo es neutro; en producción hay que setear uno que el SII acepte. Un `401 No autorizado` en el
envío con token válido = casi siempre el User-Agent.

- Tope de **500 boletas por sobre** — ⚠️ **NO lo dice el XSD**: `EnvioBOLETA_v11.xsd:89` declara
  `maxOccurs="unbounded"` para `DTE` (el `maxOccurs="1000"` del esquema es de **`Detalle`**, las
  líneas *dentro* de una boleta). El 500 sale del Instructivo Técnico del SII y **no está
  verificado en vivo**: es un tope conservador nuestro. *(Este dato circuló un tiempo como "lo
  dice el XSD" — era falso, y de paso acusaba injustamente a LibreDTE de violarlo con 1000.)*
- `SubTotDTE` máximo **2** tipos (vs 20 en EnvioDTE) — esto **sí** está en el XSD.
- Receptor genérico no nominativo: **66666666-6**.
- Diferencias del XML: `IdDoc` lleva **`IndServicio`** (1 serv. periódicos · 2 serv.
  periódicos domiciliarios · 3 ventas y servicios · 4 espectáculo por terceros) y **NO**
  lleva `FmaPago` ni `TasaIVA`; el Emisor usa **`RznSocEmisor`/`GiroEmisor`**.
- IVA **por resta** (`iva = bruto − neto`), nunca `round(neto*tasa)`: descuadra el total.

### El SET de certificación de boletas va por DTEUpload/maullin, NO por el REST (`El Documento no está en el envío`)

**La lección más cara de la certificación de boletas (resuelto 2026-07-21).** El set de boletas
se rechazaba con *"El Documento no está en el envío"* en los 5 casos, aunque el envío respondía
`EPR` (aceptado). Se probaron 5 formatos de referencia, todos rechazados idéntico. **El problema
NO era la referencia — era el CANAL:**

- El **SET de certificación** de boletas se valida SOLO contra los envíos a
  **`maullin.sii.cl/cgi_dte/UPL/DTEUpload` (SOAP)** — el mismo canal de facturas/RVD. El REST de
  **pangal** responde `EPR` pero el validador del set NUNCA ve esos documentos. (El REST
  pangal/rahue es solo para la **producción operativa** de boletas.)
- Enrutar el sobre `EnvioBOLETA` por DTEUpload: `ClienteSII.enviar_dte(sobre, rut, dv,
  tipo_dte=33)` (el `tipo_dte=33` solo elige el canal; el XML es EnvioBOLETA y DTEUpload lo acepta).
- **Referencia mínima** del caso: solo `<NroLinRef>1</NroLinRef><CodRef>SET</CodRef>
  <RazonRef>CASO-N</RazonRef>`. SIN `TpoDocRef`/`FolioRef` (son de factura; por DTEUpload dan
  `HED-3-211`). El "formato B" con TpoDocRef/FolioRef fue un **retroceso**; la mínima siempre fue
  la correcta — lo que mataba el set era el canal.
- Segundo muro tras cambiar de canal: `CRT-3-19` de carátula → era la **resolución por empresa**
  equivocada (ver L4 / `resolucion_por_ambiente`). Con la del emisor: `EPR` y set **SOK**.

Confirmado por múltiples fuentes (repo `github.com/dbenaventep/sii-chile-cert`, r/chileIT) y
verificado en vivo: set SOK → V°B° → Declaración de Cumplimiento → SOFTWARE DEMO SPA autorizada
en producción. Fuente triple-confirmada; ver `core/boleta.py` y `core/sobre.py`.

### El RVD ya NO es obligatorio en producción (Res. Ex. SII 53/2022)

**Verificado EN VIVO (2026-07)**: al enviar el RVD, el SII responde con un **reparo informativo**
(0 errores): *"RVD no es obligatorio desde 2022-08-01"*. Concuerda con la **Res. Ex. SII N° 53 de
2022**, que eliminó la obligación de enviar el Resumen de Ventas Diarias (ex RCOF) desde el
2022-08-01: el Registro de Ventas se arma directo con las boletas que el SII recibe. Correcciones
de ventas → **Nota de Crédito (tipo 61)**, no editando resúmenes.

⚠️ **Sourcing en conflicto — se documenta a propósito.** Una FAQ del SII (2025-05-26,
`.../001_380_7807.htm`) todavía dice que el RVD "sí es obligatorio para software propio". Se le da
**más peso al reparo en vivo (2026) + la Res. 53/2022 + la investigación tributaria del usuario**:
es evidencia directa, actual y específica de NUESTRO envío. *(La versión anterior de esta lección
afirmaba lo contrario ("es FALSO que se derogó") citando esa FAQ 2025; quedó refutada por el
reparo.)*

**Postura práctica:** el RVD **no es una obligación bloqueante**. El programador de RVD
(`core/scheduler.py`) queda **opcional/desactivado** (`RVD_SCHEDULER_ACTIVO=false`, así corre en
producción). En el flujo de **certificación** el set aún lo incluye → se envía por DTEUpload (ver
abajo). Enviarlo es inofensivo (reparo informativo); no enviarlo en producción no acarrea sanción.

### ✅ El RVD NO va por el REST de boletas — va por el canal de FACTURAS

**Resuelto 2026-07-17 con fuente oficial.** El OpenAPI del SII
(`www4c.sii.cl/bolcoreinternetui/api/openapi.yaml`) lo dice textual:

> *"Los sitios rahue.sii.cl y api.sii.cl son plataformas dedicadas a la recepción de Boleta
> Electrónica en Producción. **El sitio de palena.sii.cl es la plataforma dedicada para la
> recepción de DTE y RVD en Producción.**"*

Y la API REST de boleta tiene **exactamente 10 rutas, ninguna de RVD** (verificado). Por eso
`boleta.electronica.envio` rechaza `ConsumoFolios` con `SCH-00001`. El Instructivo lo decía y
se leyó al revés: *"**No hay cambios en el envío de RCOF**, que pasa a denominarse RVD"*.

⇒ **`POST /cgi_dte/UPL/DTEUpload` en maullin/palena, con el token SOAP de FACTURA.**
Implementado en `core/rvd.py::enviar_rvd` (recibe un `ClienteSII`, no un `ClienteBoletaSII`).

🔴 **Dos lecciones caras aquí**:
1. Se probaron **16 nombres de ruta en pangal** buscando algo que no existe. La API estaba
   documentada todo el tiempo: **el spec devuelve `503` sin `User-Agent` de navegador** y con
   uno devuelve `200`. Es la **tercera** vez que el User-Agent nos ciega.
2. Se descartó a **LibreDTE** por mandar el ConsumoFolios "al endpoint viejo con el token de
   factura". **LibreDTE tenía razón**; eso es exactamente el camino correcto.

**Método para descubrir rutas**: en **pangal**, ruta inexistente → `404`; ruta real sin
token → `400 "No trae TOKEN"`. ⚠️ **`apicert` NO sirve para esto**: responde `500` a
cualquier ruta, incluso inventada.

---

## LibreDTE como referencia

- ✅ **Sirve** para: estructura del `EnvioBOLETA`, normalización de boleta, y el **RCOF**
  (`lib/Sii/ConsumoFolio.php`).
- ⛔ **NO sirve** para el envío de boletas: **nunca lo implementó**. `EnvioDte::enviar()`
  hace `if ($this->tipo) return false;` — *"si es boleta no se envía al SII"*. En su master
  sigue siendo un TODO. Cero URLs de boleta en todo el repo.
- ⚠️ Tiene bugs propios: su `getRangos()` revienta con lista vacía y se corrompe con folios
  duplicados (`core/rvd.py::agrupar_rangos` los cubre).
