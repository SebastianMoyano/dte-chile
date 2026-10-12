# App de escritorio (`app/`)

Cascarón multiplataforma en **Go + Wails v2** con el motor Go (`nucleo/servidor`) adentro,
en el mismo proceso (desde la fase 7 del port, 2026-10-11; antes arrancaba el motor Python como
sidecar, y con `DTE_MOTOR=python` todavía puede, para comparar). La interfaz le habla por HTTP
igual que antes, así que el diagrama de abajo sigue valiendo cambiando "proceso hijo Python" por
"servidor Go en proceso". La idea de producto está en
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

Python sigue siendo dueño del keystore, del PDF, del envío al SII, de RCV y F29.
La app de práctica (EMPRESA DEMO SPA) sigue en Python (`core/simulacion.py`).

### El SII engine en Go dentro de la app (fase 6 del port)

"Traer lo emitido en el SII" ya no pasa por `/api/v1/mipyme/sincronizar`: el cascarón corre
`nucleo/siiengine` en su propio proceso (`app/siiengine.go::SIIEngineSincronizar`). Secuencia:
`GET /api/v1/mipyme/contexto-siiengine/{rut}` (las claves **recordadas**, descifradas del
keystore, y las rutas de la base y del storage; mismo modelo de confianza que contexto-emision)
→ si la persona marcó recordar, `PUT /api/v1/keystore/claves-sii` → sesión, empresa, form,
historial e importación a la misma base. El JS cae al endpoint Python si el binding no existe.

**Cobrar por el SII engine** (`app/siiengine.go::SIIEngineFactura`): para una empresa que emite
en el sistema del SII, "Cobrarle a alguien" con "Una empresa" + "No lleva IVA" pide giro,
dirección, comuna y ciudad del cliente (el portal los exige), pide las claves, y hace un
**dry-run real**: el SII valida el documento y la app muestra la vista previa sin gastar folio.
El botón "Emitir de verdad" solo aparece cuando `siiengine.CadenasVerificadas` tiene la
factura, es decir, después de la primera corrida real desde Go: la interfaz **no** puede aceptar
el riesgo de folio por la persona (ley L10). Hasta entonces, el CLI `nucleo-siiengine factura`.
Boletas: siguen en eboleta.sii.cl (sin captura, no portado).

**Corregir por el SII engine** (`App.SIIEngineNotaCredito`): en "Corregir", los documentos del
canal SII engine tienen "anular": el portal pre-construye la nota de crédito del documento
(receptor e ítems tal cual, `siiengine.PrepararNCAnulacionDesdePortal`), el total se contrasta
con el XML registrado, el SII la valida en seco y la app muestra la vista previa. El botón de
emitir aparece solo con la cadena 61 verificada desde Go. Los del motor propio siguen por el
panel web.

## El motor Go dentro de la app (fase 7, paso 9 — 2026-10-11)

La app ya no arranca Python: `app/motor.go::iniciarGo` levanta `nucleo/servidor` **en el mismo
proceso**, en un puerto libre de 127.0.0.1, con la clave efímera `APP_SHELL_KEY`; `App.API`
sigue hablándole por HTTP, así que la interfaz y el puente del navegador no cambian. Sin Python,
sin PyInstaller, sin procesos hijos.

- **Desarrollo** (hay repo al lado): usa el `.env`, la base y el `storage/` del repo (las rutas
  relativas del `.env` se resuelven desde la raíz del repo, como hacía uvicorn con su cwd).
- **Empaquetado** (sin repo, o con `DTE_DATOS=<carpeta>`): la carpeta de datos del usuario
  (`~/Library/Application Support/DTE Chile`, `%AppData%`, `~/.config`), con el `.env` creado por
  la app la primera vez (secretos generados ahí; la `ADMIN_PASSWORD` se muestra al pulsar
  "Abrir el panel", no en Inicio). El
  servidor Go crea el usuario `admin` en el primer arranque con esa clave (`asegurarAdmin`,
  lo mismo que hacía `main.py`).
- **Panel web**: "Abrir el panel" abre las páginas del panel (`/certificados`, `/documentos`,
  `/apikeys`, `/onboarding`), que el motor Go sirve igual que Python (copias en
  `nucleo/servidor/static/`); también está `/app/` (esta misma interfaz, en el navegador). Se
  entra con `admin` y la clave del panel, que la app muestra (y copia) justo antes de abrirlo.
- `DTE_MOTOR=python` vuelve al sidecar de antes (uvicorn del repo o el motor PyInstaller del
  bundle), para comparar durante la transición. `DTE_MOTOR_PYTHON=http://…` hace que el Go
  reenvíe a ese Python lo que no tenga (hoy: nada de la API; sí el buscador público `/consulta`).
- Gate: `app/motor_test.go::TestMotorGoEnProceso` arranca el motor sobre una carpeta de datos
  vacía y comprueba `.env`, base, admin, clave efímera (401 sin ella), `/app/` y una boleta de
  práctica con su PDF, todo sin Python.

## La misma app en Tauri, con el motor Rust (fase 8, bloque 5 — 2026-10-12)

`app-rs/` es la misma app con otro cascarón: **Tauri 2** en vez de Wails, y adentro el motor
**Rust** (`nucleo-rs/`, el que pasa el contrato dorado 203/203 contra Python) en vez del Go.
La interfaz es exactamente la misma carpeta (`app/frontend/dist`): `tauri.js` define los 12
bindings `window.go.main.App.*` sobre los comandos de `app-rs/src/app.rs`, así que `app.js`
no sabe en qué cascarón corre (en Wails los define Go; en el navegador, `puente.js`). Mismos
modos (repo en desarrollo, carpeta de datos empaquetada, `DTE_API_URL` externo), misma clave
efímera, mismo `--mcp` para la IA, mismo evento `motor`.

```bash
cd app-rs && cargo test                      # motor Rust en proceso sobre carpeta vacía + app como MCP
cargo tauri build --bundles app              # target/release/bundle/macos/DTE Chile.app (≈14 MB)
```

Gates en `tools/prueba_final.sh`: `app_rs_clippy`, `app_rs_test` (y `app_rs_tauri` con `--app`).
**La Wails sigue siendo la que se publica** hasta que la Tauri pase las mismas pruebas manuales
(tour, capturas, "Tu IA" desde Claude Desktop) y tenga firma y notarización. Detalle en
[`../app-rs/README.md`](../app-rs/README.md).

## Empaquetado: la app con el motor adentro

```bash
cd app && ./empaquetar-mac.sh      # build/bin/DTE Chile.app (motor Go adentro, universal; ~20 MB), sin repo ni .venv
IDENTIDAD="Developer ID Application: …" ./firmar-mac.sh   # firma y notarización (opcional)
```

- El motor es `nucleo/servidor` compilado dentro del binario (los XSD van embebidos en
  `nucleo/xsd`). Solo con `DTE_MOTOR_PYTHON_BUNDLE=1` se agrega además el motor Python
  congelado (`motor.spec` + `motor_embebido.py`, PyInstaller) a `Contents/Resources/motor/`,
  que se usa únicamente con `DTE_MOTOR=python`.
- Sin repo al lado, el cascarón trabaja en **la carpeta de datos del usuario**:
  `~/Library/Application Support/DTE Chile` (macOS; `%AppData%` / `~/.config` en los otros).
  Ahí viven `.env`, `dte_database.db`, `storage/` y `logs/`. Dentro del paquete no se escribe nada.
- La primera vez, el cascarón crea el `.env` con secretos generados ahí mismo (`JWT_SECRET_KEY`,
  `DTE_MASTER_KEY` del keystore) y una `ADMIN_PASSWORD` para el panel web, que Inicio muestra.
  Si el `.env` ya existe no se toca: es la configuración del usuario.
- Con repo al lado (desarrollo), la app usa el `.env`, la base y el storage del repo.
- Para Windows y Linux basta `wails build` de esa plataforma: el motor va en el mismo binario.
- Verificado 2026-10-05: la app empaquetada arrancó desde una carpeta de datos vacía, creó
  `.env`, base y logs, y la simulación completa (firma, XSD, PDF con timbre) funcionó.

## Claves del SII en la app (canal gratuito)

La primera acción real del gratuito en la app es **"Traer lo emitido en el SII"** (Inicio,
empresas que no emiten con motor propio). Antes de hacerla, un diálogo pide el RUT de la
persona autorizada, su clave tributaria y, para bajar el XML, la del certificado, y explica
para qué se usan. Viven en memoria de la app (`clavesSesion`) hasta cerrarla. Con la casilla
"Recordar en este equipo" se mandan con `recordar: true` y el motor las cifra en el keystore
(ver `docs/MIPYME.md`, sección Claves). Nunca se muestran de vuelta. Desde la fase 6, el que
entra al SII es el propio cascarón (Go); las claves recordadas las recibe del motor por la
conexión local, en memoria, y no las escribe en ningún lado.

## Navegador o app: una interfaz, dos envases (2026-10-09)

La interfaz (`app/frontend/dist`, HTML y JS planos) corre igual en la **app instalada** (Wails:
binario Go + vista web del sistema, sin Chromium adentro) y en el **navegador**, servida por el
propio motor en `/app`. Lo que la ata al cascarón son seis bindings (`Estado`, `API`, `Bytes`,
`Guardar`, `EmitirNucleo`, `SIIEngine*`); `puente.js`, cargado antes que `app.js`, los define
sobre HTTP cuando no hay cascarón: inicio de sesión con usuario y clave del motor (JWT en
`sessionStorage`), descargas por el navegador, panel en otra pestaña, y "Traer lo emitido"
por el endpoint Python. Lo que es propio del cascarón (emitir con el núcleo Go, cobrar y anular
por el SII engine en el proceso) avisa que hace falta la app instalada.

**Para qué cada uno.** La app instalada es el camino principal: es lo que la gente entiende
como "un programa", y es donde viven certificados, claves y emisión real. El navegador es el
mismo producto sin instalar, pensado para una sala de clases: cada alumno abre
`http://<motor>/app`, entra, practica con EMPRESA DEMO SPA y recorre el mismo tour. En el
servidor de mediaplex (`docs/…/despliegue`) basta el motor actualizado para tenerlo.

## Interfaz y tour guiado (2026-10-09)

Estructura (reordenada 2026-10-12 a **cuatro ítems**, como una app de teléfono): **barra
lateral** con Inicio, Cobrar, Documentos y Aprender, y abajo "Tu camino" resumido en una línea
(etapa en curso y barra de avance; el detalle vive en **Guía** y en Aprender); **cabecera** con
la empresa activa, el semáforo del mundo (práctica / pruebas del SII / real) y el engranaje
**Ajustes** (Tu IA, Valores, panel del motor, detalles técnicos); y el contenido en tarjetas.
Documentos tiene dos pestañas, **Todos** y **Mi mes**, y cada fila corregible lleva **anular**:
Corregir dejó de ser una pantalla aparte (`#corregir` y `#mes` siguen llegando al mismo lugar).

**Lenguaje visual tipo umbrelOS** (objetivo fijado en el chat el 2026-10-12: moderno y amable, que
la interfaz no sea un obstáculo, nada de "app corporativa"): `app.css` es un solo tema oscuro
sobre un fondo de colores suaves (`.fondo`, gradientes radiales que respiran), paneles de vidrio
translúcido (`backdrop-filter`), **dock** fijo abajo con los cuatro ítems y Ajustes (`.dock`,
punto blanco bajo el activo), íconos en baldosas con gradiente (`.ico`), botón primario blanco en
píldora, diálogos y tarjetas del tour más opacos (`--panel`) para leer bien. Las clases son las
mismas, así que `app.js` y `tour.js` no dependen del tema; `index.html` cambió a cabecera +
contenido + dock (ya no hay barra lateral). Los íconos son SVG de trazo propios (`ICONOS` en
`app.js`, inline en el dock), iguales en todos los sistemas; el selector de empresa aparece
recién con la primera empresa real; las etapas 4 y 5 del camino se llaman "Emitir con el SII" y
"Tu propio sistema" (en `docs/aprender/00-plan.md` conservan sus títulos largos). Tokens de color en
`app.css` (`:root`), modo oscuro automático, estados vacíos, foco visible. Sin dependencias.

**Tour por etapas** (`app/frontend/dist/tour.js`), pensado como primera introducción para
alumnos de colegio, al estilo de los tours de Google: bienvenida la primera vez ("Empezar el
recorrido" / "Explorar por mi cuenta"), tarjeta con flecha hacia el elemento iluminado (recorte
con anillo que late; la primera colocación es instantánea, entre pasos se desliza), puntos de
progreso, teclado (Enter/→, ←, Esc) y tarjeta de cierre al completar una etapa. **Decir que no
se respeta** (revisión de UI 2026-10-12): "Ahora no" en una pista automática, o "Explorar por mi
cuenta" en la bienvenida, apaga las pistas automáticas (se vuelve desde Guía); "Salir" en un
recorrido solo lo cierra. Ninguno marca pasos como vistos, así que el avance cuenta lo
recorrido de verdad. Las etapas son
los cinco tramos de `docs/aprender/00-plan.md`. Cada etapa tiene pasos que apuntan a algo de
una pantalla o explican un concepto. Es
**progresivo**: al entrar por primera vez a una pantalla aparecen solo los pasos de esa
pantalla de la etapa en curso; cuando se completan todos los de la etapa, pasa a la siguiente.
Desde **Guía** se ve el camino completo y se puede recorrer o repetir cualquier etapa (el tour
navega solo por las pantallas). Las etapas 2, 3 y 5 llevan además una lista de verificación
en Aprender (trámites que hace la persona, no la app). El avance y las casillas quedan en
`localStorage` de ese equipo ("No mostrar pistas automáticas" lo apaga; "Empezar de cero" lo
borra). `app.js` avisa al tour después de pintar cada pantalla (`Tour.alEntrar`), y las
tarjetas que el tour señala llevan `data-tour="…"`.

## Pantallas (v0.1)

| Pantalla | Qué hace hoy | Endpoints |
|---|---|---|
| Inicio | estado del motor, la empresa activa (práctica o real) con su etiqueta, tres acciones, 'empezar de nuevo' en práctica; lo técnico (motor, carpeta) plegado en "Detalles técnicos" y sin clave a la vista | `/`, `keystore/negocios`, `simulacion/estado` |
| Cobrarle a alguien | boleta/factura, monto con o sin IVA, cálculo en vivo; lo raro (sin IVA, monto **en UF** convertido con la UF del día) plegado en "Más opciones"; **"Revisar y emitir" abre una revisión real** (de, para, qué, neto/IVA/total, mundo) antes de emitir en práctica o con el núcleo (empresa real), y abre el visor | `simulacion/emitir`, `dte/emisor`, `keystore/…/contexto-emision`, `dte/documentos/{id}/pdf` |
| Documentos · Mi mes (pestaña) | selector de mes en castellano (últimos 24, se recalcula al cambiar), suma vendido/IVA/total por empresa (las NC restan), recordatorio de "sin movimiento" | `dte/documentos` |
| Documentos · anular (en cada fila) | en práctica anula con NC; en el gratuito del SII, por el SII engine; motor propio, próxima versión | `dte/documentos`, `simulacion/anular` |
| Ver | visor de PDF embebido con las partes explicadas, guardar PDF/XML, anular (práctica) | `dte/documentos/{id}/pdf` |
| Documentos · Todos | la empresa activa, ver/guardar PDF y XML con diálogo del sistema, anular | `dte/documentos`, `/pdf`, `/xml` |
| Ajustes (engranaje) | Tu IA, Valores, Panel del motor (muestra y copia la clave), Detalles técnicos | — |
| Valores | UF, UTM y dólar a cualquier fecha desde 2015 (se recalcula al cambiar la fecha) y tabla mensual por año (inicio y fin de mes); fechas en castellano; el histórico se carga una vez al arrancar, el año en curso cada día | `valores`, `valores/historico` |
| Aprender | los cinco tramos del curso (solo índice) | — |

Si la empresa elegida no emite con el motor propio (gratuito del SII u otro software), "Cobrar"
lo dice y manda al panel web; no intenta emitir.

Los cuadros de confirmación son propios de la app (`dialogo()` en `app.js`), no el `confirm()`
del sistema: mismo estilo, Esc para volver, y en lo real el botón de emitir va en rojo.

## Desarrollo

```bash
go install github.com/wailsapp/wails/v2/cmd/wails@latest   # una vez
cd app
wails dev                      # recarga en caliente; el motor Go arranca en el mismo proceso
wails build -platform darwin/arm64 -s     # build/bin/DTE Chile.app
wails build -platform darwin/universal    # Intel + Apple Silicon
```

La interfaz está en `app/frontend/dist` directamente (sin bundler, sin `npm install`). Los
bindings `app/frontend/wailsjs` los genera Wails y no se versionan.

Registro del motor arrancado por la app: `logs/app-motor.log`.

## Pendientes

1. **Emitir y anular por el SII engine desde la app**: Cobrar y Corregir ya validan contra el
   SII (dry-run) y emiten cuando la cadena esté verificada desde Go (`CadenasVerificadas`), que
   espera la primera corrida real por el CLI `nucleo-siiengine factura` + `nc-anular`.
2. **Nota de crédito desde "Corregir"** por el total registrado del documento.
3. **Datos del emisor por negocio** en BD (giro, actividad, dirección) en vez de `EMPRESA_*`
   del `.env`; hoy solo la empresa del `.env` puede emitir con el motor propio.
4. Cargar las lecciones largas y el quiz (`docs/aprender/`) en la pantalla Aprender (el tour y
   las listas de verificación ya están), enlazados al
   modo práctica (que ya existe).
5. **Instalador**: hecho para macOS (motor Go dentro del binario, carpeta de datos, `.env`
   generado). Falta: builds Windows/Linux, universal (Intel) y un DMG.
