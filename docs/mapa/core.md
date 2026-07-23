# Mapa — `core/` (lógica de negocio)

> Hoja del [`MAPA.md`](../MAPA.md). 34 módulos + `__init__`, ~7.400 líneas. Las reglas están en
> [`CONSTITUCION.md`](../CONSTITUCION.md); el porqué, en [`LECCIONES-SII.md`](../LECCIONES-SII.md).

## Grafo (simplificado)

```
config.py ── database.py ── models.py ── auth.py ──► apikeys.py    errors.py (hoja, 20 importadores)
                    └── keystore.py ──┐                            xml_seguro.py (hoja)
                                      ▼
                                  crypto.py  ◄── 24 importadores (el más acoplado)
                                      ▲
                                  sobre.py  ◄── orchestrator.py ──► dte.py, pdf_gen.py, caf.py
                                                     ▲ (herencia)          resolucion.py
                                              orchestrator_boleta.py ──► boleta.py, sii_boleta.py
                                              preview.py

reintentos.py (hoja) ◄── sii.py, sii_boleta.py, sii_portal.py
                              ▲            ▲              ▲
                       seguimiento.py   orchestrator_boleta.py  onboarding.py, negocios.py, folios_auto.py
                              rcv.py ──► rut.py
rvd.py ◄── scheduler.py ──► negocios.py, keystore.py
main.py ──► folios_auto.py (bucle asyncio in-process, sin cron)
```

## Los 8 invariantes más caros (ordenados por coste)

| # | Dónde | Qué |
|---|---|---|
| 1 | `crypto.py:379-383` | **`_c14n_reparse`, nunca substring.** Substring no redeclara los ns heredados en el ápice → el SII recomputa otro digest → RFR / `DTE-3-505`. |
| 2 | `sobre.py:9-16` | **Firmar STANDALONE + armar por STRING.** Firmar embebido o re-serializar → `DTE-3-505`. Verificado: TrackID 253113960 → `ACEPTADOS: 1`. |
| 3 | `sii_boleta.py:65-68` | **`EPR` ≠ aceptado.** *"tuvo al proyecto creyendo que la certificación pasaba mientras el SII rechazaba TODO"*. |
| 4 | `sii_boleta.py:9-18` | **Hosts asimétricos**: envío a `pangal`/`rahue`, no a `apicert`/`api`. "El error que más tiempo cuesta". |
| 5 | `caf.py:201-206` | **El FRMT del TED se firma en ISO-8859-1, NO en UTF-8.** Con acentos los bytes difieren → `TED-2-510`. |
| 6 | `config.py:44-48`, `:131-138` | **Resolución de certificación ≠ producción** → `CRT-3-19`. Usar `settings.resolucion`. |
| 7 | `sii.py:313-316`, `sii_boleta.py:73-75` | **User-Agent de navegador obligatorio.** Sin él el SII responde HTML genérico / `401` — **mensajes que mienten**. |
| 8 | `dte.py:34-43` | **Redondeo half-up, no banker's**: `round()` de Python da diferencias de $1 que el SII rechaza. |

## Por capa

### Infraestructura
- **`config.py`** — singleton `settings`. **`settings.resolucion`** → `(fecha, num)` del ambiente
  activo. `problemas_seguridad()` (lo usa `main.py` para abortar en producción), `es_produccion`.
- **`database.py`** — SQLite (WAL, FK on) + `SCHEMA_SQL`. Tablas: `dtes`, `cafs`, `audit_log`,
  `usuarios`, `rvd_envios`. El `UNIQUE(rut,fecha,sec_envio)` es lo que hace idempotente al scheduler.
- **`models.py`** — CRUD. ⚠️ **`consumir_siguiente_folio` usa `BEGIN IMMEDIATE`** (anti-TOCTOU,
  `:253-259`), con conexión propia y reintento ante `database is locked`. **No dupliques esto.**
- **`errors.py`** — jerarquía tipada. `codigo` = **contrato estable**. `SIIError` (falló la
  comunicación) ≠ `SIIRechazoError` (el SII respondió y rechazó). Nunca secretos en `detalle`.
- **`keystore.py`** — `.p12` + password **cifrados (Fernet)**. `pem_transitorio()` escribe con
  `0o600` y **borra al salir**. ⚠️ Sin `DTE_MASTER_KEY` la clave se deriva del JWT ⇒ **rotar el
  JWT deja el keystore ilegible** (de ahí `rotar_claves.py`).
- **`auth.py`** — JWT. ⚠️ Usa **`sha256_crypt` a propósito, no bcrypt** (incompatibilidad
  passlib/bcrypt). No lo "arregles" sin verificar. `requerir_autenticacion` acepta también
  **API key** (cae a `apikeys.py` si el bearer no es un JWT válido).
- **`apikeys.py`** — llaves `dte_...` para integraciones/agentes. Solo se muestra el secreto al
  crearla; en BD se guarda el **hash SHA-256**. Crear/listar/revocar exige JWT (una key no puede
  crear más keys) — `api/routes/apikeys.py` + `static/apikeys.html`.
- **`resolucion.py`** — `resolucion_emisor(rut)`: la `(fecha, número)` de la carátula es **por
  empresa**, no global. Cachea el registro público del SII (memoria + BD) y cae a
  `settings.resolucion` si la consulta falla. Corrige el `CRT-3-19` que le pegó a SOFTWARE
  DEMO SPA cuando usaba el default de EMPRESA DEMO SPA.
- **`reintentos.py`** — `ClienteReintentos`: reintenta solo `{429,502,503,504}` + errores de red,
  full jitter, respeta `Retry-After`. Reintentar POST es seguro *"porque el SII es idempotente por
  folio"*.
- **`xml_seguro.py`** — `parse_seguro()` anti-XXE. *"Úsalo para TODO XML que no hayamos generado."*

### Firma (el corazón)
- **`crypto.py`** (24 importadores) — `CertificadoDigital` + **dos** firmas que NO son
  intercambiables:

  | | `firmar_documento_xml` | `firmar_xml_sii` |
  |---|---|---|
  | uso correcto | **SOLO la semilla del `getToken`** | DTE, sobre, ConsumoFolios |
  | SignedInfo | standalone, antes de inyectar | en su posición final |
  | C14N | `canonicalizar_elemento` | **`_c14n_reparse`** |

  ⚠️ `crypto.py:432-436`: envolver a 64 chars **solo** el base64 de KeyInfo (`CHR-00002: Line too
  long`); **NO** la `SignatureValue` (metía saltos dentro del SetDTE y descuadraba el sobre).

- **`sobre.py`** ⭐ — **la única forma que el SII acepta**. `firmar_documento_standalone()` +
  `armar_sobre_firmado()`. Lo usan `orchestrator`, `orchestrator_boleta`, `preview` y
  `api/routes/dte.py`. ⚠️ Parsea el `str`, **no** bytes ISO-8859-1 (si no, lxml asume UTF-8 y
  revienta con "Morandé").

- **`caf.py`** — parsea el CAF y genera el **TED**. ⚠️ El TED se firma con **la clave del CAF**
  (`<RSASK>`), **no** con el certificado del contribuyente. El FRMT va sobre el DD
  **canonicalizado + aplanado + en ISO-8859-1**.

### Generación de XML
- **`dte.py`** — modelos Pydantic, `TipoDTE`, `calcular_totales`, `GeneradorDTE`. Cementerio de
  bugs XSD documentados: `TipoDTE` vs `TpoDTE` (`:351-355`), `SubTotDTE` va **dentro** de la
  Carátula (`:362-365`), orden `QtyItem`→`UnmdItem`→`PrcItem` (`:441-447`), `xsi:schemaLocation`
  **obligatorio** (`:320`), **declaración XML con comillas dobles** o el SII rechaza (`:502-504`).
- **`boleta.py`** — el `<DTE>` de boleta. `IndServicio` obligatorio, **sin** `FmaPago`;
  `RznSocEmisor`/`GiroEmisor`.
- **`schema_validator.py`** — valida contra `core/xsd/`. ⚠️ Un `<DTE>` de boleta suelto se
  validaría contra el esquema de **factura**: valida el **sobre**.
- **`pdf_gen.py`** — PDF carta + `generar_boleta_80mm` (térmico). ⚠️ Sin `pdf417gen` genera el PDF
  **sin timbre, en silencio** (`:73`) — un DTE impreso sin PDF417 no es válido.
- **`rvd.py`** — `ConsumoFolios` diario. Genera, firma, valida y **envía** (`enviar_rvd`) por
  `DTEUpload`/SOAP — el mismo canal de facturas, no un REST aparte. **No es obligatorio en
  producción** desde 2022-08-01 (Res. Ex. SII 53/2022; el propio SII lo confirma con el reparo
  "RVD no es obligatorio desde 2022-08-01"); correcciones de ventas van por Nota de Crédito
  (tipo 61). `agrupar_rangos` cubre los 2 bugs de LibreDTE (lista vacía, duplicados).

### Orquestación
- **`orchestrator.py`** — `emitir_dte` (facturas) + **`emitir_documento`** ← *el punto de entrada
  que deben usar API y MCP* (rutea 39/41). `_preparar_emision` es lo compartido con boletas.
  ⚠️ Fallback hardcodeado a `firma.pfx` (ruta configurable vía `DTE_CERT_PATH`) / `"12345678"`
  (`:78-84`): cómodo en dev, peligroso en producción.
- **`orchestrator_boleta.py`** — hereda de `OrquestadorDTE`. Valida XSD antes de tocar disco (el de
  facturas **no**). Emite 1 boleta por sobre (el XSD permite **500**).
- **`preview.py`** — pre-vuelo sin enviar ni consumir folio. Firma por `sobre.py` (igual que la
  emisión real) — si no, mentiría.

### Transporte
- **`sii.py`** — SOAP de **facturas** (maullin/palena). Token cacheado 50 min. Rechaza 39/41.
  ⚠️ `consultar_estado_track` **solo da conteos, sin código de error**: el detalle llega por correo.
- **`sii_boleta.py`** — REST de boletas. Hosts asimétricos, token propio, respuesta **JSON**,
  `MAX_BOLETAS_POR_ENVIO=500`.
- **`sii_portal.py`** — scraping por **mutual-TLS** del portal de timbraje. Guardrail
  `max_folios_por_tipo` (anti-acaparamiento). ⚠️ `listar_anulables` *"es optimista"*; anular exige
  la sesión **del mandatario que timbró**.
- **`seguimiento.py`** — lote de TrackIDs. *"consulta 1 vez por TrackID — el SII puede
  rate-limitear"*. Solo facturas.
- **`rcv.py`** (735 líneas, el más grande) — RCV + agregación **F29**. **Aditivo**: tabla propia,
  no toca `dtes`/`cafs`. JSON en **UTF-8** (no ISO-8859-1). Solo hay datos en **producción**.

### Operación
- **`scheduler.py`** — RVD diario **in-process** (sin cron: portable a Windows/Mac/Linux).
  Zona horaria de **Chile** (⚠️ Windows necesita `tzdata`), **catch-up** de 7 días, idempotente,
  y *"el bucle NUNCA debe morir"*. Envía por `rvd.py::enviar_rvd` (`DTEUpload`/SOAP); el RVD
  ya no es obligatorio en producción (Res. Ex. SII 53/2022), pero el scheduler lo sigue enviando.
- **`folios_auto.py`** — reposición automática de folios (reemplazó a `alertas.py`, borrado): si
  el stock de un `(rut, tipo)` cae bajo el umbral, pide un CAF nuevo al SII sola, lo verifica y
  carga; notifica por webhook genérico, nunca por correo. Respeta cooldown y el `CAF-3-517`
  (anti-acaparamiento): si el SII responde bloqueado, avisa "requiere humano" en vez de reintentar.
- **`monitoreo.py`** — salud de CAF **100% local**. Regla `CAF-3-517` = 6 meses. ⚠️ Refleja el
  estado **local**: si se emitió fuera del programa, el consumo real puede ser mayor.
- **`onboarding.py`** — diagnóstico **solo lectura** + plan. Acciones con `modo`:
  `auto` / `consentimiento` / `humano`.
- **`negocios.py`** — empresas por cuenta. ⚠️ El SII **no expone listado inverso** cert→empresas;
  el alta es por RUT con auto-relleno.

## ⚠️ Deuda conocida (auditada 2026-07-16)

| Sev | Qué | Dónde |
|:-:|---|---|
| 🟠 | **`libro.py` es código muerto** (0 importadores) pero guarda las lecciones `CHR-00002` (línea >4090 bytes) y `LBR-3` (montos obligatorios aunque sean 0). **No borrar sin rescatarlas.** | `libro.py:15-29` |
| 🟠 | `sii.py` lanza `ValueError` crudo en vez de `SIIError`/`SIIRechazoError`, pese a importar `errors`. | `sii.py:184,262,343,353` |
| 🟡 | `sii.py`/`sii_boleta.py` parsean respuestas del SII con `etree.fromstring` **sin `parse_seguro`**, violando la regla del propio `xml_seguro.py`. | `sii.py:162,242,341` |
| 🟡 | `_c14n_en_contexto` es muerto interno y su docstring **se contradice** con `firmar_xml_sii`. | `crypto.py:288-295` |
| 🟡 | Comentarios obsoletos en `boleta.py`: menciona `BOLUpload` (pista falsa) y el `uri="#DTE-…"` viejo. | `boleta.py:8,48-49` |
| 🟡 | `CLAUDE.md` dice *"certs nunca a disco"*; `keystore.py:11-13` los persiste **cifrados**. Manda el código. | doc vs código |
| 🔵 | `orchestrator.py` no valida XSD (el de boletas sí). | — |
| 🔵 | `pdf_gen.py:77` reimplementa `formatear_rut` en vez de usar `rut.py`. | — |

**Arreglados hoy** (los detectó esta misma auditoría): `preview.py` firmaba embebido —
reproducía el `DTE-3-505` que `sobre.py` elimina— y `api/routes/dte.py:144` firmaba un DTE con
`firmar_documento_xml` (la función de la semilla). Ambos ya usan `core/sobre.py`.

**Resuelto desde la auditoría** (2026-07-22): el ítem "`sii_boleta.py` NO está cableado" ya no
aplica — lo usa `orchestrator_boleta.py`, las boletas se envían, y SOFTWARE DEMO SPA
(78111111-2) quedó **autorizada en producción** tras completar la certificación de boletas.
