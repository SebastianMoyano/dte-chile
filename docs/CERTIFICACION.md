# Certificación ante el SII (facturas y boletas)

> Qué significa "certificarse", cómo difiere factura de boleta, y qué NO hace falta.
> Investigado contra fuentes oficiales del SII (2026-07-18). Cada afirmación con su fuente.
> Hoja del [`MAPA.md`](MAPA.md). Reglas operativas en [`CONSTITUCION.md`](CONSTITUCION.md).

## El modelo, en una frase

**El SII autoriza al CONTRIBUYENTE (el RUT), por TIPO DE DOCUMENTO — no certifica software.**
Una vez autorizado para un tipo, el contribuyente **cambia de software libremente sin
re-certificar** (fuente: blog LibreDTE `2024-01-05-sii-certifica-o-autoriza...`). La
"certificación" es el proceso por el que un contribuyente **se hace autorizar para un tipo
que aún no tiene**, demostrando una vez que emite bien con su sistema.

## Dos cosas distintas — no confundirlas

| | **Certificar la EMISIÓN de tu empresa** | **Ser PROVEEDOR autorizado** |
|---|---|---|
| para qué | emitir TUS propias boletas/facturas con software propio | **vender** software a terceros |
| base legal | Res. 74/2020 letras C/D | Res. 74/2020 letra J |
| requisito | pasar el **Set de Prueba** | 10 contribuyentes habilitados + 6 meses + correo |
| **¿lo necesitas tú?** | **SÍ** (para un tipo nuevo) | **NO** — no le vendes a nadie |

**El beneficio real de ser proveedor** (Res. 74 letra C): que **tus CLIENTES quedan eximidos
de certificarse** (solo se inscriben), más aparecer en el
[listado público](https://www.sii.cl/servicios_online/3785-proveedores_autorizados_be.html)
(~60 proveedores: Acepta, Nubox, Bsale, Haulmer/Simple Boleta…). **Para self-emisión:
irrelevante.**

## ⚠️ "Certificación automática": NO existe como concepto oficial

El SII **no la define en ninguna norma.** No está en la Res. 74/2020, ni el instructivo, ni
las FAQ. Es una **frase suelta** en la página de requisitos de proveedores
(`sii.cl/servicios_online/3785-.html`), sin definición — la Res. 74 (letra J) solo dice
"haber habilitado al menos 10 contribuyentes"; el *"por medio de la certificación
automática"* lo agregó la web, no la norma. **No construir ningún plan sobre este concepto.**

## 🟢 Boleta es INDEPENDIENTE de la factura — confirmado por el SII (texto literal)

FAQ oficial `sii.cl/preguntas_frecuentes/bol_electr_vtas_serv/001_380_7804.htm` (2026-07-19):

> *"El Sistema de Emisión de Boletas Electrónicas del SII es **independiente** del Sistema de
> Facturación Gratuito del SII **y** de un software de facturación propio o de mercado."*

**Consecuencia práctica (plano EMISIÓN, ya autorizado):** un contribuyente puede **conservar
MiPyme gratuito para sus FACTURAS** y a la vez **emitir BOLETAS con software propio** — no se
tocan.

⚠️ **Pero el plano CERTIFICACIÓN es otra cosa — verificado en vivo (2026-07-19).** Para bajar
el set de boletas hay que estar **"habilitado en ambiente de certificación y pruebas"**, y NO
existe una habilitación boleta-only: el enlace "Postulación" de la propia guía de boletas
(`sii.cl/servicios_online/1039-postulacion-1184.html`) resuelve a
**`maullin.sii.cl/cvc_cgi/dte/pe_ingrut`** = el MISMO flujo general `pe_condiciones`, el de la
advertencia *"perderá su calidad de usuario activo del Sistema de Facturación SII"*. El
ambiente de cert de boletas usa los mismos cgi `pe_generar`/`pe_avance*` que factura.

🟢 **RESUELTO (2026-07-19, confianza ALTA): certificar SOLO boletas NO cuesta el gratuito de
facturas.** FAQ SII 6568 responde el caso exacto, textual:

> *"Un contribuyente, usuario del Sistema de Facturación Gratuito del SII, puede emitir boletas
> electrónicas, a través de un software propio o adquirido en el mercado, **manteniendo su
> calidad de usuario del Sistema de Facturación Gratuito del SII**."*
> (`sii.cl/preguntas_frecuentes/bol_electr_vtas_serv/001_380_6568.htm`)

La exclusividad del gratuito es **por familia de documento (facturas), no por empresa**. La
advertencia de `pe_ingrut`/`pe_condiciones` es genérica del carril **factura**-software-mercado
y aplica cuando habilitas factura/NC/ND/guía con motor propio, **no** cuando habilitas solo
boletas. Corroborado por proveedor certificado (blog SuperFactura): durante la certificación
"puede seguir usando el portal MIPYME normalmente".

- **CONDICIÓN DE EJECUCIÓN:** en la postulación/set habilitar **solo boletas (39/41)**, nunca
  factura/NC/ND/guía con el motor.
- ⚠️ **GOTCHA:** anular boletas con **nota de crédito desde el motor propio** te convierte en
  facturador de mercado → perderías MiPyme. Para anular boletas, emitir la NC **manualmente en
  el portal MiPyme**. (Fuente: SuperFactura.)

(El intento de "Bajar Set" con SOFTWARE DEMO SPA devolvió *"Debe estar habilitado en ambiente de
certificación y pruebas para iniciar el proceso"* — el guard de `core/postulacion.py` lo atrapó:
era texto de error, no un ZIP. La habilitación es la postulación `pe_ingrut`.)

## Camino para emitir TUS PROPIAS boletas (39/41) — software propio

Confirmado (guía oficial `sii.cl/factura_electronica/guia_emitir_boleta_servicio.htm` +
Res. 74 letra C: *"quien usa un sistema no autorizado deberá someterse a un proceso previo de
certificación"*). **No hay atajo.** Los pasos:

1. **Postular / bajar el set** — portal `www4.sii.cl/certBolElectDteInternet/?SET=1`.
2. **Emitir el set de pruebas** de boletas (nuestro motor).
3. **Enviar el RVD** del set (por `DTEUpload`, ver [`LECCIONES-SII.md`](LECCIONES-SII.md)). ⚠️ En
   **producción** el RVD **no es obligatorio** desde 2022-08-01 (Res. Ex. SII 53/2022) — el SII
   lo confirma con el reparo *"RVD no es obligatorio desde 2022-08-01"*; en el flujo de
   certificación igual se envía como parte del set.
4. **Solicitar revisión** informando el TrackID — portal `?SET=2`.
5. **Declaración de Cumplimiento** — portal base, firma del **rep legal** (único paso humano).

⚠️ **GOTCHA de canal**: el SET de certificación (los casos del set, no las boletas de
producción) se envía por **`DTEUpload`/Maullín (SOAP)** — el mismo canal de facturas — **NO**
por el REST de `pangal`/`rahue` (ese es solo para boletas operativas ya autorizadas en
producción). Enviarlo por REST devuelve *"El Documento no está en el envío"*.

## 🟢 CERTIFICACIÓN DE BOLETAS DE SOFTWARE DEMO SPA: COMPLETA (2026-07-22)

El set de boletas (SOK) se envió, pasó el **V°B°** de revisión, se grabó la **Declaración de
Cumplimiento**, y el SII respondió **"autorizada en ambiente de Producción"**. SOFTWARE DEMO SPA
(78111111-2) **ya emite boletas reales en producción** con este motor (folio 1 aceptado, `EPR`
+ `ACEPTADOS`). No queda ningún paso pendiente para boletas de esta empresa.

**Verificado en vivo (2026-07-18)**: el portal es una **app GWT** (necesita **playwright**, no
httpx), **entra con el certificado sin clave tributaria**, y al confirmar SOFTWARE DEMO SPA
(78111111-2) ofrece **"SET DE BOLETA ELECTRÓNICA AFECTA"** + campo de correo + "Bajar Nuevo
Set". SOFTWARE DEMO SPA **califica para postular boletas directo** (ya es emisor de facturas).

## Camino para facturas — y por qué SOFTWARE DEMO SPA quizá ni lo necesita

- Portal `maullin.sii.cl/cvc_cgi/dte/pe_generar` ("Generación de Nuevo Set de Pruebas",
  *Postulación Factura Electrónica*) — es el **cgi viejo, scriptable por httpx** (a diferencia
  del de boletas). Form: `RUT_EMP/DV_EMP/CODIGO=2/Confirmar Empresa` → `pe_generar1`.
- El proceso general de certificación de DTE tiene 6 pasos (Set de pruebas → Simulación →
  Intercambio → Muestras de impresión → Declaración de cumplimiento → Registro), fuente
  `sii.cl/factura_electronica/factura_mercado/proceso_certificacion.htm`.
- ⚠️ **SOFTWARE DEMO SPA YA está autorizada a facturas (33,34,52,56,61) en producción.** Por la
  regla "cambiar de software no obliga a re-certificar los tipos ya autorizados", **podría
  emitir facturas con nuestro motor sin postular nada** — camino corto a algo real.

## 🔴 Restricción dura: UN solo sistema de boletas por RUT

Del doc de TUU/Haulmer: si **dos** facturadores mandan el RVD por el mismo RUT, la **secuencia
choca** (*"La secuencia enviada no corresponde con la última registrada en el SII... un
facturador externo... verifique que Haulmer sea su único proveedor"*). ⇒ **EMPRESA DEMO SPA
usa TUU para boletas: NO emitir sus boletas con nuestro motor** mientras esté con Haulmer.
Boletas con motor propio → en **SOFTWARE DEMO SPA** (que no está en TUU).

## Qué es humano y qué se automatiza

Casi todo el trámite es automatizable con nuestro motor (postular, emitir el set, RVD,
solicitar revisión). **Nada de "ceder poderes" a un tercero** — el emisor eres tú, con tu
cert. El único paso genuinamente humano es la **firma de la Declaración de Cumplimiento** por
el representante legal — inherente a ser emisor de ti mismo, no una delegación.

## Fuentes oficiales
- Res. Ex. SII N° 74/2020: https://www.sii.cl/normativa_legislacion/resoluciones/2020/reso74.pdf
- Guía certificación boletas: https://www.sii.cl/factura_electronica/guia_emitir_boleta_servicio.htm
- Proceso de certificación (facturas): https://www.sii.cl/factura_electronica/factura_mercado/proceso_certificacion.htm
- Requisitos proveedor: https://www.sii.cl/servicios_online/3785-.html
- Listado proveedores: https://www.sii.cl/servicios_online/3785-proveedores_autorizados_be.html
