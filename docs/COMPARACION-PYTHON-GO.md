# Antes y después: motor Python vs núcleo Go

Medido el 2026-10-11 en el mismo Mac, los dos motores arrancados a la vez sobre
**una copia** de `dte_database.db`, con la misma clave y los mismos endpoints.
Carga: 300 peticiones por ruta con 8 clientes en paralelo (60 con 4 para las
emisiones). Python = `uvicorn main:app` (1 proceso, sin workers). Go =
`nucleo-servidor servir`. Los números son de una corrida; sirven para ver el
orden de magnitud, no para un benchmark formal.

## Recursos

| | Python (antes) | Go (después) | factor |
|---|---|---|---|
| Instalación necesaria | venv 437 MB + Python 3.14 | 1 binario de 19 MB | 23× menos |
| App de escritorio (`.app`) | 219 MB (PyInstaller) | 17 MB | 13× menos |
| Memoria en reposo (RSS) | 76 MB | 18 MB | 4× menos |
| Memoria tras la carga | 79 MB | 43 MB | 2× menos |
| CPU consumida en la misma carga | 11,0 s | 2,45 s | 4,5× menos |
| Arranque hasta responder `/` | 0,81 s | 0,56 s | parecido |
| Dependencias | 21 directas / 68 paquetes | 2 directas / 15 módulos | |

La memoria de Go sube bajo carga porque su GC es perezoso; vuelve a bajar sola.

## Capacidad (latencia mediana / p95 / rendimiento)

| ruta | Python | Go | factor |
|---|---|---|---|
| `GET /` (health) | 3,7 / 6,0 ms · 2.020 req/s | 1,1 / 2,2 ms · 6.910 req/s | 3,4× |
| `GET /dte/documentos?limite=20` | 18,1 / 24,6 ms · 427 req/s | 3,8 / 6,0 ms · 1.900 req/s | 4,4× |
| `GET /valores` | 15,8 / 19,8 ms · 500 req/s | 1,0 / 4,0 ms · 4.860 req/s | 9,7× |
| `POST /dte/validar-xml` (XSD, 7 KB) | 12,2 / 24,9 ms · 582 req/s | 1,7 / 5,1 ms · 3.410 req/s | 5,9× |
| `GET /consulta/api` (buscador público) | 7,2 / 10,8 ms · 1.060 req/s | 1,0 / 2,3 ms · 6.980 req/s | 6,6× |
| `POST /simulacion/emitir` boleta (firma + PDF) | 184 / 444 ms · 18 req/s | 9,5 / 15,6 ms · 389 req/s | 21× |
| `POST /simulacion/emitir` factura (firma + PDF) | 159 / 206 ms · 25 req/s | 9,1 / 11,7 ms · 426 req/s | 17× |

Sin errores en ninguna ruta, en ninguno de los dos. La diferencia grande está en
la emisión: Python paga ReportLab + lxml + un GIL que serializa a los 4
clientes; Go firma y dibuja el PDF en ~9 ms y usa todos los núcleos.

Lo que esto significa en la práctica: una caja o un POS que emite una boleta por
venta nunca va a notar la diferencia (ambos responden antes de que la impresora
termine). Donde sí cambia es en la boleta masiva, el RVD diario, los lotes de
certificación y cualquier máquina chica (Raspberry, VPS de 512 MB, el mediaplex):
el motor Go cabe donde el Python no.

## Lo que ganamos

- **Un solo binario por herramienta**, sin Python, sin venv, sin PyInstaller.
  La app corre el motor en proceso (`app/motor.go`); el servidor en mediaplex es
  un `cp`.
- **El mismo contrato HTTP**: 94 rutas en Go contra 76 en Python (todas las de
  Python más las del portal con keystore, `enviar-keystore`, RVD y el buscador).
  Verificado por `tools/contrato_api.py` (203 pasos) y el corpus dorado (15/15
  byte a byte).
- **Validación XSD propia** (`nucleo/xsd`) sin libxml2, con 1.070 vectores que
  reproducen las rarezas de lxml. En Python dependía de la versión de lxml
  instalada.
- **Concurrencia real**: sin GIL, un `BEGIN IMMEDIATE` por folio sigue siendo la
  única serialización.
- **Herramientas del operador en Go**: certificación, CAFs, portal, keystore,
  RVD, SII, MCP (20 tools, stdio y HTTP). Una sola forma de cargar el
  certificado (`cliutil.CargarCertificado`) y de pedir la clave (Llavero → env →
  prompt oculto).
- **Gates automáticos**: 1.336 líneas de tests Go, vectores por paquete, y
  `tools/prueba_final.sh` con 11 gates que corren también en CI sin red.
- **Tipos y errores explícitos** (`emision.Error`, `sii.ErrRespuesta`) donde
  Python lanzaba `ValueError` y lo envolvía en 502.

## Lo que quedó distinto, y la decisión sobre cada cosa (2026-10-11)

- **Swagger / ReDoc**: Go no sirve `/docs` ni `/redoc` ni `openapi.json`. La
  referencia de rutas vive en `nucleo/README.md` y `docs/PLATAFORMA.md`.
  **Decisión: no hace falta que exista en Go.** (El health sigue diciendo
  `"documentacion": "/docs"` porque el contrato dorado lo compara con Python.)
- **PDF**: el de Go es equivalente en contenido (timbre PDF417 verificado con
  vectores), pero no es byte a byte el de ReportLab. Fuentes, kerning y
  márgenes son los de la librería Go. **Decisión: no necesita ser igual.** El
  SII solo valida el XML; el PDF es la representación impresa para el receptor,
  y lo que importa de ella es el timbre, que sí está verificado.
- **MCP por HTTP**: es el transporte *Streamable HTTP* de la especificación
  (2025-06-18) en su forma sin estado: `POST /mcp` responde JSON, `202` a las
  notificaciones, `405` a `GET`/`DELETE` (no abre streams del servidor ni
  sesiones, ambas opcionales), valida `Origin` contra DNS rebinding y negocia
  `MCP-Protocol-Version`. Claude Code lo conecta con `--transport http` y lo
  reporta `Connected` (`nucleo/mcp/mcp_test.go::TestHTTPStreamable`). Lo que
  no tiene es SSE para mensajes iniciados por el servidor, que ninguna
  herramienta nuestra necesita. **Decisión: así está bien**; OAuth para los
  clientes en la nube se monta encima cuando toque.
- **Despliegue en mediaplex**: sigue con la imagen Docker de Python
  (`Dockerfile` parte de `python:3.12-slim`). **Decisión: por ahora se queda
  así**; pasar al binario Go es un cambio pequeño cuando se quiera.
- **Scripts de investigación en Python** que no se portaron a propósito:
  `verificar_sii.py`, `crear_caf_mock_61.py`, `reenviar_certificacion.py`,
  `diagnostico_cert*.py`, `fase3_envio.py`, `motor_embebido.py`. Son de un uso
  y siguen funcionando con el venv.
- **Python sigue siendo la referencia**: `main.py` y `core/` se mantienen para
  los gates de paridad (L15). Hay dos implementaciones que mantener hasta que
  Rust (fase 8) reemplace a Go y Python pase a ser solo corpus.
- **Más líneas**: 18.495 líneas de Go contra 13.816 de Python para lo mismo y
  un poco más. Go es más verboso; el código lo lee la IA, el humano lee docs y
  gates (`docs/PLAN-PORT.md`).
- **Ecosistema**: lxml, ReportLab, cryptography, httpx y FastAPI son librerías
  maduras con miles de usuarios. En Go reimplementamos XSD, C14N, PDF417 y el
  PDF; están cubiertos por vectores, pero el radio de lo probado es el corpus,
  no el mundo.
- **Lo no verificado aún desde Go contra el SII vivo** (no es pérdida, es
  deuda): la corrida real del SII engine, una boleta por REST y un RVD
  aceptado. Los comandos están en `docs/PLAN-PORT.md`; las lanzas tú.

## Cómo repetir la medición

```bash
# copia de la BD + dos motores, misma clave
S=/tmp/bench; mkdir -p $S/storage; cp dte_database.db $S/db.sqlite
export APP_SHELL_KEY=$(openssl rand -hex 16) DATABASE_URL=sqlite:///$S/db.sqlite \
       STORAGE_PATH=$S/storage RVD_SCHEDULER_ACTIVO=false
.venv/bin/uvicorn main:app --port 8771 &
nucleo/bin/nucleo-servidor servir --puerto 8010 --db $S/db.sqlite --motor "" &
ps -o rss=,cputime= -p <pid>        # memoria y CPU
```

La carga se hizo con un script de 40 líneas (urllib + ThreadPoolExecutor) que
llama `/simulacion/reiniciar` y después cada ruta N veces con C hilos. No está
en el repo para no sumar otra herramienta; la tabla de arriba es el resultado.
