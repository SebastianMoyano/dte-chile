# Canal MIPYME — el Sistema de Facturación Gratuito del SII, por httpx

> Hoja del [`MAPA.md`](MAPA.md). Las trampas y su porqué están en
> [`LECCIONES-SII.md`](LECCIONES-SII.md#portal-mipyme-facturación-gratuita-por-httpx).
> Código: `core/sii_mipyme.py` · script: `emitir_mipyme.py` · test: `test_mipyme.py`.

## Qué es y qué NO es

Es un **segundo canal de emisión**, distinto al motor. El SII pone el folio, el CAF y la
**firma central** (con el certificado que el propio SII guarda). Nada pasa por `core/sobre.py`,
`core/caf.py` ni por CAF locales. **No es un tipo de DTE más**: es el portal del gratuito manejado
por HTTP en vez de a mano.

| | motor (`core/orchestrator.py`) | canal MIPYME (`core/sii_mipyme.py`) |
|---|---|---|
| folio | CAF propio, `consumir_siguiente_folio` | lo pone el SII en `mipeGenXMLFirma` |
| firma | `core/sobre.py` (Ley L2) | central, `postFirmaDigital` con la clave del certificado |
| ambiente | certificación o producción | **solo producción** |
| quién puede | empresa con software propio certificado | empresa en el gratuito para facturas |
| transporte | SOAP `DTEUpload` | CGI legacy `www1.sii.cl/cgi-bin/Portal001/` |
| evidencia | TrackID 253113966 → `ACEPTADOS: 1` | factura: T34 folio 59 (2026-09-06) y 62 (2026-10-08) sin reparos, **no emitidas por este repo** (herramienta Auxin / a mano) · lectura/importación: verificada desde este repo (Auxin, 46 documentos, 2026-09-07) · NC por httpx desde este repo: **FALLÓ** (2026-10-02, folio perdido) |

## Para qué sirve

1. **Facturas de una empresa que está en el gratuito.** El SII no le timbra CAF a software
   externo, así que el motor no puede emitirle ni una T34 (ver `CERTIFICACION.md`). Este canal
   la emite **sin sacarla del gratuito**, porque literalmente usa el gratuito.
2. **NC de anulación de boletas por el portal**, que [`ANULAR-BOLETA.md`](ANULAR-BOLETA.md) manda
   hacer así para no convertirse en facturador de mercado. ⚠️ Verificado solo para la NC de una
   **factura**; la variante de boletas (`mipeSelEmpresaBol.cgi`) sigue **sin verificar**.

## Reglas de uso (las que cuestan plata)

- **Solo producción, sin sandbox (Ley L1).** Cada corrida que llega a `mipeGenXMLFirma` gasta un
  folio real aunque después falle la firma o el envío. Por eso `preparar()` no gasta folio (sí
  abre una sesión real, y hay tope de ~10) y `emitir()` exige `confirmar=True`. Para leer basta la
  clave tributaria; la del certificado solo hace falta al emitir.
- **Dos claves distintas (Ley L6).** La tributaria abre la cuenta; la del certificado firma.
  Usar la tributaria al firmar → `Clave no corresponde` y el folio ya está gastado. Se piden por
  consola; no van a `.env`, ni a logs, ni a la BD.
- **RUT completo, con DV, siempre.** `RUT_EMP` sin DV fue la causa del `Request Rejected` del
  WAF. En el motor el RUT viaja entero (`12345678-9`); no lo partas en dos variables.
- **Los 5 montos alineados.** `PRC_nn`, `SUBT_nn`, `SUBTOTAL`, `MNT_NETO`, `MNT_TOTAL` salen del
  mismo número (`armar_payload` lo hace). Sustituir solo dos → reparo `HED-2-220`.
- **La factura pasa por "Validar y visualizar" antes de firmar.** `preparar()` hace el POST a
  `mipeDisplayPreView` con los 54 campos del navegador (`CAMPOS_VALIDAR_FACTURA`) y arma el payload
  desde la página PreViewDTE. Ir directo a `mipeGenXMLFirma` desde una sesión httpx limpia devuelve
  "No se pudo generar XML para firmar" (código 02.35.209.44…; 2026-10-08, sin folio perdido). La
  cadena de septiembre funcionó porque reutilizaba la sesión del navegador, que ya había
  previsualizado (contrato de Auxin, §3). Un fallo en GenXMLFirma ahora también deja evidencia.
- **Una sesión por corrida, y cerrada de verdad.** `cerrar()` (el `with`) llama a
  `zeusr.sii.cl/cgi_AUT2000/autTermino.cgi` **siguiendo la redirección**; verificado 2026-10-08:
  tras cerrar, `mipeSelEmpresa` manda al login. El cierre anterior (`herculesr`, sin seguir el 302)
  no cerraba nada: cada corrida dejaba una sesión viva ~2 h, se llegó al tope (~10 por RUT) y el
  navegador del usuario recibió `ayudas/900.html` ("no lo podemos atender"). Si cerrar() avisa
  "autTermino no cerró la sesión", el SII cambió algo: mirar antes de seguir corriendo.
- **Factura 62 (2026-10-08) emitida a mano con captura completa** (`captura_zeusr…17-00-03`): es la
  referencia byte a byte del envío de una factura. Lo que mostró, comparado con el intento del folio
  61 (mismo frmSign, mismos 249 nombres): el navegador manda a `mipeSendXML` **todos los inputs del
  frmSign, con duplicados (`EFXP_FMA_PAGO` ×2), más los de firma, ordenados por nombre en ASCII**;
  el módulo mandaba firma-antes-de-txtPlainText y el resto en orden del HTML. Corregido en
  `armar_send_xml_desde_form` y **verificado con la factura 63 y la NC 60 (2026-10-08)**.
- **Datos del emisor en el portal:** el formulario exige también la **ciudad de origen** (p. ej.
  Buchupureo); el módulo la toma del propio form (`EFXP_CIUDAD_ORIGEN`).
- **Folios perdidos en `mipeSendXML`: 57 y 58 (NC, 2026-10-02) y 61 (factura, 2026-10-08).** En los
  tres casos GenXMLFirma y la firma central funcionaron y el envío final fue rechazado por el WAF
  (246 B). La evidencia del 61 está completa (`storage/mipyme_fallidos/…/T34_F61_…`). La causa era el
  cuerpo del envío (orden, duplicado, CRLF); con el envío calcado de la captura de la 62 el módulo
  emitió solo la **factura 63** y la **NC 60** que la anula (prueba Auxin → Moyoli por $1.000,
  2026-10-08, BD id 118 y 119).
- **Forma de pago: contado (1) por defecto** desde 2026-10-08. Las facturas de la primera prueba en
  vivo (septiembre 2026) salieron a crédito (2) porque ese era el default del CLI, no por decisión
  del usuario; no tiene efecto tributario, solo la condición de pago registrada.
- **La NC de anulación lleva el TOTAL registrado del documento, no la línea.** `preparar_nc_anulacion`
  lee el total desde el PDF del SII (`total_registrado`, regex `TOTAL $` sobre el texto, necesita
  `pypdf`) y se niega si la NC no coincide (`verificar_monto=False` lo apaga; no protege facturas).
  El listado del portal NO sirve para esto: en un documento inconsistente muestra la línea. Caso
  real (2026-09-06): factura 57 con línea 3.270.323 y total 3.068.005; la NC 56 salió por la línea →
  `REF-2-780` y una corrección con nota de débito + NC nueva. El test `test_guardarrail_nc` usa los
  PDF reales de `storage/pdfs/mipyme/` y **se omite si no están**.
- **Cadenas verificadas desde este repo (`CADENAS_VERIFICADAS`): factura exenta (34) y NC de
  anulación (61)**, ambas el 2026-10-08 (factura 63 → NC 60). Para un tipo que no esté en la lista
  (nota de débito 56, NC de corrección de montos, boletas) `emitir()` exige `aceptar_riesgo_folio=True`
  (CLI: `--acepto-riesgo-folio`). Un fallo después de `GenXMLFirma` deja un folio gastado; la
  evidencia (respuesta, XML firmado, body, con claves tachadas) queda en
  `storage/mipyme_fallidos/<rut>/`. Cuando una corrida real pase, se agrega el tipo con su evidencia.
- **Sin reintentos automáticos.** El cliente usa `httpx.Client` a secas, no `ClienteReintentos`:
  reintentar `GenXMLFirma` en un 502 gastaría dos folios.
- **Cerrar la sesión.** Tope de ~10 sesiones concurrentes por RUT. `ClienteMipyme` es un context
  manager y llama a `autTermino.cgi` al salir.
- **Drift del form.** El payload es *schema (243 nombres) + HTML fresco + sustituciones*. Si el
  HTML trae un input que el schema no conoce, `PayloadMipyme.campos_nuevos` lo lista y se loguea:
  el SII cambió el form, revisar antes de emitir.

## La cadena

```
login   POST zeusr.sii.cl/cgi_AUT2000/CAutInicio.cgi   rut, dv, rutcntr (con puntos), clave, referencia, 411
        → cookies NETSCAPE_LIVEWIRE.*   (~2 h)
1.  GET  mipeLaunchPage.cgi?OPCION=34&TIPO=4  →  GET mipeSelEmpresa.cgi  →  POST mipeSelEmpresa.cgi (RUT_EMP con DV)
2.  GET  mipeGenFacEx.cgi?IGUAL=ULT_FAC&PTDC_CODIGO=34   form pre-llenado "igual al último"   ← gratis
2b. POST mipeDisplayPreView.cgi  54 campos ("Validar y visualizar") → página PreViewDTE (243 campos)  ← OBLIGATORIO, gratis
3.  POST mipeGenXMLFirma.cgi   243 campos, ISO-8859-1    → XML con <Folio> y CAF               ← GASTA EL FOLIO
4.  POST postFirmaDigital.cgi  nombre=1, dato=<xml>, rut, dv, clave=<cert>, nodo=dte:DTE,
                               nodoId=dte:Documento, nameSpace=http://www.sii.cl/SiiDte
                                                          → XML con <Signature>
5.  POST mipeSendXML.cgi       TMST_SIGN, nombre, clave, nodo, nodoId, nameSpace,
                               txtPlainText (sin firma), txtSignText (CON firma),
                               + form sin INDICA_PRIMERA_EJECUCION, con EFXP_FOLIO tras PTDC_CODIGO
                                                          → "Documento Firmado y Enviado" + DHDR_CODIGO
6.  GET  mipeDisplayPDF.cgi?DHDR_CODIGO=<id>              → PDF
```

**NC de anulación (T61):** `GET mipeDisplayPreView.cgi?EHDR_CODIGO=<DHDR>&TIPO_NOTA=61` pre-construye
la NC; después es la misma cadena con `PTDC_CODIGO=61`, `TPO_DOC_REF_001=34`, `FOLIO_REF_001`,
`FCH_REF_001`, `CODIGO_REF_001=1`, `RAZON_REF_001=ANULA DOCUMENTO DE LA REFERENCIA`. Los ítems
deben ser los del documento anulado: si el monto difiere → reparo `REF-2-780`. La NC con reparo
**anula igual** ("Aceptado con Reparos"). Implementada en `preparar_nc_anulacion()`.

**Estado real (2026-10-02): la NC por httpx desde este repo se intentó y FALLÓ.** `GenXMLFirma`
asignó la NC folio 57 y la firma central funcionó; `mipeSendXML` fue rechazado por el WAF
("Request Rejected", 246 bytes) y el folio quedó gastado sin documento. Desde entonces el envío
de notas (56/61) NO reconstruye el body por schema: toma los campos del `<form name="frmSign">`
que devuelve `mipeGenXMLFirma` (`armar_send_xml_desde_form`), usa su `action`, pone la cookie
`usa_firma_central`, usa `mipeGenXMLFirma.cgi` como Referer y respeta `ES_BORR`/`EFXP_FMA_PAGO`/
`INDICA_PRIMERA_EJECUCION` tal como vienen del portal. Es lo que hace la implementación que SÍ
emitió la NC 56 (repo Auxin, `app/sii/service_http.py`). **Esa rama nueva no se ha vuelto a
correr.** Las facturas siguen con la reconstrucción por schema (`armar_send_xml`).

**NC para CORREGIR MONTOS (código 3) — cadena real capturada el 2026-10-04** (extensión Captura SII,
NC 59 de Auxin emitida con éxito en el navegador; replicada en `preparar_nc_correccion_montos()`):

```
GET  mipeGenFacEx.cgi?IGUAL=CORR_MNT&VALOR=<DHDR>&PTDC_CODIGO=61      form editable (39 inputs + JS)
POST mipeDisplayPreView.cgi   60 campos exactos (CAMPOS_VALIDAR_CORR_MNT): TIPO_PLANTILLA=CORR_MNT_V_NC,
                              CANT_DET=3, REF_SI_NO=SiChecked, MNT_TOTAL_ORI=<total del doc>, ref código 3
                              "CORRIGE MONTO", ítems y los 5 montos        → página PreViewDTE (243)
(POST mipePreView.cgi: solo renderiza el PDF de la vista previa, devuelve application/pdf; no es estado)
POST mipeGenXMLFirma.cgi      los 243 de PreViewDTE (sin botones)         → página de firma (frmSign, TMST_SIGN)
POST postFirmaDigital.cgi     XHR UTF-8, dato = XML + <!-- O … central … --> → XML firmado crudo
POST mipeSendXML.cgi          frmSign (245) + nombre/clave/nodo/nodoId/nameSpace → "ENVIADO EXITOSAMENTE" + DHDR
```
Datos del flujo real: `TMST_SIGN` de la página == `TmstFirma` del XML firmado (el servidor fija la hora al
generar); `txtPlainText` sin comentario, `txtSignText` CON el comentario; sin `csrt` en el `action`.
Una NC de corrección por el total registrado deja el documento en cero (así quedó la factura 57).
Esta rama del módulo tampoco se ha corrido aún para emitir (solo su POST de vista previa está
cubierto por test en seco).

**Nota de débito (T56):** su formulario es el mismo (`mipeDisplayPreView?EHDR_CODIGO&TIPO_NOTA=56`,
capturado 2026-10-02 al emitir a mano la ND 1 que anuló la NC 56). No hay `preparar_nota_debito`
todavía; `emitir()` la trataría como nota (frmSign) si alguien arma el payload.

## Historial de emitidos, PDF y XML

> **En Go (SII engine, fase 6 del port):** este segmento ya está portado en `nucleo/siiengine`
> (`nucleo/bin/nucleo-siiengine sesion|listar|importar`), verificado en vivo el 2026-10-08 con
> los mismos resultados que el módulo Python. La emisión (segmentos 2-4) sigue en Python hasta
> que el Go reproduzca los cuerpos de la factura 63 y la NC 60. Ver `docs/PLAN-PORT.md`.

- **Listado**: `GET mipeAdminDocsEmi.cgi` con `RUT_RECP, FOLIO, RZN_SOC, FEC_DESDE, FEC_HASTA,
  TPO_DOC, ESTADO, ORDEN, NUM_PAG` (paginado, "Página N de M", hasta `pag_max=20` páginas). Cada
  fila trae el enlace `mipeGesDocEmi.cgi?CODIGO=<DHDR>` y las celdas `[RUT receptor, razón social,
  tipo (texto), folio, fecha, monto, estado]`. `ClienteMipyme.listar_emitidos()` + `parsear_listado()`.
  **Verificado desde este repo** (2026-09-07, Auxin: 46 documentos importados con PDF).
  ⚠️ El `monto` del listado es la LÍNEA, no el total firmado (factura 57: 3.270.323 vs 3.068.005).
- **PDF**: `mipeDisplayPDF.cgi?DHDR_CODIGO=<id>`. `descargar_pdf()`. Verificado desde este repo
  (los 46 PDF de Auxin) y por el tool externo.
- **Importar al motor**: `importar_emitidos()` mete cada documento en `dtes` (canal MIPYME,
  estado `emitido_mipyme`, DHDR en `track_id`, idempotente por rut/tipo/folio) y guarda el PDF en
  `storage/pdfs/mipyme/<rut>/`. Endpoint `POST /api/v1/mipyme/importar`; botón **Importar
  emitidos (PDF)** en el panel Portal SII. Después se ven en `/documentos`.
- **XML de lo ya emitido: RESUELTO** (verificado desde este repo 2026-10-04, factura 57, idéntico
  al que baja el navegador). Es el botón "Obtener Envío" del portal: `GET mipeGenDLNewEnvio.cgi?
  CODIGO=<DHDR>&TPO_DOC=<tipo>&RUT_RCP=<rut>&DV_RCP=<dv>` devuelve un `frmSign` con el `EnvioDTE`
  en la textarea `txtPlainText`; se firma centralmente (nodo `dte:EnvioDTE`, nodoId `dte:SetDTE`,
  clave del certificado) y se hace `POST mipeDownLoadNewEnvio.cgi` con `txtSignText` → adjunto
  `.xml`. `ClienteMipyme.obtener_envio_xml()`; `importar_emitidos(..., con_xml=True)` lo guarda en
  `dtes.xml_firmado` y en `storage/dtes/mipyme/<rut>/`. En la página: campo opcional "Clave del
  certificado" en Sincronizar. No gasta folio.

## Capturar un flujo real del portal (extensión "Captura SII")

`tools/captura-sii/` es una extensión de Chrome con un botón Grabar/Detener: guarda, en orden,
las peticiones y **respuestas** a `sii.cl` de la pestaña (claves tachadas, cookies omitidas) y
descarga un JSON. `tools/captura-sii/comparar_captura.py captura.json --evidencia <carpeta de
storage/mipyme_fallidos/...>` lo cruza campo a campo con lo que mandó el módulo. Es la forma de
diagnosticar un rechazo del portal **sin gastar folios**: capturar el flujo a mano una vez y
comparar. Instalación y uso en `tools/captura-sii/README.md`. También sirve para "Obtener
Envío" (`mipeGenDLNewEnvio.cgi`: el XML de un documento emitido, pide la clave), eboleta y F29.

## Lo que las capturas del 2026-10-04 dejaron verificado (sin gastar folios)

- **Factura "igual a la última"**: el "Validar y visualizar" del navegador manda **54 campos** a
  `mipeDisplayPreView.cgi` (`CANT_DET=1`, helpers `*_DEFUALT`, `EFXP_ACTECO_SELECT`, `EFXP_FMA_PAGO=1`
  contado…) y recibe la página PreViewDTE (243 campos, `PTES_ESTADO`/`TIPO_PLANTILLA`/`MNT_TOTAL_ORI`
  vacíos). El form `IGUAL=ULT_FAC` viene con `EFXP_CIUDAD_ORIGEN` y `EFXP_CIUDAD_RECEP` **vacíos**: el
  usuario los llena a mano; el módulo pone la ciudad del receptor y deja la de origen como venga.
  "Corregir" desde la vista previa reenvía los 243 campos a `mipeGenFacEx.cgi`.
- **RCV (`core/rcv.py`) verificado en vivo desde el repo** con la sesión por clave tributaria:
  ventas y compras de Auxin 2026-09 coinciden con el portal y con la propuesta F29 del SII.
  Contrato real: `conversationId` = cookie `CSESSIONID`, `transactionId` uuid, Export con
  `accionRecaptcha` (`RCV_DDETV` ventas / `RCV_DDETC` compras) y `tokenRecaptcha="t-o-k-e-n-web"`
  (placeholder, no hay reCAPTCHA), `estadoContab` vacío en ventas y `REGISTRO` en compras; la
  respuesta es CSV con `;` dentro de `data`. `getResumen` da totales por tipo.
- **F29 (app `propuestaf29ui` + formulario GWT `rfiInternet`)**: API JSON con el mismo sobre
  `metaData/data`. `getDeclaracionConCondicionesYTipoPropuesta` entrega la propuesta del SII con
  códigos (Auxin 2026-09: 142=6.136.010, 511/520=10.627, 586=4, 563=6.136.010, 115=1), es decir,
  **la propuesta de septiembre lleva 6.136.010 en exentas** (la corrección ND 1 + NC 59 cae en
  octubre: +202.318). `PPTA_HABILITAR_SMOV:N` → el "sin movimiento" no está en la app de
  propuesta; vive en el formulario GWT, que habla GWT-RPC (`formularioFacade`, payloads `7|0|…`).
  Como persona natural el formulario falla (`PRE-0006-207`); como empresa entra. Automatizar el
  envío exige replicar GWT-RPC: pendiente, con captura de una declaración real.
- **NC de boletas (`mipeSelEmpresaBol.cgi`)**: el rebote está explicado. La página pide entrar
  "con RUT y Clave o Certificado de la persona autorizada por la empresa para emitir este
  documento" y su selector `RUT_EMP` viene **vacío**: la persona no está registrada como usuaria
  autorizada de boletas en ninguna empresa. Es un registro del sistema de boletas (el nuevo
  `eboleta.sii.cl` tiene `/gestor-get-usuarios` y `/update-usuarios-sii/`), no de facturas.
  Desde el navegador la página redirige al login en bucle. Siguiente paso: capturar la
  administración de usuarios de eboleta y dar de alta a la persona.

## Desde la página

En `/certificados`, cada negocio tiene el botón **Portal SII**. Pide el RUT de quien entra al SII
(por defecto el del certificado) y la clave tributaria, y tiene una sola acción, **Sincronizar
con el SII** (`POST /api/v1/mipyme/sincronizar`): entra, elige la empresa, lee el form (emisor,
drift), lista el historial e importa lo nuevo con su PDF a `dtes`. Muestra el resumen y la lista;
los enlaces del menú y el detalle del form quedan plegados en "Detalles técnicos". **Solo lectura,
producción, no gasta folio.** La clave viaja en esa petición, se usa en memoria y no se guarda.
Los endpoints `/diagnostico` (solo lectura del form y menú) e `/importar` (solo historial)
siguen disponibles para la API. Router: `api/routes/mipyme.py`.

## Cómo se usa (línea de comandos)

```bash
# 1. En seco: valida el schema, el parser, los montos y la estructura del envío. Sin red.
.venv/bin/python test_mipyme.py

# 2. Sesión real, solo lectura del form (no gasta folio). Pide la clave por consola.
.venv/bin/python test_mipyme.py --live --usuario 12.345.678-9 --empresa 77.777.777-7

# 3. Dry-run de una factura: sesión + form + payload, sin emitir.
.venv/bin/python emitir_mipyme.py --usuario … --empresa … --receptor … --razon … --giro … \
    --dir … --ciudad … --comuna … --glosa Arriendo --precio 3270323 --detalle "-Octubre PAGO DE : 3.270.323"

# 4. Emitir de verdad (gasta 1 folio, PRODUCCIÓN) y registrar en la BD.
…  --emitir --guardar
```

Desde código:

```python
from core.sii_mipyme import ClienteMipyme, ItemMipyme, ReceptorMipyme, TIPO_FACTURA_EXENTA

with ClienteMipyme(rut_usuario, clave_tributaria, clave_certificado) as cli:
    cli.iniciar_sesion()
    cli.seleccionar_empresa("77.777.777-7")
    payload = cli.preparar(TIPO_FACTURA_EXENTA, receptor, [ItemMipyme("Arriendo", 3_270_323)])
    res = cli.emitir(payload, confirmar=True)        # res.folio, res.dhdr, res.xml_firmado, res.pdf
```

## Persistencia

`registrar_en_bd()` guarda el documento en `dtes` con `ambiente=produccion`, estado
`emitido_mipyme`, `monto_exento=total` y el XML firmado por el SII. Este canal no tiene TrackID:
en `track_id` va el **`DHDR_CODIGO`** (el id que el portal usa para el PDF y para la NC).

## Pendiente / no verificado

- **Factura exenta y NC de anulación: VERIFICADAS** (2026-10-08, factura 63 y NC 60, prueba
  Auxin → Moyoli por $1.000, emitidas por `emitir_mipyme.py` sin navegador). La **NC de corrección
  de montos** (`--corregir-dhdr`, otro form de 60 campos) solo está verificada en seco contra la
  captura de la NC 59: la próxima real es la prueba, con `--acepto-riesgo-folio`.
- **Nota de débito (T56)**: form capturado, sin `preparar_nota_debito`; la ND 1 se emitió a mano.
- NC de anulación de **boletas** (`mipeSelEmpresaBol.cgi`): ni cableada ni verificada.
- Los documentos importados sin clave del certificado no tienen XML (`xml_firmado=None`):
  `/documentos/{id}/xml` responde 404 para ellos. Con la clave, Sincronizar los trae.
- Emitir y anular desde la página y desde la app (hoy: diagnóstico, importar y sincronizar).
- Ruteo automático por empresa en `emitir_documento` (gratuito → MIPYME, software propio → motor).

## Claves: qué se pide, dónde viven, cuándo se recuerdan

Operar el gratuito "como la persona" necesita dos claves con papeles distintos:

| clave | para qué | de quién |
|---|---|---|
| **tributaria** | entrar al SII y actuar por la empresa | la persona autorizada (`rut_usuario`) |
| **del certificado** | la firma central (`postFirmaDigital`): emitir, Obtener Envío (XML) | el titular del certificado |

Reglas (implementadas en `api/routes/mipyme.py::_resolver_claves` y `core/keystore.py`):

1. **Se piden cuando hacen falta y se dice para qué.** Los endpoints las aceptan en el cuerpo
   (`clave_tributaria`, `clave_certificado`, `rut_usuario`); nunca en la URL ni en argumentos.
2. **Por defecto no se guardan.** La app las mantiene en memoria mientras está abierta.
3. **Se recuerdan solo con `recordar: true`** (la casilla "recordar en este equipo"): entonces se
   cifran en la tabla `claves_sii` del keystore con la **misma clave maestra** (`DTE_MASTER_KEY`)
   que protege el certificado. Quien tenga la base y el `.env` de esa máquina puede
   descifrarlas: es el mismo nivel que el `.p12`, ni más ni menos.
4. Lo que falta en la petición se toma de lo recordado; lo que viene manda. `GET
   /api/v1/keystore/claves-sii/{rut}` dice **qué** hay guardado, nunca los valores;
   `DELETE` las olvida.
5. **Tenerlas no autoriza a gastar folios**: cada emisión real pasa por su confirmación.
6. Nunca a logs ni a evidencias (`_guardar_evidencia` ya tacha claves en todas sus formas).

