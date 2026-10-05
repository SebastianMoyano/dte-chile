# Captura web — extensión de Chrome (SII y cualquier sitio)

Graba, con un botón, todo lo que tu Chrome le manda y recibe en la pestaña activa, y lo descarga
como un JSON legible. Nació para capturar flujos reales del portal del SII (emitir una nota,
"Obtener Envío", eboleta, F29) sin mitmproxy y sin copiar peticiones a mano; desde la v3 sirve
para **cualquier sitio**, y el JSON es, en orden, **lo que vería un agente** que navegara esa
página: cada página con su HTML y su **texto visible**, cada llamada AJAX/fetch con su respuesta.

- Por defecto solo tráfico de `sii.cl`. Con la casilla **"Grabar en cualquier sitio"** pide el
  permiso de Chrome para todos los sitios y graba la pestaña que elijas, sea la que sea (útil
  para ver qué recibe un agente de tu propia página). Se puede desactivar y el permiso se devuelve.
- Ignora imágenes, fuentes, CSS, analítica y el script anti-bot del F5. Guarda el JS como
  petición (URL y estado) pero no su contenido.
- **Tacha secretos** antes de guardar: `clave`, `contraseña`, `password`, `token`, `api_key`,
  `secret`, `otp`, campos `type=password`, `Bearer …` quedan como `***`; las cookies y las
  cabeceras `Authorization`/`X-API-Key`/`X-CSRF-Token` se omiten. El JSON se puede pegar en un chat.
- Guarda, en orden: cada petición de red (método, URL, cabeceras, cuerpo enviado, estado), el
  **HTML y el texto visible de cada página** que llega (también en apps de una sola página, por
  cambio de ruta) y cada llamada **AJAX/fetch con su respuesta**. No usa el depurador de Chrome:
  nada se corta solo, graba hasta que pulses Detener, y cada entrada se guarda al instante.
- Límites por entrada para que la grabación no explote: HTML 2 MB, texto 300 k, respuestas 1 MB
  (se recortan y se marca).

## Instalar (una vez)

1. Chrome → `chrome://extensions` → activa **Modo de desarrollador** (arriba a la derecha).
2. **Cargar extensión sin empaquetar** → elige esta carpeta `tools/captura-sii`.
3. Fija el ícono "Captura web" en la barra (menú de extensiones → pin).

## Usar

1. Abre el portal del SII (o, con "cualquier sitio" activado, la página que quieras) y llega
   hasta justo antes del flujo que quieres capturar.
2. Clic en el ícono → **Grabar esta pestaña**. Toma una foto de la página actual y empieza.
3. Haz el flujo completo (formulario, revisión, firmar, clave, envío, resultado).
4. Clic en el ícono → **Detener y descargar**. Queda `captura_<sitio>_<fecha>.json` en Descargas.

Si recargas la extensión en `chrome://extensions` (tras cambios), vuelve a abrir el popup antes de grabar.

## Leerla desde el motor

```bash
.venv/bin/python tools/captura-sii/comparar_captura.py ~/Downloads/sii_captura_....json
# con una carpeta de evidencia del módulo, compara campo a campo el envío:
.venv/bin/python tools/captura-sii/comparar_captura.py ~/Downloads/sii_captura_....json \
    --evidencia storage/mipyme_fallidos/777777777/T61_F58_20261002T212520
```

## Qué hay en el JSON (para alimentar a un agente)

```json
{ "herramienta": "captura-web/3.0", "modo": "todo", "sitio": "tu-pagina.cl", "indice": ["001 [página load] https://…", "002 [ajax] POST 200 https://…/api/…"],
  "entradas": [
    { "n": 1, "tipo": "pagina", "momento": "load", "url": "…", "titulo": "…", "texto": "lo que se lee en pantalla", "html": "<html>…" },
    { "n": 2, "tipo": "xhr", "metodo": "POST", "url": "…/api/…", "cuerpo": "…", "estado": 200, "respuesta": "{…}" },
    { "n": 3, "tipo": "red", "metodo": "GET", "url": "…", "estado": 200, "cabeceras": {…}, "cabeceras_respuesta": {…} } ] }
```

`texto` es `document.body.innerText`: la página tal como la leería un agente que no ejecuta
JavaScript ni mira el HTML. Comparar `texto` con `html` y con las respuestas `xhr` muestra
exactamente qué parte de tu página llega por el HTML inicial y qué parte solo existe después de
una llamada. En aplicaciones de una sola página también se toma una foto en cada cambio de ruta.

