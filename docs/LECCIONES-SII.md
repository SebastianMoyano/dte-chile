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
| `HED-2-220`, `REF-2-780`, `Clave no corresponde`, `Request Rejected` (portal MIPYME) | [Portal MIPYME por httpx](#portal-mipyme-facturación-gratuita-por-httpx) |
| `mipeSendXML` rechazado por el WAF tras firmar / "el folio ya está gastado" | [Folio perdido por una cadena no verificada](#portal-mipyme-facturación-gratuita-por-httpx) |

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

⚠️ **El envío de boletas (rahue/pangal) y DTEUpload EXIGEN el token `PROG 1.0` en el User-Agent
(`401 engañoso`).** La "magia" NO es LibreDTE — es el string **`PROG 1.0`** (identificador de
"programa" de la implementación de referencia del SII, documentado por el SII como
`Mozilla/4.0 (compatible; PROG 1.0; Windows NT)`). Verificado en vivo (2026-07), reenviando el
MISMO sobre variando solo el UA:
- `Mozilla/5.0 (Windows...) Chrome/120...` → **401**
- `Mozilla/5.0` → **401**
- `Mozilla/5.0 (compatible; DTE-Chile/1.0)` (sin PROG 1.0) → **401**
- `Mozilla/5.0 (compatible; PROG 1.0; +https://www.libredte.cl)` → **EPR aceptado**
- `Mozilla/5.0 (compatible; PROG 1.0; +https://github.com/SebastianMoyano/dte-chile)` (PROG 1.0,
  SIN libredte) → **EPR aceptado** ✅

O sea: cualquier UA **con `PROG 1.0`** pasa; el resto del string (la URL) es libre. LibreDTE solo
copió la convención del SII (su código lo pone sin ningún comentario que lo explique). El portal
de folios NO es picky. El UA es configurable por `SII_USER_AGENT` (`core/config.py`); el default
del repo ya trae `PROG 1.0`. Un `401 No autorizado` con token válido = casi siempre falta `PROG 1.0`.

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

## Portal MIPYME (facturación gratuita) por httpx

> Canal **distinto** al motor: el SII pone el folio, el CAF y la **firma central**. Sirve para
> empresas que están en el gratuito para facturas (el motor no puede timbrarles CAF) y para la
> **NC de anulación de boletas** que [`ANULAR-BOLETA.md`](ANULAR-BOLETA.md) manda hacer por el
> portal. **Solo existe en producción**: cada corrida es un documento real y **gasta un folio**.
> Las facturas de septiembre y la NC 56 salieron de la herramienta del repo Auxin **reutilizando la
> sesión del navegador**; la NC 59, la ND 1 y la factura 62 se emitieron **a mano** en el portal.
> **Desde este repo**: lectura, importación (PDF + XML), firma central y **emisión** verificadas.
> La emisión costó tres folios en `mipeSendXML` (57, 58 y 61) hasta calcar el envío de la captura
> de la 62; con eso salieron la factura 63 y la NC 60 (2026-10-08). Ver "Folio perdido" y "Tercer
> folio" abajo.
> Implementado en `core/sii_mipyme.py` (guía: [`MIPYME.md`](MIPYME.md), test en seco: `test_mipyme.py`).

**La cadena** (`www1.sii.cl/cgi-bin/Portal001/`, CGI legacy):

```
login  POST zeusr.sii.cl/cgi_AUT2000/CAutInicio.cgi   (rut, dv, rutcntr, clave, referencia, 411)
       → cookies NETSCAPE_LIVEWIRE.*  (~2 h, máx ~10 sesiones concurrentes)
1. mipeSelEmpresa.cgi         POST RUT_EMP
2. mipeGenFacEx?IGUAL=ULT_FAC&PTDC_CODIGO=34   → form pre-llenado "igual al último"
2b. mipeDisplayPreView.cgi    POST 54 campos ("Validar y visualizar") → página PreViewDTE  ← OBLIGATORIO (sin esto, GenXMLFirma: "No se pudo generar XML")
3. mipeGenXMLFirma.cgi        243 params → XML con FOLIO + CAF   ⚠️ AQUÍ se consume el folio
4. postFirmaDigital.cgi       clave del CERTIFICADO + XML → XML con <Signature>
5. mipeSendXML.cgi            TODO el frmSign (con duplicados) + firma, ordenado ASCII; XML con CRLF
6. mipeDisplayPDF.cgi?DHDR_CODIGO=<id>
logout: zeusr.sii.cl/cgi_AUT2000/autTermino.cgi SIGUIENDO la redirección (si no, la sesión no muere)
NC de anulación: mipeDisplayPreView.cgi?EHDR_CODIGO=<DHDR>&TIPO_NOTA=61 y la misma cadena con
PTDC_CODIGO=61, TPO_DOC_REF=34, FOLIO_REF, CODIGO_REF=1.
```

**Dos claves distintas, y no son intercambiables:**

| paso | clave | qué es |
|---|---|---|
| login (`CAutInicio`) | clave tributaria | la de entrar a Mi SII |
| firma central (`postFirmaDigital`) | clave del **certificado** | la del `.p12` que el SII guarda centralmente |

Usar la tributaria al firmar da `Clave no corresponde`. Ambas son **credenciales** (L6): keystore
cifrado, nunca en logs.

| Lo que dijo | Lo que era |
|---|---|
| `Request Rejected` + support ID (WAF F5) | **NO es fingerprinting** (se probó `curl_cffi` con TLS de Chrome: mismo rechazo). Era un **body malformado**: `RUT_EMP=77777777` sin el DV (`77777777-7`, 2 bytes). El F5 ASM es **por reglas** (formato, tamaño, caracteres de cada parámetro), no conductual: con requests bien formados **httpx puro pasa, sin navegador** — verificado para login, empresa, form, historial, PDF y la cadena de factura. ⚠️ Para `mipeSendXML` de una NOTA el WAF rechazó un envío de este repo (2026-10-02) por una causa aún no vista: la regla "es por reglas" sigue en pie, pero cuál regla, no. Sumaban sospecha menor: `Accept-Encoding` sin `br, zstd`, POST sin `Cache-Control: max-age=0`, headers con valor `None`. |
| `requerimiento no bien recepcionado` en `GenXMLFirma` | Payload incompleto (48 de 243 campos). El SII espera **el form entero**: GET fresco, parsear todos los inputs, sustituir solo lo tuyo. |
| **`HED-2-220`** (reparo) | Se sustituyeron 2 de los **5** montos (`PRC/SUBT/SUBTOTAL/MNT_NETO/MNT_TOTAL`) → ítem ≠ total. Sustituir los cinco siempre. |
| **`REF-2-780`** (reparo en la NC) | Heredado del documento referenciado inconsistente. No es recursivo: la NC de un doc limpio sale limpia. |
| WAF rechaza `mipeSendXML` (~11 KB) | `txtSignText` iba **sin** `<Signature>` (bug de strip). Debe llevar el XML firmado completo. |
| `%2520` en el body | Doble URL-encoding: XML crudo al dict, sin `quote()` previo. |
| Folios "perdidos" | Cada prueba que llega a `GenXMLFirma` gasta uno aunque no envíe. Modo dry-run = parar **antes** del paso 3. |

**El método que lo destrabó** (reusable para cualquier CGI del SII — y lo que NO se hizo con
las 11 variantes de firma del `DTE-3-505`):

1. Capturar con **mitmproxy** una corrida real del navegador: esa es la referencia, byte a byte.
2. Replicar en httpx **el request más simple** de la cadena.
3. **Diff byte a byte** contra la referencia: headers, cookies, body. Corregir **solo** las
   diferencias reales, no adivinar.
4. Iterar con un paso que **no cueste nada** (el GET del form), nunca con el que gasta folio.
5. Recién con 200 limpio, ejecutar el paso que consume recursos.

Regla derivada de L12: `Request Rejected` "olía" a antibot y era un bug de 2 bytes. **Verifica la
causa, no la etiqueta.** En el motor el RUT viaja siempre completo (`12345678-9`); no lo partas en
dos variables de entorno.

**Folio perdido por correr una cadena no verificada (2026-10-02).** La NC de anulación por httpx
se lanzó en producción sin haberse corrido nunca desde este repo: `GenXMLFirma` asignó la NC
folio 57, la firma central funcionó y el **WAF rechazó el envío** (`Request Rejected`, 246 bytes,
el mismo tamaño que devuelve a cualquier URL inexistente). Folio gastado, sin documento. Se
descartaron con cuerpos falsos contra `mipeSendXML` (el SII los rechaza sin crear nada, no gastan
folio): la descripción larga, el `°`, la clave del certificado. La causa quedó sin ver porque no se
guardó la respuesta. **Lo que faltó fue leer antes la implementación que SÍ emitió la NC 56**
(repo Auxin, `app/sii/service_http.py`): manda a `mipeSendXML` los campos del `frmSign` que
devuelve la página de firma, con la cookie `usa_firma_central` y el referer de `mipeGenXMLFirma`,
no una reconstrucción del schema. Es L10 otra vez. Gates agregados: `CADENAS_VERIFICADAS` (emitir
un tipo no verificado exige `aceptar_riesgo_folio`), evidencia saneada en `storage/mipyme_fallidos/`
ante cualquier fallo, y envío de notas con el `frmSign` real.

**Segundo intento (2026-10-02, NC folio 58, también perdido).** Con el envío por `frmSign` el WAF
ya NO rechazó: la app del SII respondió "Error al contribuyente" (1017 B, alert "Por el momento no
se puede responder a sus requerimientos", código 02.35.209.45.930.13). El XML firmado era correcto
(T61 folio 58, MntTotal 3.068.005, FolioRef 57, CodRef 1). El frmSign real de una nota trae 249
campos, en otro orden que el schema, con `EFXP_RUT_RUT_EMP` y SIN `ES_BORR`/`INDICA`/`esCRED_EC`.
Lo que falta para resolverlo es la **página de firma** (`mipeGenXMLFirma`) con su JS inline, que
arma el envío real: desde ahora el módulo la guarda siempre (`respuesta_genxmlfirma.html`) junto a
la respuesta cruda de `postFirmaDigital`. Un GET a `mipeGenXMLFirma.cgi` sin cuerpo NO recupera el
documento pendiente ("requerimiento no bien recepcionado"). Ese artefacto (la página de firma con su frmSign) quedó guardado en el tercer intento, ver abajo.

**Tercer folio (2026-10-08, factura 61) y la referencia completa.** Primer intento del módulo:
`GenXMLFirma` respondió "No se pudo generar XML para firmar" (código 02.35.209.44…) porque el
módulo saltaba `mipeDisplayPreView` ("Validar y visualizar", 54 campos): el portal necesita ese
paso antes de generar el XML. Sin folio perdido (se asigna en GenXMLFirma). Segundo intento, con
el paso agregado: previsualización OK, folio 61 asignado, firma central OK, y `mipeSendXML`
rechazado por el WAF (246 B). La factura se emitió a mano (folio 62) **con la extensión grabando
el flujo completo**, y esa captura es la referencia byte a byte de un envío de factura. Comparada
con el intento del 61 (mismo frmSign, mismos 249 nombres de campo), las únicas diferencias eran
de forma: el navegador manda **todos los inputs del frmSign, con el duplicado `EFXP_FMA_PAGO`,
más los de firma, ordenados por nombre en ASCII**, y los dos XML con saltos **CRLF** (son valores
de `<textarea>`). El módulo mandaba otro orden y LF; para facturas además reconstruía el cuerpo
desde el schema. Corregido (`armar_send_xml_desde_form`, único camino para todos los tipos) y
verificado en seco (secuencia de 250 campos idéntica a la del navegador) y luego **en real, el
mismo día: factura 63 (DHDR 2881744181) y la NC 60 que la anula (DHDR 2881747811), prueba
Auxin → Moyoli por $1.000**. Primera emisión completa desde este repo; `CADENAS_VERIFICADAS` ya
tiene 34 y 61.
Dos lecciones más del mismo día: el `cerrar()` del módulo no cerraba la sesión (herculesr sin
seguir el 302) y cada corrida dejaba una viva ~2 h hasta el tope por RUT; y el comparador leía la
evidencia partida por líneas e inventaba nombres de campo desde el base64 de la firma. Ambos
corregidos. Con una captura completa del navegador, el diff fiel tarda minutos; sin ella, se
pierden folios adivinando.

**Lo que hace de verdad el navegador al firmar (leído del JS del portal, `pluginsii-1.2.js` y la
página de firma guardada en abril por una sonda, sin gastar folio):** el botón Firmar de la vista
previa (`goSignDTE`) manda el form `PreViewDTE` directo a `mipeGenXMLFirma` (sin `mipePreView`,
sin los botones). La página de firma trae `frmSign` (245 campos, `TMST_SIGN` ya puesto por el
servidor, action con `?csrt=` inyectado por el script TSbd del F5) y `signXmlCompatible` hace:
`dato = txtPlainText.replace("&","&amp;")` + comentario `<!-- O <platform> <browser> <ver> central
VERSION: v20190409 -->` antes de `<Documento`; POST a `postFirmaDigital` (jQuery, UTF-8) con
`nombre=certId` ("1" para firma central), `rut/dv` de las cookies `NETSCAPE_LIVEWIRE`, `clave`,
`nodo=dte:DTE`, `nodoId=dte:Documento`, `nameSpace`; la respuesta cruda va a `txtSignText`;
inserta hidden `nombre/clave/nodo/nodoId/nameSpace` **antes de `txtPlainText`** y hace
`frmSign.submit()` (TMST_SIGN intacto). El módulo replica esto para notas desde 2026-10-02.
**No todo lo del repo Auxin funcionó**: los intentos Python de abril acabaron en "Firma no
reconocida"; el Apps Script (`_external_assets/gas-dashboard/Code.gs`) parsea `postFirmaDigital`
como JSON `{statusCode,text}` y manda `frmSign` sin tocar `TMST_SIGN`.
**Firma central VERIFICADA desde este repo (2026-10-04, flujo "Obtener Envío", sin folio).** Capturado
con la extensión `tools/captura-sii` en un navegador real y replicado por `ClienteMipyme._firma_central`:
POST `postFirmaDigital.cgi` como XHR (`Content-Type: application/x-www-form-urlencoded; charset=UTF-8`,
`X-Requested-With: XMLHttpRequest`, `Accept: text/plain, */*; q=0.01`) con `nombre=1`, `dato` = XML con
`&`→`&amp;` y el comentario `<!-- O MacIntel Chrome 154 central VERSION: v20170209 -->` antes del
primer `<Documento`, `rut/dv` del usuario, `clave` del certificado, `nodo`/`nodoId`/`nameSpace`. La
respuesta es el **XML firmado en texto plano** (`text/plain; charset=iso-8859-1`), no JSON. El XML
que devolvió el módulo fue idéntico al del navegador salvo `TmstFirmaEnv` y la firma. Por tanto, lo
que sigue sin explicar en la NC 58 NO es la firma: es `mipeSendXML` o una regla de negocio.

**Causa más probable del "Error al contribuyente" de la NC 58 (con la captura real de una NC del
2026-10-04 en la mano):** el XML que el módulo mandó a firmar NO llevaba el comentario
`<!-- O … central VERSION: … -->` que el JS del portal antepone a `<Documento` antes de llamar a
`postFirmaDigital`. En el flujo real, `txtSignText` SÍ lo lleva (y `txtPlainText` no): es la marca
con la que el backend reconoce una firma centralizada. Todo lo demás coincide con el navegador:
mismos 243 campos a `GenXMLFirma`, mismo `frmSign` + 5 campos de firma a `mipeSendXML`, `TMST_SIGN`
igual al `TmstFirma`, sin `csrt`, `mipePreView` es solo el PDF de la vista previa. La regla de
negocio "57 ya tiene NC" quedó descartada en la práctica: el portal aceptó una NC de corrección
(código 3) sobre la 57. La anulación (código 1) repetida sigue sin probarse. Se verifica en la
próxima nota real emitida por el módulo (ahora `preparar_dato_firma` pone el comentario).

⚠️ No verificado: la NC de **boletas** (`mipeSelEmpresaBol.cgi`, con la especificidad descrita en
`ANULAR-BOLETA.md`) no está ni cableada. La NC de factura por httpx la logró el repo Auxin; desde
este repo todavía no (ver arriba).

---

## LibreDTE como referencia

- ✅ **Sirve** para: estructura del `EnvioBOLETA`, normalización de boleta, y el **RCOF**
  (`lib/Sii/ConsumoFolio.php`).
- ⛔ **NO sirve** para el envío de boletas: **nunca lo implementó**. `EnvioDte::enviar()`
  hace `if ($this->tipo) return false;` — *"si es boleta no se envía al SII"*. En su master
  sigue siendo un TODO. Cero URLs de boleta en todo el repo.
- ⚠️ Tiene bugs propios: su `getRangos()` revienta con lista vacía y se corrompe con folios
  duplicados (`core/rvd.py::agrupar_rangos` los cubre).
