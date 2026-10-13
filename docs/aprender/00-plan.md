# Aprender a facturar y declarar — plan del curso

> Para alguien que no sabe nada de finanzas ni de impuestos. Pensado para la app y para una
> clase de educación cívica. Cada lección tiene **concepto**, **acción en la app** y **una pregunta**.
> Ningún ejemplo usa empresas ni personas reales (ley L14): la empresa del curso es
> **EMPRESA DEMO SPA, RUT 77.777.777-7**.

## Los cinco tramos, en el orden en que pasan en la vida real

| Tramo | Qué aprende la persona | Qué usa la app | Riesgo |
|---|---|---|---|
| **1. Entender** | qué es una boleta, una factura, el IVA, el RUT, el SII, "declarar" | simulación local, sin red ni claves | ninguno |
| **2. Crear la empresa** | qué es una persona jurídica, Empresa en un Día, el RUT de la empresa, representante legal | guía paso a paso y lista de verificación; la app no lo hace por ti | ninguno |
| **3. Iniciar actividades** | inicio de actividades, giro, clave tributaria, certificado digital, inscribirse como emisor | asistente de alta (diagnóstico de solo lectura contra el SII) | ninguno |
| **4. Usar lo que el SII da gratis** | el emisor gratuito de facturas y el de boletas (eboleta); emitir, ver documentos, anular con nota de crédito, el Registro de Compras y Ventas, el F29 | **canal MIPYME**: la app opera el portal del SII por ti y le agrega lo que falta (archivo de PDF/XML, resúmenes, avisos) | **real desde el primer clic**: no hay ambiente de pruebas |
| **5. El motor propio** | qué es un CAF, la firma, el ambiente de certificación, por qué certificar, cuándo conviene | motor propio en el **ambiente de pruebas del SII** primero; producción solo tras certificar | pruebas sin efecto; producción con efecto |

El tramo 4 va antes que el 5 a propósito: primero la persona aprende que **el SII ya le da un
emisor gratis** y que la app lo mejora sin reemplazarlo. El motor propio es para quien emite
mucho, integra sistemas o quiere ser dueño de todo; es difícil y se enseña al final.

## La regla de oro de la app en cada tramo

Arriba de todo, siempre visible, en qué mundo estás:
- 🟢 **Simulación** — nada sale de tu computador.
- 🟡 **Pruebas del SII** — el SII responde de verdad, sin efecto tributario.
- 🔴 **Real** — cada documento cuenta. Antes de la primera emisión, una pantalla que lo dice
  en una frase y pide confirmación.

---

## Tramo 1 — Entender (simulación)

**1.1 Qué pasa cuando compras algo.** La boleta de un café: 1.190 por un café de 1.000. El IVA
es el 19% que va al Estado; el negocio solo lo recauda. *Acción:* abrir una boleta demo en la
app y tocar cada parte: folio, fecha, neto, IVA, total, timbre. *Pregunta:* si el café vale
2.000, ¿cuánto dice la boleta?

**1.2 Qué pasa cuando vendes.** Emitir tu primera boleta en simulación. Ver el PDF con el
timbre. Entender que el folio es un número que no se repite y que el SII "la recibe".
*Acción:* emitir una boleta de 5.000. *Pregunta:* ¿qué número tiene la siguiente boleta?

**1.3 Boleta o factura.** La boleta es para personas; la factura es para empresas, lleva el
RUT y el nombre del cliente, y le sirve a él para descontar IVA. La factura **exenta** es la
que no lleva IVA (arriendos, educación, salud…). *Acción:* emitir una factura a CLIENTE DEMO
SPA. *Pregunta:* ¿quién puede usar esa factura para descontar impuestos?

**1.4 Equivocarse y corregir.** Nada se borra. Un documento mal hecho se corrige con otro
documento: la **nota de crédito**, que resta, y la **nota de débito**, que suma. *Acción:*
anular la boleta de 1.2 con una nota de crédito. *Pregunta:* ¿por qué no se puede borrar?

**1.5 El mes.** Todo lo que vendiste y compraste queda en el **Registro de Compras y Ventas**
del SII. Al final del mes se **declara** en el **F29**: cuánto IVA cobraste, cuánto pagaste,
la diferencia. *Acción:* ver el mes de la empresa demo y su F29 propuesto. *Pregunta:* si
cobraste 19.000 de IVA y pagaste 10.000, ¿cuánto declaras?

**1.6 Lo que no es obvio.** Sin movimiento también se declara. El RUT de la empresa no es el
tuyo. La clave tributaria no es la clave del certificado. Los folios se cuidan.

---

## Tramo 2 — Crear la empresa (guía)

**2.1 Persona natural o empresa.** Qué cambia: responsabilidad, impuestos, RUT propio.
**2.2 Empresa en un Día.** Qué se llena, qué cuesta, qué sale: RUT, estatuto, representante.
**2.3 Lista de verificación** en la app: cada paso con "hecho / falta", sin hacerlo por ti.

## Tramo 3 — Iniciar actividades (guía + asistente)

**3.1 Inicio de actividades y giro.** Qué es un código de actividad y por qué importa (exento o afecto).
**3.2 Clave tributaria.** Es la llave de todo lo demás. Quién la tiene, cómo se cuida.
**3.3 Certificado digital.** Qué es, para qué sirve (firmar), que tiene su propia clave distinta.
**3.4 Inscribirse como emisor.** El asistente de la app lee tu estado en el SII y te dice qué falta.

## Tramo 4 — Usar lo que el SII da gratis (canal MIPYME, REAL)

**4.1 El SII tiene un emisor gratis.** Facturas en su portal, boletas en eboleta. La app lo
usa por ti: entra con tu clave, emite, guarda PDF y XML, te muestra tu historial.
**4.2 Tu primera factura real.** Pantalla roja: "esto es real". Vista previa, revisar los cinco
montos, confirmar. **Un folio gastado no vuelve.**
**4.3 Anular de verdad.** Desde la fila del documento en Documentos: nota de crédito por el total registrado, no por lo
que dice la línea. La app lo verifica antes de gastar folio.
**4.4 Tu mes, de verdad.** El Registro de Compras y Ventas real y la propuesta del F29 del SII,
lado a lado con el cálculo de la app. Cuando no coinciden, la app explica por qué.
**4.5 Declarar.** Sin movimiento también. Qué plazos hay. Qué pasa si no declaras.

## Tramo 5 — El motor propio (pruebas del SII → producción)

**5.1 Por qué existe.** Volumen, integración, ser dueño de tus documentos.
**5.2 CAF, folios y firma.** El SII te autoriza rangos; tú timbras y firmas.
**5.3 Certificar.** El set de pruebas, el ambiente de certificación, qué revisa el SII.
**5.4 Pasar a producción.** Cambiar el software registrado; convivir o no con el gratuito.

---

## Qué falta para que esto exista

- Los textos completos de cada lección (este plan es el índice).
- El quiz del tramo 1 ya existe: [`quiz-tramo-1.md`](quiz-tramo-1.md) y su JSON para la app.
- Los videos del tramo 1: las **fuentes para NotebookLM** están en [`notebooklm/`](notebooklm/README.md)
  (un archivo por lección, autocontenido). Los prompts de [`videos-tramo-1.md`](videos-tramo-1.md)
  son la alternativa si se generan con un modelo de video en vez de NotebookLM.
- En la app: **hecho** el modo simulación (EMPRESA DEMO SPA emite, se ve y se anula con el
  pipeline real, sin envío; `core/simulacion.py`) y la barra de "en qué mundo estás".
- **Hecho (2026-10-13): la mini academia dentro de la app.** 23 lecciones en 5 módulos (lo
  básico: impuesto, SII y RUT, IVA, boleta o factura, exento, neto/IVA/total; los números del
  mes: UF y UTM, débito y crédito, F29, PPM, renta y F22; tu empresa: persona o empresa, SpA/EIRL/
  Ltda./S.A., regímenes Pro-PYME, inicio de actividades y giro, clave tributaria y certificado;
  las fechas: calendario, honorarios y retención, multas; los documentos: folio y CAF, notas,
  RCV, gratuito o motor propio). Cada lección: concepto, ejemplo con números, "Hazlo en la app" y
  una pregunta. El texto completo está en [`LECCIONES.md`](LECCIONES.md), generado desde los
  mismos datos (`tools/academia_datos.py` → `app/frontend/dist/academia.js`;
  `tools/revisar_academia.py --md`).
