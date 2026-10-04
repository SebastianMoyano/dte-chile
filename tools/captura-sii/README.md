# Captura SII — extensión de Chrome

Graba, con un botón, todo lo que tu Chrome le manda y recibe de **sii.cl** en la pestaña activa, y
lo descarga como un JSON legible. Es la herramienta para capturar un flujo real del portal (emitir
una nota, "Obtener Envío", eboleta, F29) sin mitmproxy y sin copiar peticiones a mano.

- Solo tráfico de `sii.cl`; ignora imágenes, CSS, JS, analítica y el script anti-bot del F5.
- **Tacha secretos** antes de guardar: `clave`, `password`, `myPass`, etc. quedan como `***`; las
  cookies y cabeceras de autorización se omiten. El JSON se puede pegar en un chat.
- Guarda, en orden: cada petición de red (método, URL, cabeceras, cuerpo enviado, estado), el
  **HTML de cada página** que llega (la respuesta real de formularios y navegaciones) y cada
  llamada **AJAX con su respuesta** (p.ej. la firma central). No usa el depurador de Chrome:
  nada se corta solo, graba hasta que pulses Detener, y cada entrada se guarda al instante.

## Instalar (una vez)

1. Chrome → `chrome://extensions` → activa **Modo de desarrollador** (arriba a la derecha).
2. **Cargar extensión sin empaquetar** → elige esta carpeta `tools/captura-sii`.
3. Fija el ícono "Captura SII" en la barra (menú de extensiones → pin).

## Usar

1. Abre el portal del SII y llega hasta justo antes del flujo que quieres capturar.
2. Clic en el ícono → **Grabar esta pestaña**. Toma una foto de la página actual y empieza.
3. Haz el flujo completo (formulario, revisión, firmar, clave, envío, resultado).
4. Clic en el ícono → **Detener y descargar**. Queda `sii_captura_<fecha>.json` en Descargas.

Si recargas la extensión en `chrome://extensions` (tras cambios), vuelve a abrir el popup antes de grabar.

## Leerla desde el motor

```bash
.venv/bin/python tools/captura-sii/comparar_captura.py ~/Downloads/sii_captura_....json
# con una carpeta de evidencia del módulo, compara campo a campo el envío:
.venv/bin/python tools/captura-sii/comparar_captura.py ~/Downloads/sii_captura_....json \
    --evidencia storage/mipyme_fallidos/777777777/T61_F58_20261002T212520
```
