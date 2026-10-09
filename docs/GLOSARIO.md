# Glosario — el vocabulario tributario en cristiano

> Dos líneas por término, sin jerga. Para el detalle de cada tema, sigue el enlace.

## Las dos vías de emisión

- **SII engine**: la app opera los sistemas del propio SII por la empresa — facturas por el
  portal MIPYME (`docs/MIPYME.md`), boletas por eboleta. El SII pone folio, timbre y firma.
  Es el motor base: sirve para quien no quiere cambiar nada de cómo emite hoy.
- **Motor propio**: software certificado ante el SII, con CAF, timbre y firma nuestros. Es la
  expansión, por familia de documento (el SII exige exclusividad por familia: facturas en una
  vía y boletas en la otra es válido). Ambas vías son gratis para quien las usa; "gratuito" es
  solo el nombre del SII para su sistema, no una diferencia del producto.
- **Canal**: por cuál de las dos vías salió un documento. En la BD, `estado = emitido_mipyme`
  marca el SII engine; el resto es motor propio. Misma tabla, misma pantalla.

## Documentos

- **DTE** (Documento Tributario Electrónico): cualquier documento tributario en XML firmado —
  boletas, facturas, notas, guías. Es el término paraguas.
- **Boleta electrónica (tipo 39)**: la venta al consumidor final, con IVA. La emite el motor
  y se envía al SII en el momento (máx. 1 hora).
- **Boleta exenta (tipo 41)**: igual que la 39 pero por ventas/servicios sin IVA.
- **Factura electrónica (tipo 33)**: venta a otra empresa, con IVA. El comprador la necesita
  para recuperar su crédito fiscal. Requiere certificación previa aparte de las boletas.
- **Factura exenta (tipo 34)**: factura sin IVA.
- **Nota de crédito / NC (tipo 61)**: el documento que **anula o corrige** otro documento
  (incluidas boletas — no existe "borrar una boleta", se anula con una NC →
  [`ANULAR-BOLETA.md`](ANULAR-BOLETA.md)).
- **Nota de débito / ND (tipo 56)**: lo contrario de la NC — aumenta el monto de un
  documento ya emitido (intereses, reajustes).
- **Guía de despacho (tipo 52)**: acompaña el traslado de mercadería; no es venta por sí sola.

## Las piezas de una emisión

- **Folio**: el número correlativo del documento (Boleta N° 6 → folio 6). Cada folio se usa
  **una sola vez**, y los autoriza el SII de antemano.
- **CAF** (Código de Autorización de Folios): archivo XML que el SII te entrega con un
  **rango de folios autorizado** (ej. del 1 al 50) y una clave privada propia. El motor lo
  pide y carga solo (gestión automática de folios).
- **TED** (Timbre Electrónico): el bloque de datos firmado **con la clave del CAF** (no con
  tu certificado) que va dentro del documento y se imprime como código de barras.
- **PDF417**: el tipo de código de barras 2D del timbre que ves en toda boleta impresa.
- **Certificado digital**: tu identidad electrónica (archivo `.p12`/`.pfx` con clave). Es de
  una **persona natural**, no de la empresa, y firma los documentos y los trámites.
- **Firma electrónica (XMLDSig)**: la firma matemática del XML con tu certificado. Si el
  documento cambia una coma después de firmado, la firma se invalida (por eso el motor firma
  de una forma muy precisa → `core/sobre.py`).
- **EnvioDTE / EnvioBOLETA**: el "sobre" XML que agrupa uno o más documentos firmados para
  mandarlos al SII (facturas van en EnvioDTE; boletas en EnvioBOLETA, máx. 500 por sobre).
- **TrackID** ("identificador de envío"): el número que el SII te da al recibir un sobre,
  para consultar su suerte. En boletas tiene 15 dígitos; en facturas, 10.

## Estados y respuestas del SII

- **EPR**: en *boletas* (REST) significa **aceptado**. En *facturas* (SOAP) significa solo
  "envío procesado" — el veredicto real está en los contadores ACEPTADOS/RECHAZADOS.
- **RCT**: rechazado. **RLV/RPR**: aceptado con reparos (llegó, pero con observaciones).
- **Rechazos con código** (`DTE-3-505`, `CRT-3-19`, etc.): cada código tiene su historia y
  su solución → [`LECCIONES-SII.md`](LECCIONES-SII.md) tiene el índice.

## Obligaciones y trámites

- **RVD** (Resumen de Ventas Diarias, ex RCOF): archivo diario con el resumen de boletas del
  día. Obligatorio en certificación; **ya no** en producción (Res. 53/2022).
- **RCV** (Registro de Compras y Ventas): el libro online del SII donde caen todas tus
  ventas/compras informadas. De ahí sale la propuesta del F29.
- **F29**: la declaración mensual de IVA.
- **Voucher / Comprobante de pago electrónico**: el papelito de la tarjeta. Desde 2021
  **puede valer como boleta** según tu modelo de emisión → [`MODELO-EMISION.md`](MODELO-EMISION.md).
- **Código 48**: la línea del RCV donde entran los totales de vouchers cuando el voucher hace
  de boleta (Modelo 2).
- **Modelo de emisión**: tu declaración al SII de si emites boleta en ventas con tarjeta
  (Modelo 1) o dejas que el voucher haga de boleta (Modelo 2) → [`MODELO-EMISION.md`](MODELO-EMISION.md).
- **Certificación**: el examen del SII para autorizar tu software a emitir de verdad — un set
  de casos de prueba que debe salir perfecto → [`CERTIFICACION.md`](CERTIFICACION.md).
- **Declaración de Cumplimiento**: la firma final (del representante legal) que te pasa a
  producción tras aprobar la certificación.

## Personas y accesos

- **Representante legal**: quien firma por la sociedad ante el SII. Único que puede postular
  a certificación y firmar la Declaración de Cumplimiento.
- **Usuario autorizado / firmante (signatario)**: persona natural habilitada por la empresa
  para firmar/enviar documentos. Se administra en "Mantención de usuarios autorizados".
- **Mandatario**: la persona cuyo certificado hizo un trámite (ej. timbró folios). Algunas
  acciones solo puede deshacerlas el mismo mandatario.
- **Clave Tributaria**: la contraseña del SII (la tienen tanto personas como empresas — son
  cuentas distintas). **Clave Única**: la clave del Estado, sirve como login de persona.
- **¿Con qué identidad entro a cada trámite?** → [`IDENTIDADES-SII.md`](IDENTIDADES-SII.md)
  (la fuente de la mayoría de los rebotes inexplicables).

## Infraestructura del SII

- **Maullín** (`maullin.sii.cl`): el SII de **certificación** (pruebas). **Palena**
  (`palena.sii.cl`): el SII de **producción** (documentos reales). Facturas, vía SOAP.
- **apicert/pangal** y **api/rahue**: los servidores REST de **boletas** (certificación y
  producción respectivamente — boletas viven en infraestructura aparte).
- **Portal MIPYME**: el sistema de facturación gratuito del SII (`www1.sii.cl/.../Portal001`).
  Ahí se emite la NC que anula boletas.
- **Mesa de Ayuda SII**: (2) 2395 1115 — para los bloqueos que ningún permiso ni código
  resuelve.
