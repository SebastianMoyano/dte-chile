# Anular una boleta electrónica — guía de usuario

> **Por qué existe este documento**: el SII tiene esta información **dispersa** entre FAQs,
> guías, alerts de JavaScript y manuales de 2003. Acá está consolidado y **verificado en vivo**
> (2026-07, RUT de la empresa con software propio 77777777-7) para que no haya que reconstruirlo cada vez.

---

## En una frase

**Anular una boleta electrónica = emitir una Nota de Crédito Electrónica (DTE tipo 61) que la
referencia con motivo "anula".** No existe un botón "borrar boleta": se emite *otro* documento
(la NC) que la deja sin efecto. Esto vale para boleta afecta (39) y exenta (41).

> **Base legal (no es interpretación nuestra).** Resolución Ex. SII **N° 74 de 02.07.2020**,
> Resolutivo 1°, letra F, **N° 8**: *"En caso que se requiera **anular una boleta electrónica,
> deberá emitirse una nota de crédito electrónica**."* (El N° 7 exige lo mismo para modificar
> datos del receptor o aplicar descuentos posteriores.)
> Res. 74 completa: `sii.cl/normativa_legislacion/resoluciones/2020/reso74.pdf`

---

## Lo que hay que entender primero: DOS identidades distintas

El enredo que trabó todo esto es que el trámite involucra **dos apps del SII que piden
identidades opuestas**:

| Paso | Con qué identidad se entra | Por qué |
|---|---|---|
| **Declaración de modelo de emisión** | **RUT + Clave de la EMPRESA** (77777777-7) | Es un atributo de la empresa emisora de boletas. Con el certificado de una persona, la app responde *"esta aplicación es solo para usuarios de boletas"* porque lee el RUT personal, que no es emisor. |
| **Emitir la Nota de Crédito** | **RUT + Clave o Certificado de la PERSONA autorizada** (ej. 12345678-5) | La NC la *firma una persona*. La app rechaza el RUT de la empresa con un alert (ver más abajo). |

Meterse con la identidad equivocada en cada paso es lo que produce los mensajes de bloqueo.
El mapa completo de qué identidad exige **cada** trámite del SII está en
[`IDENTIDADES-SII.md`](IDENTIDADES-SII.md).

---

## Requisitos previos

1. **Persona autorizada** por la empresa para emitir el documento, con su Clave Tributaria /
   Clave Única / Certificado Digital. (En el portal del SII → *Mantención de usuarios
   autorizados*, la persona necesita **Firmar** y **Enviar**; opcionalmente **Registro**.)
2. **Datos de la boleta a anular**: tipo (39/41), **folio**, fecha de emisión, RUT del receptor,
   monto y cantidad a anular.
3. **Declaración de modelo de emisión** hecha (paso siguiente). Especialmente si recibes pagos
   con tarjeta: el SII exige declarar si emites boleta electrónica en esos casos.

---

## Procedimiento (portal MIPYME — la vía que NO cuesta el gratuito)

> ⚠️ **Importante**: hacer la NC **por el portal MIPYME del SII** es lo correcto. Emitir la NC
> **desde el motor propio** te convierte en "facturador de mercado" y **pierdes el MiPyme
> gratuito de facturas** (FAQ SII 6568 + proveedores certificados). Ver el final del documento.

### Paso 1 — Declarar el modelo de emisión (como EMPRESA)

- URL: **`https://www4.sii.cl/actatributointernetui/#!/inicio`**
- Entra con el **RUT de la empresa + su Clave Tributaria de empresa**.
- Informa si emites boleta electrónica cuando recibes pagos electrónicos (tarjetas). Es rápido
  y suele ser el requisito que el sistema pide antes de habilitar la emisión de NC.

### Paso 2 — Emitir la NC (como PERSONA, en sesión limpia)

1. **Cierra sesión** completamente en el SII primero (para que no quede pegada una sesión de la
   empresa o del certificado — es la causa más común de que rebote).
2. Entra a **`https://www1.sii.cl/cgi-bin/Portal001/mipeSelEmpresaBol.cgi`**
   (menú: *Servicios online → Boleta de ventas y servicios electrónica → Emitir nota de crédito
   electrónica*).
3. Autentícate con la **Clave Única o RUT + Clave Tributaria de la persona autorizada**.
   👉 Esa página usa el **login nuevo** del SII; el certificado por el flujo antiguo la rebota.
4. En **"Selección de empresa"**, elige la empresa emisora de la boleta (aparecen las empresas
   que te registraron como usuario autorizado).
5. Busca/selecciona la boleta por tipo + folio + fecha + RUT.
6. Motivo: **anulación** (ver códigos abajo). Completa, valida, **firma** y confirma.
7. Verifica el mensaje de éxito e imprime desde "ver documento".

---

## Los códigos que definen la anulación (parte técnica)

Toda NC lleva un bloque **Referencia** que apunta a la boleta. Los campos y códigos (formato DTE
del SII; idénticos en nuestro motor `core/dte.py` y en la librería de referencia
[dansanti/facturacion_electronica](https://gitlab.com/dansanti/facturacion_electronica)):

| Campo | Qué es | Valor para anular una boleta |
|---|---|---|
| `TpoDocRef` | Tipo del documento referenciado | **39** (boleta) o **41** (boleta exenta) |
| `FolioRef` | Folio de la boleta | el folio a anular (ej. `6`) |
| `FchRef` | Fecha de la boleta | fecha de emisión de la boleta |
| `CodRef` | **Motivo de la referencia** | **1 = Anula documento** |
| `RazonRef` | Texto libre del motivo | ej. `"Anula boleta"` (máx. 90 caracteres) |

**Los tres `CodRef` posibles** (útil para otros casos, no solo anular):

| `CodRef` | Significado | Cuándo se usa |
|---|---|---|
| **1** | **Anula** documento de referencia | dejar la boleta totalmente sin efecto |
| **2** | Corrige **texto** | arreglar datos (glosa, RUT) sin cambiar montos |
| **3** | Corrige **montos** | rebajar/ajustar el monto (nota de crédito parcial) |

Para una NC de anulación, la NC repite los montos de la boleta original con `CodRef=1`.

---

## Mensajes de error del SII y qué significan de verdad

- **Alert al entrar a la NC**: *"…no es posible hacerlo con el RUT y Clave de la empresa…
  ingrese con la persona autorizada…"* y te devuelve al login.
  → Es un **guard genérico**. Te nombra a ti aunque estés logueado. Causas reales: (a) entraste
  con el RUT de la **empresa** en vez de la persona; (b) quedó **pegada una sesión anterior**
  (cierra todo y reintenta limpio); (c) si (a) y (b) están descartados y falla en más de una
  empresa, es una **especificidad de la opción MIPYME del lado del SII** (ver "Si aun así te
  rebota") → Mesa de Ayuda. NO es la *declaración de modelo de emisión* (no está en la Res. 74)
  ni "falta inscribir al firmante" (la persona ya emite documentos, luego ya es firmante).
- **"Esta aplicación es solo para usuarios de boletas de ventas y servicios electrónicas"**
  (en *Declaración de modelo de emisión*).
  → Entraste con el **certificado de la persona** (lee su RUT personal, que no es emisor).
  Entra con el **RUT de la empresa**.

---

## Si aun así te rebota

⚠️ **Verificado en vivo (2026-07): este bloqueo se reproduce en DOS empresas distintas con la
misma persona** — una con software propio (la empresa con software propio) y otra que usa el sistema gratuito del
SII (la empresa del gratuito). Falla idéntico en ambas, sin importar cómo se emitió la boleta. **Eso descarta que
sea por el software propio, por nuestro motor, o por el setup de una empresa puntual.** El común
denominador es la **persona que inicia sesión**: el SII no la reconoce como autorizada para
*esa* opción MIPYME.

👉 Es un **registro/identidad del lado del SII**. No lo resuelve ni un permiso ni el código.

**Descartado (verificado 2026-07): NO es "falta inscribir al firmante".** Se rastreó el portal
MIPYME (`Portal001`) y el registro de firmantes es el mismo "Administración de usuarios
autorizados" (`eu_enrola_usuarios`), donde *"Firmar Documentos" = firmante* (Res. 74, def. de
signatario) — y la persona ya lo tiene. Además, la persona **ya emite boletas/facturas** en esas
empresas, lo que **prueba** que es firmante (si no, no podría emitir). El bloqueo es una
**especificidad de la opción "Emitir NC de boletas" de MIPYME**, no un registro faltante. (El
portal `Portal001` exige el login nuevo —Clave Única/Tributaria vía `AUT2000`—; la sesión por
certificado del motor no lo cruza, así que este paso no es automatizable.)

📞 **Mesa de Ayuda SII: (2) 2395 1115** — es el número que el propio alert del SII entrega. Pídeles
qué registro falta para quedar habilitado como **firmante/usuario autorizado para emitir NC de
boletas** en MIPYME.

---

## Lo que NO conviene: emitir la NC desde el motor propio

Tentador, pero tiene dos costos:

1. **Pierdes el MiPyme gratuito de facturas.** Anular boletas con NC de motor propio te
   reclasifica como *facturador de mercado* (FAQ SII 6568; blog SuperFactura). Ver
   [`CERTIFICACION.md`](CERTIFICACION.md).
2. **Puede estar bloqueado igual.** El timbraje de tipo 61 (NC) por software propio requiere
   folios CAF, y hoy puede estar frenado por la **Verificación de Actividades** pendiente
   (`ST-SEG-DTE-21-3`).

La NC **por el portal MIPYME** evita ambos: el SII pone los folios y no toca tu condición de
usuario gratuito.

---

## Enlaces del SII, consolidados (porque están dispersos)

| Para qué | URL |
|---|---|
| Emitir NC de anulación de boletas | `https://www1.sii.cl/cgi-bin/Portal001/mipeSelEmpresaBol.cgi` |
| Declaración de modelo de emisión | `https://www4.sii.cl/actatributointernetui/#!/inicio` |
| Consultar validez de una boleta | `https://www4.sii.cl/bolcoreinternetui/#!/home` |
| Consultar contenido de una boleta | `https://www2.sii.cl/bolcore/` |
| Mantención de usuarios autorizados (permisos) | `https://palena.sii.cl/cvc_cgi/dte/eu_enrola_usuarios` |
| Menú boleta electrónica (índice) | `https://www.sii.cl/servicios_online/1039-.html` |

---

## Fuentes

- **Verificación en vivo** contra el SII (2026-07, la empresa con software propio): autorización de tipos vía
  `ee_empresa_rut`, asociación MIPYME vía `mipeSelEmpresa.cgi`, alert real de
  `mipeSelEmpresaBol.cgi`. Ver [`LECCIONES-SII.md`](LECCIONES-SII.md).
- **Resolución Ex. SII N° 74 de 02.07.2020** (rige la boleta electrónica): la anulación por NC
  está en el Resolutivo 1° letra F N°8; el RVD diario en la letra E/I (⚠️ luego relajado por
  Res. 53/2022); la certificación previa del software propio en la letra C.
- **FAQ SII** boletas 6568 (boleta independiente del gratuito) y 001_380_7804.
- **Blog Nubox**: "Cómo hacer nota de crédito para boleta electrónica".
- **[dansanti/facturacion_electronica](https://gitlab.com/dansanti/facturacion_electronica)**
  (Daniel Santibáñez, GPLv3) — librería chilena de referencia para los códigos de referencia y
  tipos de DTE.
