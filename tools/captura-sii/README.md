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
- **Tacha secretos en dos capas** (`tachar.js`): por **nombre** (cualquier parámetro, campo de
  formulario, clave JSON, atributo HTML o cabecera cuyo nombre *contenga* clave, contraseña,
  password, token, secret, api_key, auth, csrf, session, sid, jwt…) y por **valor**, aunque el
  nombre sea inocente: JWT (`eyJ….eyJ….firma`), `Bearer …`, hex de 32+ caracteres, uuid junto a
  un nombre sensible, inputs `type=password`. Se aplica a cuerpos, respuestas, HTML, texto
  visible, URLs y cabeceras; las cookies y las cabeceras de autorización se omiten. Al detener,
  el **JSON entero pasa otra vez** por el tachado y se audita: el archivo trae `auditoria` con
  cuántas cadenas aún parecen secretos, y el popup lo muestra. **Si no es todo 0, revisa antes
  de compartir.** Un tachado por patrones nunca es una garantía: es una red con agujeros
  conocidos (un token con nombre raro y forma inocente puede pasar).
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

## Datos personales: RUT, correos y celulares ficticios

Con la casilla **"Reemplazar RUT, correos y celulares por ficticios"** (`pii.js`), cada dato
personal se sustituye por uno inventado **consistente**: el mismo RUT real da siempre el mismo
RUT ficticio dentro de la captura (también si aparece con puntos, sin puntos o como parámetro
`rut…=` sin dígito verificador), lo mismo con cada correo (`persona1234@ejemplo.cl`) y cada
celular (`+56 9 ….`, se conservan los separadores). Los RUT ficticios son válidos (módulo 11),
de persona (10-24 millones) o de empresa (76-77 millones) según el real, y no corresponden a
nadie. Un agente que lea la captura sigue viendo la estructura (este cliente aparece en estas
tres páginas) sin saber quién es. No se tocan folios, totales, fechas, códigos ni teléfonos fijos.

- Por defecto está **activada en "cualquier sitio"** y **desactivada en sii.cl**: las capturas
  del SII se comparan campo a campo con lo que manda el módulo y ahí los RUT deben ser los reales.
- El archivo lo dice en `datos_personales` (`reemplazados: true/false`, y si no, cuántos hay).
- `limpiar_captura.py` hace el mismo reemplazo (mismo algoritmo, mismos ficticios dada la misma
  semilla) por defecto; `--sin-pii` lo desactiva.
- El reemplazo se hace sobre los valores, nunca sobre el JSON serializado (la 3.2 lo hacía
  sobre el texto y podía dejar `\persona…`, un escape inválido; `limpiar_captura.py` repara
  esos archivos). Antes de descargar se comprueba que el JSON sea válido.
- Límite honesto: reconoce RUT con guion, correos y celulares chilenos. Un nombre y apellido, una
  dirección o un RUT sin guion ni contexto `rut=` **no** se reemplazan.

## Limpiar una captura ya descargada

Las capturas de la v2 y la v3.0 tachaban solo por nombre exacto (`token` no calzaba con
`api_token`) y no miraban valores: un JWT en una respuesta se guardaba entero. Para esos
archivos, o como segunda pasada antes de compartir cualquiera:

```bash
python3 tools/captura-sii/limpiar_captura.py ~/Downloads/captura_….json      # escribe ….limpio.json
python3 tools/captura-sii/limpiar_captura.py ~/Downloads/captura_….json --en-sitio
```

Imprime cuántos JWT y uuid junto a nombres sensibles había antes y quedan después, y lista los
uuid que se repiten 3 o más veces (pueden ser ids inocentes o un token con un nombre que las
reglas no conocen: míralos). Sale con código 1 si queda algo. Un token que ya se compartió
está comprometido aunque después se tache: **revócalo** (cierra sesión, regenera la api key).

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

