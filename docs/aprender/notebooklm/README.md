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

4. Si el video sale demasiado general, en vez de repetir, agrega al archivo de la lección la
   frase o el dato que faltó. El video mejora cuando mejora la fuente.
5. Revisa que las cifras que diga el video sean las de la fuente. Si cambia una, regenera.

## Qué no subir

- Nada con RUT reales, nombres de clientes ni documentos emitidos de verdad (ley L14 del repo).
- Capturas del portal del SII: el video las reproduciría con logos y datos.

## Orden de producción sugerido

1.1 y 1.4 primero (son los que explican el "por qué"); luego 1.2, 1.3, 1.5 y 1.6.
