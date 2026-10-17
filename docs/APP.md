# Faro, la app de escritorio (`app-rs/` y `app/`)

**Faro** es la app que se publica: **Tauri 2 con el motor Rust** (`app-rs/`, sección más abajo)
adentro, en el mismo proceso. Existe también la construcción en **Go + Wails v2** (`app/`) con
el motor Go (`nucleo/servidor`) adentro, igual de completa, que se mantiene como alternativa
mientras dura la transición. Las dos usan **la misma interfaz** (`app/frontend/dist`, HTML/CSS/JS
sin framework) y los mismos 18 bindings. El proyecto va de servidor + panel web a app fácil de
usar; la versión web (`/app`, servida por cualquier motor) queda para la sala de clases.

La idea de producto está en [`aprender/00-plan.md`](aprender/00-plan.md): una app para quien no
sabe nada de finanzas, con un dock de cuatro ítems (**Inicio, Emitir, Documentos, Aprender**) más
Ajustes, y un semáforo que dice siempre en qué mundo estás (práctica / pruebas del SII / real).

> Historia: la Wails arrancaba el motor Python como sidecar (el diagrama de abajo es de esa
> época, se conserva como registro; con `DTE_MOTOR=python` todavía puede, para comparar). Desde
> la fase 7 (2026-10-11) lleva el motor Go en proceso, y desde la fase 8 (2026-10-12) la Tauri
> lleva el Rust.

## Cómo funcionaba con Python como proceso hijo (registro histórico, hasta la fase 7)

> Todo lo de esta sección es de la época del sidecar Python. Hoy el motor va **en el mismo
> proceso** (Go en la Wails, Rust en la Tauri): no hay uvicorn, ni SIGINT, ni raíz del repo
> obligatoria. Lo que sigue vigente de aquí es la idea de la **clave efímera** y el **modo externo**.

```
Faro.app (Go)                              motor (Python, main.py)
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
  `main.py` + `core/`. (Hoy, sin repo, la app usa la carpeta de datos `Faro`; ver más abajo.)

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

Cuando la empresa elegida emite con el motor propio, "Emitir" **no** llama a
`/dte/emitir`: el cascarón firma y persiste con el núcleo (Go en `app.go::EmitirNucleo`, Rust en
`app-rs/src/app.rs::emitir_nucleo`; el mismo núcleo que reproduce el corpus dorado byte a byte y
cuyo T34 el SII aceptó). La secuencia, tal como se escribió en la fase 4 (hoy el PDF y la
práctica también están en Go y en Rust, ver `nucleo/README.md`):

1. `GET /api/v1/keystore/negocios/{id}/contexto-emision` → el motor descifra el certificado
   del keystore y lo entrega en PEM **en memoria por la conexión local**, junto con la
   resolución del emisor para su ambiente y las rutas absolutas de la base y del storage.
   La clave privada viaja una vez por emisión y no se escribe en ningún lado.
2. `nucleo/emision.Emitir` sobre la misma base (folio atómico) y el mismo storage: mismas
   rutas y la misma fila que Python.
3. `POST /api/v1/dte/documentos/{id}/pdf` → el motor dibuja el PDF desde el XML firmado
   (en la fase 4 lo hacía Python con `core/dte_xml.py`; hoy lo hacen `nucleo/pdf` y `nucleo-rs/src/pdf`).

(Lo anterior describe la fase 4. Desde la fase 7 el keystore, el PDF, el envío al SII, RCV, F29 y
la práctica están también en Go, y desde la fase 8 en Rust; Python sigue como referencia.)

### El SII engine en Go dentro de la app (fase 6 del port)

"Traer lo emitido en el SII" ya no pasa por `/api/v1/mipyme/sincronizar`: el cascarón corre
`nucleo/siiengine` en su propio proceso (`app/siiengine.go::SIIEngineSincronizar`). Secuencia:
`GET /api/v1/mipyme/contexto-siiengine/{rut}` (las claves **recordadas**, descifradas del
keystore, y las rutas de la base y del storage; mismo modelo de confianza que contexto-emision)
→ si la persona marcó recordar, `PUT /api/v1/keystore/claves-sii` → sesión, empresa, form,
historial e importación a la misma base. El JS cae al endpoint Python si el binding no existe.

**Emitir por el SII engine** (`app/siiengine.go::SIIEngineFactura`, `app-rs/src/siiengine.rs`): para una empresa que emite
en el sistema del SII, "Emitir" con "Una empresa" + "No lleva IVA" pide giro,
dirección, comuna y ciudad del cliente (el portal los exige), pide las claves, y hace un
**dry-run real**: el SII valida el documento y la app muestra la vista previa sin gastar folio.
El botón "Emitir de verdad" solo aparece cuando `siiengine.CadenasVerificadas` tiene la
factura, es decir, después de la primera corrida real desde Go: la interfaz **no** puede aceptar
el riesgo de folio por la persona (ley L10). Hasta entonces, el CLI `nucleo-siiengine factura`.
Boletas: siguen en eboleta.sii.cl (sin captura, no portado).

**Anular por el SII engine** (`App.SIIEngineNotaCredito`): en Documentos, con "anular" en la fila, los documentos del
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
  (`~/Library/Application Support/Faro`, `%AppData%`, `~/.config`; la antigua `DTE Chile` se
  renombra sola la primera vez), con el `.env` creado por
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
La interfaz es exactamente la misma carpeta (`app/frontend/dist`): `tauri.js` define los 15
bindings `window.go.main.App.*` sobre los comandos de `app-rs/src/app.rs`, así que `app.js`
no sabe en qué cascarón corre (en Wails los define Go; en el navegador, `puente.js`). Mismos
modos (repo en desarrollo, carpeta de datos empaquetada, `DTE_API_URL` externo), misma clave
efímera, mismo `--mcp` para la IA, mismo evento `motor`.

```bash
cd app-rs && cargo test                      # motor Rust en proceso sobre carpeta vacía + app como MCP
cargo tauri build --bundles app              # target/release/bundle/macos/Faro.app (≈14 MB)
```

Gates en `tools/prueba_final.sh`: `app_rs_clippy`, `app_rs_test` (y `app_rs_tauri` con `--app`).
**Esta es la app que se publica como Faro** (2026-10-12): pasó el recorrido guiado completo, la
boleta de práctica, la anulación y las capturas del README. **Firma (2026-10-14)**: `tools/release.sh` detecta el certificado "Developer ID Application" del
llavero y Tauri firma con él (`APPLE_SIGNING_IDENTITY`); la notarización corre sola con el
perfil `cafe-printerd-notary` del llavero (`NOTARY_PROFILE` para otro; se crea una vez con
`xcrun notarytool store-credentials`, credencial del desarrollador, nunca en el repo). Antes de
las sumas, `tools/auditar_release.py` revisa que ningún paquete lleve nada privado. Pendiente: "Tu IA" probado desde la app de Claude. Detalle en [`../app-rs/README.md`](../app-rs/README.md).

## Empaquetado: la app con el motor adentro

```bash
cd app && ./empaquetar-mac.sh      # build/bin/Faro.app (motor Go adentro, universal; ~20 MB), sin repo ni .venv
IDENTIDAD="Developer ID Application: …" ./firmar-mac.sh   # firma y notarización (opcional)
```

- El motor es `nucleo/servidor` compilado dentro del binario (los XSD van embebidos en
  `nucleo/xsd`). Solo con `DTE_MOTOR_PYTHON_BUNDLE=1` se agrega además el motor Python
  congelado (`motor.spec` + `motor_embebido.py`, PyInstaller) a `Contents/Resources/motor/`,
  que se usa únicamente con `DTE_MOTOR=python`.
- Sin repo al lado, el cascarón trabaja en **la carpeta de datos del usuario**:
  `~/Library/Application Support/Faro` (macOS; `%AppData%` / `~/.config` en los otros).
  Ahí viven `.env`, `dte_database.db`, `storage/` y `logs/`. Dentro del paquete no se escribe nada.
- La primera vez, el cascarón crea el `.env` con secretos generados ahí mismo (`JWT_SECRET_KEY`,
  `DTE_MASTER_KEY` del keystore) y una `ADMIN_PASSWORD` para el panel web, que Inicio muestra.
  Si el `.env` ya existe no se toca: es la configuración del usuario.
- **Bóveda con PIN** (2026-10-13, `nucleo-rs/src/servidor/boveda.rs`, solo en el motor Rust): al crear el
  PIN, la clave maestra sale del `.env` y queda en `boveda.json` cifrada con una llave derivada del PIN
  (Argon2id 64 MiB × 3, sal aleatoria). El motor arranca **bloqueado** (`fernet = None`) y todo lo que
  necesite cifrar o descifrar responde **423 `boveda_bloqueada`**; la interfaz lo convierte en la pantalla
  "Escribe tu PIN". Rutas: `GET/POST/PUT /api/v1/boveda`, `POST …/abrir|bloquear|reiniciar`. Autobloqueo por
  inactividad (minutos, 0 = nunca; cualquier petición autenticada menos el sondeo cuenta como uso), 5
  intentos y pausa de 30 s, y el primer envío real de la sesión vuelve a pedir el PIN (`pinParaReal`, en
  `revisar`, las notas reales, los folios en producción y el gratuito). "Olvidé mi PIN" = `reiniciar`:
  borra `certificados` y `claves_sii`, `negocios.cert_id = NULL`, clave maestra nueva en el `.env`, sin
  bóveda; los documentos se quedan. Consecuencias: el MCP por stdio (otro proceso) y los CLI sobre una
  carpeta con bóveda ven 423 en lo que necesite el certificado; lo que no lo necesita sigue. Python y Go
  no la tienen (la interfaz lo detecta por el 404 de `GET /api/v1/boveda`). Modelo de amenaza: protege
  contra copiar la carpeta, no contra un programa corriendo como el usuario con la app abierta; un PIN
  corto se adivina fuera de línea, por eso el mínimo son 6 caracteres y se sugiere una frase.
- Esa carpeta queda **solo para el usuario** (2026-10-13, `cliutil::proteger_carpeta_datos`): 700 la
  carpeta y 600 el `.env` y la base con su `-wal`/`-shm`, al crearla y en cada arranque empaquetado.
  Motivo: el `.env` tiene la clave maestra y la base el certificado y las claves cifradas con ella;
  juntos abren todo, así que otra cuenta del mismo computador no debe poder leerlos. Lo que ya está
  cifrado en la base lo verifica `estado_claves_sii` sin devolver valores; el log del motor solo
  registra método, ruta y estado, nunca cuerpos.
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

## Cuando algo falla: informe local, sin Sentry (2026-10-17)

Se evaluó agregar Sentry (o cualquier reportero de errores en la nube) y se decidió que **no**:
la app promete "nada sale de tu computador", los errores de este dominio llevan RUT, folios y
montos (los mensajes del SII los traen), el público son colegios y en beta cada falla llega mejor
por una persona que escribe con su registro. Si algún día hace falta algo automático, será opt-in
(apagado por defecto) y contra un servidor propio (GlitchTip habla el protocolo de Sentry).

Lo que hay en su lugar, igual en las dos apps (`app-rs/src/informe.rs`, `app/informe.go`):

- **Las caídas quedan en `logs/app-fallas.log`** de la carpeta de datos: un panic de la app Rust
  (hook instalado al arrancar, con versión, sistema y traza) o del hilo principal de la Wails
  (`registrarCaida` diferido en `main`). La interfaz también anota ahí sus propios errores
  (`window.onerror`, promesas rechazadas) a través del binding `RegistrarFalla`, con tope por
  sesión y sin repetidos.
- **Ajustes → "¿Algo no funcionó?" → Informar un problema**: el binding `InformeProblema` arma el
  texto (versión de la app y del motor, sistema, ambiente, últimas 80 líneas de fallas y 120 del
  registro del motor) **con los RUT tachados** (`76.***.***-6`) y las cadenas largas que parecen
  claves tapadas. La app lo muestra completo en un diálogo; los botones son Copiar y "Copiar y
  abrir GitHub" (abre un issue nuevo con el título puesto; la persona pega el informe). Nada se
  envía solo. En el navegador (sin bindings) el informe es el básico: versión, navegador y las
  fallas de la sesión.
- Pruebas: `cargo test informe` (tachado, recorte, informe sin carpeta), `go test -run
  'TestTachar|TestInformeProblema'`, y la prueba sin ventana del diálogo (tarjeta, botones,
  captura de un error provocado).

## Navegador o app: una interfaz, dos envases (2026-10-09)

La interfaz (`app/frontend/dist`, HTML y JS planos) corre igual en la **app instalada** (Tauri o Wails:
binario + vista web del sistema, sin Chromium adentro) y en el **navegador**, servida por el
propio motor en `/app`. Lo que la ata al cascarón son los 16 bindings `window.go.main.App.*` (`Estado`, `API`, `Bytes`, `ElegirArchivo`, `Formulario`, `PedirFolios`,
`Guardar`, `EmitirNucleo`, `AbrirURL`, `AbrirPanel`, `Conectores`, `ConectarIA`, `SIIEngine*`); `puente.js`, cargado antes que `app.js`, los define
sobre HTTP cuando no hay cascarón: inicio de sesión con usuario y clave del motor (JWT en
`sessionStorage`), descargas por el navegador, panel en otra pestaña, y "Traer lo emitido"
por el endpoint del motor. Lo que es propio del cascarón (emitir con el núcleo, emitir y anular
por el SII engine en el proceso) avisa que hace falta la app instalada.

**Para qué cada uno.** La app instalada (Faro: Tauri + Rust, o la Wails + Go) es el camino principal: es lo que la gente entiende
como "un programa", y es donde viven certificados, claves y emisión real. El navegador es el
mismo producto sin instalar, pensado para una sala de clases: cada alumno abre
`http://<motor>/app`, entra, practica con EMPRESA DEMO SPA y recorre el mismo tour. En un
servidor propio basta el motor actualizado (`nucleo-servidor servir`) para tenerlo.

## Interfaz y tour guiado (2026-10-09)

Estructura (reordenada 2026-10-12 a **cuatro ítems**, como una app de teléfono): un **dock**
abajo con Inicio, Emitir, Documentos y Aprender, más Ajustes (Tu IA, Valores, panel del motor,
detalles técnicos); **cabecera** con la marca, la empresa activa (solo si hay una real), el
semáforo del mundo (práctica / pruebas del SII / real) y "Tu camino" como chip (Guía, etapa en
curso y barra de avance; el detalle vive en Guía y en Aprender); y el contenido en tarjetas.
Documentos tiene dos pestañas, **Todos** y **Mi mes**, y cada fila corregible lleva **anular**:
Corregir dejó de ser una pantalla aparte (`#corregir` y `#mes` siguen llegando al mismo lugar).

**Lenguaje visual tipo umbrelOS** (objetivo fijado en el chat el 2026-10-12: moderno y amable, que
la interfaz no sea un obstáculo, nada de "app corporativa"): `app.css` tiene tema oscuro y claro
(más abajo) sobre un fondo de colores suaves (`.fondo`, gradientes radiales que respiran), paneles de vidrio
translúcido (`backdrop-filter`), **dock** fijo abajo con los cuatro ítems y Ajustes (`.dock`,
punto blanco bajo el activo), íconos en baldosas con gradiente (`.ico`), botón primario blanco en
píldora, diálogos y tarjetas del tour más opacos (`--panel`) para leer bien. Las clases son las
mismas, así que `app.js` y `tour.js` no dependen del tema; `index.html` cambió a cabecera +
contenido + dock (ya no hay barra lateral). Los íconos son **ilustrados** al estilo de los de
umbrelOS (2026-10-13): SVG propios de relleno en tres capas (`.s` sombra, `.f` forma, `.a`
acento; `ICONOS` en `app.js`, inline en el dock) sobre baldosas con degradado y brillo (`.ico`,
tonos por `--tono-1/--tono-2`); en el dock el glifo toma el color del texto. El ícono de la app
es un faro de noche con su haz (`app-rs/icons/faro.svg`; de ahí salen `icon.png`, `.icns`,
`.ico` con `cargo tauri icon`, y `app/build/appicon.png` para Wails). Iguales en todos los sistemas; el selector de empresa aparece
recién con la primera empresa real; las etapas 4 y 5 del camino se llaman "Emitir con el SII" y
"Tu propio sistema" (en `docs/aprender/00-plan.md` conservan sus títulos largos).

Hay **tema claro y oscuro** (tokens en `:root`, `prefers-color-scheme` y `data-theme` elegido en
Ajustes → Apariencia, recordado en `localStorage`): salió de una prueba de usuario simulada con
una persona de 72 años a la que el fondo oscuro le cansaba la vista. De esas pruebas (un alumno
de 16 y esa persona, agentes sin contexto mirando capturas) salieron también: "Salir" pausa las
pistas, "Anular este documento", "Mis documentos" en el visor, ejemplos marcados "Ej.:", la
línea "El IVA no es tuyo" bajo los totales y la bienvenida sin género.
El protocolo de la prueba con personas reales y el registro de las simuladas está en
`docs/PRUEBA-DE-USUARIO.md`.

**"Muéstrame"** (2026-10-12): los pasos de acción de la guía (monto, revisar y emitir, anular,
mes) llevan un botón que corre una demo sobre la interfaz real: un cursor fantasma (`.fantasma`)
se mueve, escribe en los campos de verdad (el formulario reacciona), pulsa (se abre el diálogo
real y lo cierra con Volver) y al final restaura los valores y vuelve la tarjeta con "Ahora tú".
Mientras corre, un velo impide pulsar. Las demos son listas de acciones (`DEMOS` en `tour.js`),
sin GIF ni video: siempre en sincronía con la interfaz y nítidas en cualquier tema. `dialogo()`
no cierra el tour mientras `Tour.enDemo()`.

**Entrada y escena** (2026-10-12): `index.html` lleva una escena en SVG (un faro en la costa, de
noche en tema oscuro y de día en claro: colores `--cielo-*`, `--mar-*`, `--haz`…), con el haz
barriendo, olas y estrellas en CSS. Al abrir, la escena se ve nítida con el nombre y "Entrar"
(habilitado cuando el motor está listo; Enter también entra). Al entrar, `html.dentro` desenfoca
la escena (`filter: blur`) y la app aparece encima. El nombre es la constante `MARCA` en `app.js`
(decidido el 2026-10-12: el producto es **Faro**, antes "DTE Chile"); el logo es el mismo faro en trazo. Tokens de color en
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
| Inicio | saludo, la empresa activa (práctica o real) con su etiqueta, tres acciones (Emitir, Mis documentos, Mi mes), 'empezar de nuevo' en práctica; lo técnico vive en Ajustes | `/`, `keystore/negocios`, `simulacion/estado` |
| Emitir una boleta o factura | boleta/factura, monto con o sin IVA, cálculo en vivo; lo raro (sin IVA, monto **en UF** convertido con la UF del día) plegado en "Más opciones"; **"Revisar y emitir" abre una revisión real** (de, para, qué, neto/IVA/total, mundo) antes de emitir en práctica o con el núcleo (empresa real), y abre el visor | `simulacion/emitir`, `dte/emisor`, `keystore/…/contexto-emision`, `dte/documentos/{id}/pdf` |
| Documentos · Mi mes (pestaña) | selector de mes en castellano (últimos 24, se recalcula al cambiar), suma vendido/IVA/total por empresa (las NC restan), recordatorio de "sin movimiento" | `dte/documentos` |
| Documentos · anular (en cada fila) | en práctica anula con NC; en el gratuito del SII, por el SII engine; motor propio, próxima versión | `dte/documentos`, `simulacion/anular` |
| Ver | visor de PDF embebido con las partes explicadas, guardar PDF/XML, anular (práctica) | `dte/documentos/{id}/pdf` |
| Documentos · Todos | la empresa activa, ver/guardar PDF y XML con diálogo del sistema, anular | `dte/documentos`, `/pdf`, `/xml` |
| Ajustes | Mi empresa, Tu IA, Valores, "Tu PIN" (crear/cambiar/bloquear ahora/autobloqueo; 2026-10-13), Apariencia, "Dónde quedan tus claves", Detalles técnicos (con el panel web para integradores) | — |
| Mi empresa (2026-10-12) | tres pasos explicados como a un alumno: (1) certificado digital: diálogo del sistema + clave, se guarda cifrado (bindings `ElegirArchivo` + `Formulario` → `POST keystore/certificados`); (2) empresa: el SII lista las del certificado o se escribe el RUT, ambiente explicado como a un alumno con dos tarjetas, "practicar con el SII" (amarillo: el ambiente de pruebas del SII, nada vale) y "trabajar de verdad" (rojo, con confirmación "Trabajar de verdad" y PIN si hay bóveda) (`GET certificados/{id}/empresas`, `Formulario` → `POST keystore/negocios`), y por cada empresa sus **datos del emisor** (nombre, giro, código de actividad, dirección, comuna, ciudad, correo, teléfono), cada uno explicado, guardados por negocio con `PUT keystore/negocios/{id}` (2026-10-13; antes eran `EMPRESA_*` del `.env`, uno para todo el motor, y se heredan de ahí si coinciden con el RUT); (3) folios: qué es un folio y un CAF, qué tipos autorizó el SII (`GET negocios/{id}/timbraje`) y "pedir 5 folios" (`PedirFolios`: el portal con el certificado, CAF a `storage/cafs` y a la base, guardarraíles anti-acaparamiento; en práctica un aviso explica que son folios del ambiente de pruebas del SII, que no valen y no gastan los reales). Reemplaza al "Abrir el panel" de Inicio | ver fila |
| Valores | UF, UTM y dólar a cualquier fecha desde 2015 (se recalcula al cambiar la fecha) y tabla mensual por año (inicio y fin de mes); fechas en castellano; el histórico se carga una vez al arrancar, el año en curso cada día | `valores`, `valores/historico` |
| Aprender | **Mini academia** (2026-10-13): 23 lecciones en 5 módulos (lo básico, los números del mes, tu empresa, las fechas, los documentos), cada una con un **visual interactivo** propio (`app/frontend/dist/academia-vis.js`, `AcademiaVis.montar(id, contenedor, {valores})`: deslizadores del IVA, balanza débito/crédito, calendario del año, contador de folios, documentos de ejemplo, convertidor UF/UTM con el valor del día, etc.; HTML + SVG sin librerías), y recorrida **por pasos** (2026-10-13, una tarjeta a la vez con puntos de progreso y flechas del teclado): `adivina` (pregunta antes de explicar; al responder se revela el visual), `idea` (dos o tres líneas; `foco` resalta una parte del visual marcada con `data-parte` y los `<b data-vivo="neto|iva|total">` del texto se actualizan con `ctx.cambio` cuando el alumno mueve el visual), ejemplo, `pregunta` (4 opciones, pista por opción equivocada `xo`), `mision` opcional (enlace a una vista; con `check` {tipo|total} la app mira en `GET /api/v1/dte/documentos` si ya está hecha; nunca bloquea) y `cierre` ("lo que te llevas"). Progreso en `localStorage` (`academia.v1`), barra y "Seguir: …". Datos en `app/frontend/dist/academia.js` (generado por `tools/academia_datos.py`; gate `tools/revisar_academia.py`, que con `--md` escribe `docs/aprender/LECCIONES.md`). Debajo, el camino de cinco etapas (tours) | `#leccion?id=…` |

Si la empresa elegida no emite con el motor propio (gratuito del SII u otro software), "Emitir"
lo dice y manda al panel web; no intenta emitir.

Los cuadros de confirmación son propios de la app (`dialogo()` en `app.js`), no el `confirm()`
del sistema: mismo estilo, Esc para volver, y en lo real el botón de emitir va en rojo.

## Desarrollo

```bash
go install github.com/wailsapp/wails/v2/cmd/wails@latest   # una vez
cd app
wails dev                      # recarga en caliente; el motor Go arranca en el mismo proceso
wails build -platform darwin/arm64 -s     # build/bin/Faro.app
wails build -platform darwin/universal    # Intel + Apple Silicon
```

La interfaz está en `app/frontend/dist` directamente (sin bundler, sin `npm install`). Los
bindings `app/frontend/wailsjs` los genera Wails y no se versionan.

Registro del motor arrancado por la app: `logs/app-motor.log`.

## Pendientes

1. **Emitir y anular por el SII engine desde la app**: Emitir, "anular" y "dejar sin efecto"
   (una NC, con nota de débito; binding `SIIEngineNotaDebito`, 2026-10-13) en la fila ya validan
   contra el SII (dry-run) y emiten cuando la cadena esté verificada desde Go o Rust
   (`CadenasVerificadas`), que espera la primera corrida real por el CLI `nucleo-siiengine
   factura` + `nc-anular` + `nd-anular`.
2. ~~Nota de crédito para documentos del motor propio~~ **hecho 2026-10-13**: desde la fila o el
   visor, "anular" (NC código 1), "cobrar más" (ND código 3, agrega un cobro que faltó) y "dejar
   sin efecto" una NC (ND código 1), para la práctica (`POST simulacion/nota-debito/{id}`, en los
   tres motores) y para el motor propio (`EmitirNucleo` con `referencias`; sin folios de 56/61 la
   app manda a Mi empresa). El original no cambia de estado fuera de la práctica.
3. ~~Datos del emisor por negocio~~ **hecho 2026-10-13**: cada empresa guarda los suyos desde
   Mi empresa (`PUT keystore/negocios/{id}`, en los tres motores); `EMPRESA_*` del `.env` queda
   solo como herencia para instalaciones viejas.
4. ~~Cargar las lecciones y el quiz en la pantalla Aprender~~ **hecho 2026-10-13** (mini
   academia por pasos, ver la fila Aprender). Quedan los videos y escribir a mano las adivinanzas
   y claves de los módulos 2 a 5 (hoy se convierten solos).
5. **Instalador**: hecho para macOS (motor Go dentro del binario, carpeta de datos, `.env`
   generado). Falta: builds Windows/Linux, universal (Intel) y un DMG.
