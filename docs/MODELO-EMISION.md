# Modelo de emisión de boletas y medios de pago — guía de usuario

> **Por qué existe este documento**: desde 2021 el voucher de la tarjeta *vale como boleta*, y
> el SII pide declarar cómo operas ("modelo de emisión"). La información oficial está dispersa
> (app del SII, resoluciones, ayuda de Haulmer/TUU). Acá está consolidada y aterrizada a **este
> motor**. Complementa [`ANULAR-BOLETA.md`](ANULAR-BOLETA.md).

---

## La idea en una frase

Cuando un cliente paga con **tarjeta o app de pago**, el **voucher de ese pago ya vale como
boleta** (Ley + Res. Ex. SII 176/2020). Si además emites TU boleta por la misma venta, la venta
queda **contada dos veces** (doble débito de IVA) y tendrías que emitir una **Nota de Crédito**
por cada duplicado. La **Declaración de modelo de emisión** le dice al SII de antemano cómo
operas, para que cuente cada venta **una sola vez**.

- **Dónde se declara**: `https://www4.sii.cl/actatributointernetui/#!/inicio`
  (menú *Boleta de ventas y servicios electrónica → Declaración de modelo de emisión*).
- **Con qué identidad**: **RUT + Clave de la EMPRESA** (no la persona — con clave/certificado
  personal la app responde *"solo para usuarios de boletas"*).
- Se declara **por empresa**, y debe reflejar la operación real de **todos** sus locales.

---

## Las dos modalidades, decodificadas

| | **Modelo 1 — "Siempre emito boleta, aún con pago electrónico"** | **Modelo 2 — "No emito boleta cuando recibo pago electrónico"** |
|---|---|---|
| ¿Quién es "la boleta" en ventas con tarjeta? | **Tu boleta** (el voucher queda solo como comprobante de pago) | **El voucher** (lleva la glosa *"válido como boleta"*) |
| ¿Quién informa la venta al SII? | Tu sistema (la boleta que emites) | El **operador de pago** (Transbank/Haulmer/MP…) informa los vouchers |
| Trabajo mensual extra | **Ninguno** | Debes ingresar al Registro de Ventas los **totales de vouchers, código 48** (Res. 176/2020 + Res. 9, 23 y 76 de 2021) — salvo que tu proveedor lo automatice |
| Ventas en efectivo o **transferencia** | Boleta tuya, como siempre | **Boleta tuya igual** — ⚠️ la transferencia NO cuenta como "pago electrónico" |
| Para quién tiene sentido | Quien tiene **software emisor propio** (este motor) | Quien usa la **máquina del proveedor de pago como único sistema** (el POS lo hace todo) |

### Para usuarios de ESTE motor: **Modelo 1**

Este programa **emite una boleta por cada venta** — ese es su propósito. Y aplica igual si el
cobro es **online** (link de pago, suscripción de Mercado Pago, etc.): el operador reporta sus
comprobantes al SII lo mismo que un POS físico, así que la regla no cambia — tu boleta es el
documento, el comprobante del operador es solo el pago. Por lo tanto:

- Declara **Modelo 1** ("siempre emito boleta").
- El medio de cobro (Mercado Pago, Transbank, etc.) queda como **solo cobro**; la boleta la
  pone el motor.
- No tienes reporte manual de código 48, y el Registro de Compras y Ventas del SII se arma
  con tus boletas.
- ⚠️ Verifica que tu proveedor de cobro **no emita también boleta** por su lado (algunos POS
  lo hacen por defecto) — si ambos emiten, duplicas el IVA y vuelves al problema de las NC.

### ⚠️ El Modelo 2 escala mal: la tienda con varios POS de marcas distintas

El voucher-boleta funciona bien con **una** máquina. Pero un comercio con 2–3 POS de marcas
distintas (Transbank + Getnet + MP, común en Chile) queda con **cada operador informando sus
vouchers por separado**: el Registro de Ventas se arma con varias fuentes que no se hablan,
conciliar la caja exige revisar cada panel, y una devolución en una máquina no la ve la otra.
(La ayuda de TUU lo confirma: *"el envío de comprobantes que realice cada proveedor se añadirá
a los montos diarios del resumen correspondiente"*.) Con **Modelo 1 + un sistema emisor único**
(este motor), todas las máquinas son solo cobro y la fuente de verdad es una — da lo mismo
cuántos POS haya ni de qué marca.

### El caso típico del Modelo 2: un café con máquina TUU/Haulmer

Un café que usa la máquina del proveedor **como único sistema**: en ventas con tarjeta la
máquina no emite boleta (el voucher hace de boleta y el proveedor lo informa al SII); en
efectivo/transferencia sí emite boleta; el cierre mensual (código 48) lo automatiza la
plataforma del proveedor. Por eso "sale todo solo": **un solo sistema emite y declara**. El
modelo 2 es coherente solo dentro de ese mundo cerrado.

Datos verificados en la doc de TUU/Haulmer (2026-07):

- **TUU no recomienda un modelo**: presenta ambos y pide que el usuario declare primero en el
  SII y luego **replique** esa declaración en el espacio de trabajo, porque la máquina decide
  emitir boleta o solo voucher según "modelo declarado + tipo de documento + forma de pago".
- ⚠️ **Si NO declaras nada, el SII asume el Modelo 2 por defecto** (FAQ de TUU: *"En caso de
  que no se declare ningún modelo a utilizar, el SII considerará la segunda opción por
  defecto"*). O sea: un emisor con software propio que nunca declaró está, ante el SII, en el
  modelo contrario al que opera → **declara el Modelo 1 explícitamente**.
- **Folios**: TUU los timbra y administra automáticamente (carga manual del CAF solo como
  contingencia). Su ayuda **no documenta** la convivencia con otro software emisor — refuerza
  la regla de rangos separados de más abajo.

---

## ⚠️ Dos sistemas emisores = problemas (léelo si migras o convives)

Si una empresa tiene **dos** sistemas capaces de emitir boletas (ej. la máquina del proveedor
Y este motor):

1. **Doble conteo**: si ambos emiten por la misma venta, el IVA se duplica y hay que emitir NC.
2. **Colisión de folios**: **ningún sistema detecta que otro consumió un folio**. Cada sistema
   lleva su propio contador sobre el CAF que tiene cargado. Si ambos usan el mismo rango,
   emitirán folios repetidos y el SII rechazará.

Reglas prácticas:
- Lo más limpio: **un solo sistema emisor por empresa**.
- Si deben convivir (ej. migración gradual): **rangos de folios separados** — cada sistema con
  su propio CAF, sin traslape. Los CAF se solicitan por rango en el SII (este motor lo hace
  con `solicitar_folios` / gestión automática de folios).
- La **declaración de modelo de emisión debe calzar con quién emite**: si el motor emite todo,
  Modelo 1; si el POS del proveedor es la boleta en tarjeta, Modelo 2 (y que el proveedor
  cargue el código 48).

---

## Cómo hacer la declaración, paso a paso (pantallas reales, 2026-07)

1. **Entra a** `https://www4.sii.cl/actatributointernetui/#!/inicio` **con el RUT + Clave
   Tributaria de la EMPRESA** (no la tuya — con clave o certificado personal la app te
   rechaza con *"esta aplicación es solo para usuarios de boletas"*).
2. Primera pantalla — te pregunta si el trámite te aplica:
   > *"La siguiente aplicación está orientada para los comercios que reciben pagos
   > electrónicos por medio de tarjetas de crédito o débito (u otro medio electrónico)…
   > Favor continuar, si recibe estos pagos. En caso contrario, seleccionar salir."*
   - ¿Recibes pagos con tarjeta o app de pago (Transbank, Mercado Pago, etc.)? → **Continuar**.
   - ¿Solo efectivo y transferencias? → **Salir** (no te aplica; recuerda que la
     transferencia NO es "pago electrónico").
3. Pantalla **"Declaración del modelo de emisión"** — muestra la identificación de la
   sociedad y pide elegir la **Forma de Emisión** entre estas opciones (texto real):
   - **"Siempre emito Boleta de Ventas y Servicios Electrónica aún cuando reciba un pago
     electrónico"** → **Modelo 1**. *Esta es la correcta si emites con este motor.*
   - **"No emito Boleta de Ventas y Servicios cuando recibo un pago electrónico"** →
     Modelo 2 (el voucher es la boleta; solo emites boleta para efectivo/transferencia).
   - *"En casos particulares, emito boleta electrónica pero no es la generalidad de mi
     operación"* → variante minoritaria; evítala salvo que describa exactamente tu caso.
4. Confirma y guarda. **Repite por cada empresa** que opere con boletas (la declaración es
   por RUT).
5. Si además usas un POS de un proveedor (TUU, etc.), **replica la elección en la
   plataforma del proveedor** — el SII no se la comunica, y la máquina decide si emite
   boleta o solo voucher según lo que le digas.

---

## ¿Puede este motor tener SU propia máquina? (POS e integración)

Investigado 2026-07. Resumen: **sí se puede, y la vía más concreta hoy es la máquina TUU.**

### Máquina TUU/Haulmer — la más abierta (verificado en `developers.tuu.cl`)

El POS de TUU corre Android (hardware **Sunmi o Kozen**) y tiene un ecosistema de
desarrolladores real, con tres vías de integración:

1. **Pago remoto (API REST)**: tu sistema (este motor) dispara el cobro en el terminal por
   webservice — mandas el monto con el serial del POS (`device`) y una `X-API-Key`, el
   terminal en "modo integración" cobra, y recibes el resultado. **No requiere app en la
   máquina**: el motor podría cobrar con TUU y emitir su propia boleta hoy mismo.
   (`developers.tuu.cl/docs/pago-remoto`)
2. **App propia EN el POS (inter-app)**: tu app Android corre en la máquina e invoca la app
   TUU Negocio vía **Intent** con un JSON (`paymentData`); el parámetro `printVoucherOnApp`
   decide quién imprime el voucher (TUU o tu app).
   (`developers.tuu.cl/docs/integración-de-aplicaciones-de-pago-inter-app-new`)
3. **App Store del POS**: registrándote como partner puedes **publicar tu app** en la tienda
   del terminal (pública o privada; en POS PRO2 exigen apps firmadas).
   (`developers.tuu.cl/docs/proceso-de-publicación-de-aplicaciones`)

Límites documentados: máx. **3 dispositivos en modo desarrollador** por integración, y el paso
de un dispositivo a modo desarrollador es **irreversible**. Además Haulmer expone la emisión de
DTE por API (OpenFactura) y anuncia un "SDK inter-app de facturación" como *próximamente* —
pero eso a nosotros no nos hace falta: **la boleta la emite este motor**; de TUU solo
necesitaríamos el cobro.

**Arquitectura sugerida si se quisiera "máquina TUU + este motor":** app propia (o pago remoto)
para cobrar → al aprobarse el pago, llamar a la API del motor (`/api/v1/...` o MCP) para emitir
la boleta → declarar **Modelo 1**. Un solo emisor (el motor), TUU solo como adquirente.

### Mercado Pago Point — integrable por API, pero SIN apps propias en la máquina

Verificado en la doc oficial chilena (`mercadopago.cl/developers`, 2026-07):

- **Integración oficial "modo PDV"**: tu sistema crea la orden por API
  (`POST /v1/orders` con `type: "point"` y el `terminal_id`), el terminal la carga y cobra,
  y recibes el resultado por **webhook**. Requiere pasar el terminal de `STANDALONE` a `PDV`
  (una caja por terminal). Modelos integrables en Chile: **Point Smart (PAX A910) y Point
  Smart 2 (Newland N950)**; el Point Mini NO se integra (solo standalone).
- **Printing API (2025)**: permite **imprimir DTE propios en la impresora del Point** — o sea,
  el motor emite la boleta y la imprime en la máquina de MP.
- **NO se pueden instalar apps de terceros** en el terminal: todo es desde fuera, por API.
- Ojo comercial: MP vende su propio servicio de boletas (~$11.000+IVA/mes tras 6 meses
  gratis) y, sin contratarlo, su voucher opera como boleta bajo el **Modelo 2**. Si el motor
  emite, hay que declarar **Modelo 1** y no contratar ese servicio (sería un segundo emisor).
- Combo posible: orden por API → Point cobra → webhook → el motor emite la boleta →
  **Printing API la imprime en el mismo Point**.

### Transbank — la única vía documentada para una app propia EN el terminal

- **POS Integrado**: SDKs oficiales open-source (.NET, Java, Node, Python) para manejar el
  POS desde una caja/PC por serial/USB (`transbankdevelopers.cl/documentacion/posintegrado`).
- **SmartPOS**: existió doc pública de un **SDK Android** (.aar) para apps "de valor agregado"
  corriendo EN el POS (PAX A920) que invocan la app Transbank Pagos (venta, anulación, cierre,
  impresión, escáner). Exige **certificación** y distribución por **PAXSTORE** con lista
  blanca. ⚠️ La doc pública fue retirada del sitio (hoy redirige al home; consultable en
  Wayback) → el canal se gestiona en privado, requiere contacto comercial con Transbank.

### Resto del mercado (resumen)

| Proveedor | Integración por API | App propia en la máquina |
|---|---|---|
| **TUU/Haulmer** | ✅ Pago remoto (REST) | ✅ Inter-app + App Store del POS (partner) |
| **Mercado Pago** | ✅ Orders API modo PDV + Printing API | ❌ |
| **Transbank** | ✅ POS Integrado (SDKs abiertos) | ⚠️ SmartPOS SDK con certificación (canal privado) |
| **Getnet** | "POS Integrado" (integradores como Bsale ya lo usan) | no documentado |
| **Klap / SumUp** | parcial/no confirmado en Chile | ❌ |

**Conclusión para este motor**: las dos rutas concretas hoy son **TUU** (la más abierta: API
de cobro + app propia en el POS + tienda de apps) y **Mercado Pago Point** (API + impresión
del DTE propio en su impresora, sin app). En ambas la arquitectura es la misma: **la máquina
solo cobra; la boleta la emite este motor** (→ declarar Modelo 1, un solo emisor, sin
colisión de folios).

---

## Fuentes

- **Res. Ex. SII N° 176/2020** (+ complementarias 9, 23 y 76 de 2021): voucher válido como
  boleta; obligación del código 48 en el Registro de Ventas para el Modelo 2.
  `sii.cl/normativa_legislacion/resoluciones/2020/reso176.pdf`
- **App del SII**: Declaración de modelo de emisión (`actatributointernetui`), texto verificado
  en vivo (2026-07).
- **Ayuda Haulmer/TUU**: "¿Por qué se debe informar a Haulmer el modelo de emisión?" y
  "Declarar modelo de emisión en el espacio de trabajo" (`help.tuu.cl`) — confirma la mecánica
  del Modelo 2 y el código 48, y que la declaración del SII **no** se reemplaza por la del
  proveedor.
