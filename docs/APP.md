# App de escritorio (`app/`)

Cascarón multiplataforma en **Go + Wails v2** sobre el motor Python. No reimplementa nada:
arranca `main.py` como proceso hijo y le habla por HTTP. La idea de producto está en
[`aprender/00-plan.md`](aprender/00-plan.md): una app para quien no sabe nada de finanzas,
con tres acciones ("Cobrarle a alguien", "Mi mes", "Corregir") y una barra que dice siempre
en qué mundo estás (simulación / pruebas del SII / real).

## Cómo funciona

```
DTE Chile.app (Go)                         motor (Python, main.py)
  ├─ localiza la raíz del repo  ──────►    .venv/bin/python -m uvicorn main:app
  ├─ puerto libre en 127.0.0.1               --host 127.0.0.1 --port <libre>
  ├─ APP_SHELL_KEY=app_<48 hex>  ──────►    settings.app_shell_key
  ├─ espera GET / == 200
  └─ App.API(método, ruta, json) ─────►    Authorization: Bearer <clave>
       (la interfaz nunca ve la clave)      → actúa como el usuario dueño (menor id)
```

- **Clave efímera.** `APP_SHELL_KEY` vive solo en el entorno del proceso hijo. No va en
  `.env` ni en la BD. `core/auth.py::requerir_autenticacion` la compara en tiempo constante y
  devuelve el usuario dueño de la instalación, así los negocios y certificados son los suyos.
- **Sin CORS, sin login.** La interfaz (`app/frontend/dist`, HTML/CSS/JS sin framework) llama a
  Go (`window.go.main.App.API`) y Go firma la petición. No hay token en el webview.
- **Cierre limpio.** Al cerrar la app, Go manda SIGINT a uvicorn (apaga programadores y BD) y
  si no termina en 5 s lo mata. En Windows mata directo.
- **Modo externo.** Con `DTE_API_URL` (y `DTE_API_KEY`, una API key `dte_...`) la app no
  arranca nada y usa ese motor: sirve para desarrollo y para el motor desplegado en otra máquina.
- **Raíz del repo.** `DTE_REPO`, o subiendo desde el ejecutable o el cwd hasta encontrar
  `main.py` + `core/`. Para empaquetar sin repo (instalador) falta embeber Python; ver pendientes.

## La empresa de práctica (modo simulación)

Arriba hay un selector de empresa. La primera siempre es **EMPRESA DEMO SPA (práctica)**:
el mundo del tramo 1 del curso. Con ella elegida, la barra dice **SIMULACIÓN** y todo lo que
se emite pasa por el mismo pipeline que un documento real (folio atómico → TED → XML → firma
→ PDF → BD) pero con un emisor ficticio, un CAF de mentira, un certificado autofirmado en
memoria y **sin envío**. Ver `core/simulacion.py` y `api/routes/simulacion.py`
(`/api/v1/simulacion/{estado,emitir,anular/{id},documentos/{id},reiniciar}`).

- Los documentos quedan con `ambiente='simulacion'` y `estado='simulado'`, sus archivos en
  `storage/simulacion/`, y el PDF dice "documento de práctica, sin validez tributaria".
- "Anular" emite una nota de crédito por el total registrado y marca el original como
  `anulado_simulado`: la lección de que nada se borra.
- "Empezar de nuevo" (solo en práctica) borra todo lo de la empresa demo y vuelve al folio 1.
- En boletas el precio se manda **con IVA incluido** (así las exige el SII); en facturas, neto.
  La app lo hace sola.

Prueba sin red: `.venv/bin/python test_simulacion.py` (20 comprobaciones).

## El núcleo en Go dentro de la app (fase 4 del port)

Cuando la empresa elegida emite con el motor propio, "Cobrarle a alguien" **no** llama a
`/dte/emitir`: el cascarón firma y persiste con el núcleo en Go (`nucleo/`, el mismo que
reproduce el corpus dorado byte a byte y cuyo T34 el SII aceptó). La secuencia, en
`app.go::EmitirNucleo`:

1. `GET /api/v1/keystore/negocios/{id}/contexto-emision` → el motor descifra el certificado
   del keystore y lo entrega en PEM **en memoria por la conexión local**, junto con la
   resolución del emisor para su ambiente y las rutas absolutas de la base y del storage.
   La clave privada viaja una vez por emisión y no se escribe en ningún lado.
2. `nucleo/emision.Emitir` sobre la misma base (folio atómico) y el mismo storage: mismas
   rutas y la misma fila que Python.
3. `POST /api/v1/dte/documentos/{id}/pdf` → Python dibuja el PDF desde el XML firmado
   (`core/dte_xml.py` reconstruye la entrada, el TED es el original). El núcleo no hace PDF.

Python sigue siendo dueño del keystore, del PDF, del envío al SII, de MIPYME, RCV y F29.
La app de práctica (EMPRESA DEMO SPA) sigue en Python (`core/simulacion.py`).

## Pantallas (v0.1)

| Pantalla | Qué hace hoy | Endpoints |
|---|---|---|
| Inicio | estado del motor, la empresa activa (práctica o real) con su etiqueta, tres acciones, 'empezar de nuevo' en práctica | `/`, `keystore/negocios`, `simulacion/estado` |
| Cobrarle a alguien | boleta/factura, afecta/exenta, monto con o sin IVA, cálculo en vivo, aviso verde/amarillo/rojo según el mundo; emite en práctica (Python) o con el **núcleo Go** (empresa real) y abre el visor | `simulacion/emitir`, `dte/emisor`, `keystore/…/contexto-emision`, `dte/documentos/{id}/pdf` |
| Mi mes | suma neto/IVA/total del mes por empresa (las NC restan), recordatorio de "sin movimiento" | `dte/documentos` |
| Corregir | lista documentos corregibles; en práctica anula con NC; en empresas reales, próxima versión | `dte/documentos`, `simulacion/anular` |
| Ver | visor de PDF embebido con las partes explicadas, guardar PDF/XML, anular (práctica) | `dte/documentos/{id}/pdf` |
| Documentos | todas las empresas, filtro, guardar PDF/XML con diálogo del sistema | `dte/documentos`, `/pdf`, `/xml` |
| Aprender | los cinco tramos del curso (solo índice) | — |

Si la empresa elegida no emite con el motor propio (gratuito del SII u otro software), "Cobrar"
lo dice y manda al panel web; no intenta emitir.

## Desarrollo

```bash
go install github.com/wailsapp/wails/v2/cmd/wails@latest   # una vez
cd app
wails dev                      # recarga en caliente; abre el motor como sidecar
wails build -platform darwin/arm64 -s     # build/bin/DTE Chile.app
wails build -platform darwin/universal    # Intel + Apple Silicon
```

La interfaz está en `app/frontend/dist` directamente (sin bundler, sin `npm install`). Los
bindings `app/frontend/wailsjs` los genera Wails y no se versionan.

Registro del motor arrancado por la app: `logs/app-motor.log`.

## Pendientes

1. **Emitir por el gratuito desde la app** (canal MIPYME, `core/sii_mipyme.py`): hoy solo el
   motor propio. Requiere la primera emisión verificada (`CADENAS_VERIFICADAS`).
2. **Nota de crédito desde "Corregir"** por el total registrado del documento.
3. **Datos del emisor por negocio** en BD (giro, actividad, dirección) en vez de `EMPRESA_*`
   del `.env`; hoy solo la empresa del `.env` puede emitir con el motor propio.
4. Cargar las lecciones y el quiz (`docs/aprender/`) en la pantalla Aprender, enlazados al
   modo práctica (que ya existe).
5. **Instalador**: embeber Python (o PyInstaller del motor) para que la app no dependa del
   repo; build Windows/Linux. La firma y notarización en macOS ya tiene script:
   `app/firmar-mac.sh` (identidad y credenciales por entorno, nada en el repo).
