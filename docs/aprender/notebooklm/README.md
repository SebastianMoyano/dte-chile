# Fuentes para NotebookLM — tramo 1 (Entender)

Cada archivo de esta carpeta es una **fuente autocontenida** para generar un Video Overview
en NotebookLM. Están escritos para que el video no tenga que inventar nada: traen el objetivo,
la explicación completa, el ejemplo con números ya calculados, los errores típicos y un cierre.

## Cómo usarlos

1. Crea **un cuaderno por lección** (seis en total). Un cuaderno con todo mezclado produce un
   video que salta entre temas.
2. En cada cuaderno sube **dos fuentes**: `00-contexto.md` y el archivo de la lección.
3. Genera el **Video Overview**. En "Personalizar" pega esta instrucción, cambiando el número:

   > Explica solo la lección 1.X para alguien que nunca ha trabajado ni emitido una boleta.
   > Usa el ejemplo con números tal como viene en la fuente. Español de Chile, cercano, sin
   > tecnicismos sin explicar. Termina con la pregunta de cierre y deja la respuesta en pantalla.
   > No menciones empresas ni personas reales: solo EMPRESA DEMO SPA y CLIENTE DEMO SPA.
   > Todo ocurre en Chile: pesos chilenos con $, IVA único de 19%. No muestres tickets,
   > facturas ni billetes de otros países.

4. Si el video sale demasiado general, en vez de repetir, agrega al archivo de la lección la
   frase o el dato que faltó. El video mejora cuando mejora la fuente.
5. Revisa que las cifras que diga el video sean las de la fuente. Si cambia una, regenera.

## Formato

El primer video (1.1) se generó en formato **Short** (vertical, 70 segundos) y quedó bien:
siguió la fuente, usó las cifras exactas y cerró con la pregunta. Para estas lecciones, que
son cortas, Short alcanza. Explainer sirve si una lección sale incompleta.

Lo único que falló en esa primera generación fueron dos imágenes de relleno: un ticket de
supermercado español (con euros y dos tasas de IVA) y billetes de euro. De ahí la regla
"Todo es Chile" en `00-contexto.md` y la frase extra en la instrucción.

## Qué no subir

- Nada con RUT reales, nombres de clientes ni documentos emitidos de verdad (ley L14 del repo).
- Capturas del portal del SII: el video las reproduciría con logos y datos.

## Orden de producción sugerido

1.1 y 1.4 primero (son los que explican el "por qué"); luego 1.2, 1.3, 1.5 y 1.6.
