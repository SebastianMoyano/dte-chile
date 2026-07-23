# De cero a emitir — Guía de puesta en marcha

Esta guía te lleva desde una instalación nueva hasta emitir tu primer DTE, con tu
certificado y tus datos, **en tu propio equipo** (self-hosted — nada se lo entregas a un
tercero).

## 1. Instalar y arrancar

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python setup.py                 # crea .env con secretos fuertes, la BD y el usuario admin
uvicorn main:app --port 8000
```

`setup.py` imprime **la contraseña de admin una sola vez** — guárdala. Genera solos el
`JWT_SECRET_KEY` y el `DTE_MASTER_KEY` (la clave que cifra tus certificados). No los
compartas ni los cambies después sin re-subir los certificados (ver `rotar_claves.py`).

## 2. El asistente (wizard)

Abre **http://localhost:8000/onboarding** e inicia sesión. El asistente te lleva paso a
paso:

1. **Certificado** — sube tu `.pfx`/`.p12` (del representante legal) + su clave. Se guarda
   **cifrado en tu equipo**.
2. **Empresa** — se descubren solas las empresas asociadas a tu certificado (no escribes RUT).
3. **Diagnóstico** — el sistema investiga en el SII (solo lectura) y te dice en qué punto
   estás y **qué falta**, con cada acción marcada:
   - 🤖 **auto** — lo hace el sistema.
   - 🔐 **requiere tu autorización** — escribe en el SII a tu nombre; te explica qué hará
     antes de ejecutar.
   - 👤 **gestión con el SII** — necesita un trámite (p. ej. una llamada a Mesa de Ayuda).

## 3. Requisitos del SII (lo que el SII exige, no este programa)

Para emitir facturas electrónicas, el SII pide:

1. **Inicio de actividades** vigente + ser contribuyente de Primera Categoría.
2. **Certificado digital** de una CA autorizada (E-CertChile, etc.).
3. **Estar inscrito** como facturador electrónico.
4. **Certificar** tu software (el "set de pruebas" — el sistema lo automatiza).
5. **Registrar tu software** de facturación en el SII (Actualización de datos) — el "switch".

El diagnóstico chequea 2, 3 y 5 por ti y te dice cuáles faltan.

## 4. Importante: exenta, boleta y el tema del "33"

Confunde a todos, así que déjalo claro:

- **Boleta (39/41)** y **Factura (33/34)** son **inscripciones distintas** en el SII.
- La familia **Factura** incluye **33 (afecta)** y **34 (exenta)** juntas.
- El **sistema gratuito del SII** puede habilitarte solo lo que usas (p. ej. solo Factura
  Exenta 34, sin la 33).
- Pero pasar a **software propio o de mercado** (como este programa, o Haulmer) exige la
  **certificación del SET BÁSICO, que incluye la Factura Afecta (33)** — aunque solo vayas
  a emitir exentas. Habilitar el 33 **no te obliga** a emitir afectas; solo queda disponible.

> Si tu empresa emite solo exenta hoy con el sistema gratuito, el diagnóstico te lo dirá y
> te explicará que la certificación agregará el 33. Es normal.

## 5. Después: certificar y pasar a producción

- **Set de pruebas**: el motor genera, firma y envía los 16 casos al ambiente de
  certificación (Maullín) y consulta su estado. Si el timbraje de algún tipo está bloqueado
  (anti-acaparamiento), el diagnóstico te avisa que hay que pedirlo a la Mesa de Ayuda del
  SII (600 330 3000).
- **Producción**: al terminar el set, el SII emite la resolución. Entonces cambias tu
  software de facturación registrado a este sistema (acción 🔐 con tu autorización) y ya
  emites en producción.

## Seguridad, en corto

- Certificados: cifrados con Fernet en tu equipo; nunca en texto plano ni entregados a nadie.
- La API arranca **fail-closed en producción** si hay secretos por defecto.
- Toda acción que escribe en el SII pide tu **autorización explícita** antes de ejecutar.

Ver también: [`docs/MCP.md`](./MCP.md) (servidor MCP para IA) y
[`docs/ERRORES-API.md`](./ERRORES-API.md).
