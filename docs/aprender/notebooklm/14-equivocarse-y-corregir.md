# Lección 1.4 — Equivocarse y corregir

## Objetivo

Entender que un documento emitido no se borra ni se edita, y que todo error se arregla con otro
documento: la nota de crédito (resta) o la nota de débito (suma).

## La escena

Ana emite la boleta 7 por una torta: 5.950. El cliente dice "no, era un café". Ana busca el
botón "borrar" y no existe. Tampoco puede abrir la boleta 7 y cambiarle el precio. La boleta 7
ya está en el SII.

## Explicación

### Por qué nada se borra

Cuando Ana emitió la boleta 7, el SII la recibió y la guardó. Si Ana pudiera borrarla o
cambiarla después, el registro del SII y el de Ana dejarían de coincidir, y nadie podría
confiar en ningún documento. Por eso la regla es simple: **lo emitido queda**. Un documento
tributario es como una anotación con tinta: no se borra, se tacha con otra anotación.

### La nota de crédito: resta

Para arreglar la boleta 7, Ana emite una **nota de crédito**. Es un documento nuevo, con su
propio folio, que dice: "esto resta a la boleta 7". Tiene dos usos:

1. **Anular**: la nota de crédito resta el total completo. Boleta 7 (5.950) + nota de crédito
   (-5.950) = 0. Es como si la venta no hubiera existido, pero los dos documentos quedan en el
   registro. Después Ana emite la boleta 8 correcta, por el café de 1.190.
2. **Corregir el monto**: si la boleta decía 5.950 y debía decir 2.380, la nota de crédito
   resta la diferencia: 3.570. Boleta 7 (5.950) - nota (3.570) = 2.380.

La nota de crédito siempre dice **a qué documento corrige** (la "referencia": tipo, folio y
fecha del documento original) y **por qué** (anula, corrige monto, corrige texto).

### La nota de débito: suma

Es la contraria. Si Ana cobró de menos (la boleta decía 1.190 y era un café grande de 2.380),
emite una **nota de débito** que suma la diferencia: 1.190.

También se usa para **dejar sin efecto una nota de crédito** que se emitió mal. Como la nota de
crédito tampoco se borra, se compensa con una nota de débito que la anula. Las correcciones
también se corrigen con documentos.

### Cómo queda el registro

| Folio | Documento | Referencia | Monto | Saldo acumulado |
|---|---|---|---|---|
| 7 | boleta | — | 5.950 | 5.950 |
| NC 1 | nota de crédito | anula boleta 7 | -5.950 | 0 |
| 8 | boleta | — | 1.190 | 1.190 |

El cliente pagó 1.190 y el registro dice 1.190. Pero quedó la historia completa: hubo una
boleta, se anuló, se emitió otra. Cualquiera que mire después entiende qué pasó.

### El costo de equivocarse

Cada documento gasta un folio. La boleta 7 equivocada gastó un folio de boleta; la nota de
crédito gastó un folio de nota de crédito; la boleta 8 gastó otro folio de boleta. Nada
grave, pero por eso conviene **revisar antes de emitir**, sobre todo en las facturas: una
factura con el RUT del cliente equivocado se anula completa y se emite de nuevo, y el
cliente se queda sin su factura hasta que eso pase.

## Errores comunes

- "Le pido al sistema que elimine la boleta." No existe eliminar.
- "Emito la boleta correcta y la equivocada la ignoro." No: la equivocada sigue sumando en el
  SII. Hay que anularla con nota de crédito.
- "La nota de crédito es una devolución de plata." No necesariamente: es el documento que
  registra la corrección. Si además hay que devolver plata, eso es aparte.
- "Hago una nota de crédito por el monto que recuerdo." Hay que hacerla por el monto exacto del
  documento original; si no, no cuadra y queda un saldo colgando.

## Pregunta de cierre

¿Por qué no se puede borrar la boleta 7?

**Respuesta: porque el SII ya la recibió y la guardó. Lo emitido queda. Se corrige con una
nota de crédito que la anula, y las dos quedan en el registro.**
