# `nucleo-rs/`: el núcleo en Rust (fase 8 del port)

La forma final del motor, transcrita desde `nucleo/` (Go) módulo por módulo y juzgada por los
mismos gates que no saben en qué lenguaje está lo que los pasa (`docs/PLAN-PORT.md`, fase 8).
Ya pasa todo (contrato dorado Python vs Rust 203/203, esquema 23/23, set de certificación 16/16, MCP) y es
el motor que va adentro de **Faro**, la app que se publica (`app-rs/`). Python sigue siendo la referencia
que fija el comportamiento; Go, la otra implementación completa, se mantiene en paridad mientras dura la transición.

```bash
cd nucleo-rs && cargo test && cargo clippy --release --all-targets -- -D warnings && cargo build --release
cd .. && .venv/bin/python test_dorado.py --port nucleo-rs/target/release/nucleo-dorado   # 15/15 byte a byte
.venv/bin/python tools/esquema_dorado.py --go nucleo-rs/target/release/nucleo-servidor   # la base: 23/23
# el servidor, con el mismo contrato que Python y que Go (mismos flags que nucleo/bin/nucleo-servidor):
nucleo-rs/target/release/nucleo-servidor servir --puerto 8012 --motor http://127.0.0.1:8000
APP_SHELL_KEY=… .venv/bin/python tools/contrato_api.py --python http://127.0.0.1:8000 --go http://127.0.0.1:8012   # 203/203
nucleo-rs/target/release/nucleo-mcp            # el MCP (stdio), igual que nucleo/bin/nucleo-mcp
```

Todo junto, con los gates de Go y Python: `./tools/prueba_final.sh` (gates `rust_*`, `corpus_rust`,
`esquema_rust`, `contrato_rust`, `mcp_rust`).

| módulo Rust | transcribe | gate | estado |
|---|---|---|---|
| `totales` | `nucleo/totales` | corpus dorado (`totales.json`) | hecho 2026-10-12 |
| `ted` | `nucleo/ted` | corpus dorado (`ted.xml`) | hecho 2026-10-12 |
| `c14n` | `nucleo/c14n` | corpus dorado (digest y firma del DTE y del sobre) | hecho 2026-10-12 |
| `xmlgen` | `nucleo/xmlgen` | corpus dorado (`dte.xml`) | hecho 2026-10-12 |
| `firma` | `nucleo/firma` | corpus dorado (`dte.xml`, `envio.xml`) | hecho 2026-10-12 |
| `bin/nucleo-dorado` | `nucleo/cmd/nucleo-dorado` | `test_dorado.py --port` | 15/15 |
| `xsd` | `nucleo/xsd` | paridad con lxml (`testdata/vectores.json.gz`) | 1070/1070 |
| `pdf417` | `nucleo/pdf417` | filas idénticas a pdf417gen (`testdata/pdf417.json`) | 48/48 |
| `pdf` + `bin/nucleo-pdf` | `nucleo/pdf` | texto idéntico al PDF de Go, timbre píxel a píxel | hecho 2026-10-12 |
| `almacen` | `nucleo/almacen` | misma migración; folio atómico | hecho 2026-10-12 |
| `certificacion` | `nucleo/certificacion` | 16 sobres del set byte a byte | 16/16 |
| `sii` | `nucleo/sii` | semilla firmada SOAP y REST byte a byte | hecho 2026-10-12 |
| `rvd` | `nucleo/rvd` | ConsumoFolios sin firmar y firmado byte a byte | hecho 2026-10-12 |
| `rcv` | `nucleo/rcv` | normalización, payload, F29 == esperado de Python | hecho 2026-10-12 |
| `portal` | `nucleo/portal` | parsers y onboarding == esperado de Python | hecho 2026-10-12 |
| `siiengine` | `nucleo/siiengine` | payloads y cuerpo de envío == evidencias reales | hecho 2026-10-12 |
| `emision` | `nucleo/emision` | contrato dorado (`/dte/emitir`, `/dte/previsualizar`, práctica) | hecho 2026-10-12 |
| `servidor` + `bin/nucleo-servidor` | `nucleo/servidor` (94 rutas, JWT, passlib `sha256_crypt`, Fernet, RVD, buscador público, `/app`) | esquema dorado 23/23; contrato dorado Python vs Rust 203/203 (`tools/contrato_api.py`) | hecho 2026-10-12 |
| `mcp` + `bin/nucleo-mcp` | `nucleo/mcp` | 20 tools; stdio y Streamable HTTP; dos motores sobre la misma base | hecho 2026-10-12 |
| `conectores`, `valores`, `cliutil` | `nucleo/conectores`, `nucleo/valores`, `nucleo/cliutil` | tests portados de Go | hecho 2026-10-12 |
| `bin/nucleo-{emitir,cafs,rvd,valores,sii,portal,keystore,certificacion,siiengine}` | `nucleo/cmd/*` | set de certificación Go == Rust byte a byte (16/16) | hecho 2026-10-12 |

**Dependencias** (sin OpenSSL): `rsa` + `sha1` (RSA-SHA1 PKCS#1 v1.5), `p12-keystore`
(PKCS#12 con PBES2/AES), `x509-cert` (CN y SAN del certificado), `quick-xml` (lector para la
C14N y el XSD), `regex`, `serde_json`, `base64`, `flate2` (streams del PDF y PNG), `ureq` con
`rustls` (HTTP, incluido TLS de cliente para el portal), `rusqlite` con SQLite embebido,
`tiny_http` (el servidor), `hmac` + `sha2` (JWT HS256, Fernet, `sha256_crypt`), `aes` + `cbc`
(Fernet) y `rand`. `Cargo.lock` fija las versiones.

**Lo que el servidor repite de Go sin librería**: el enrutador con los patrones de
`http.ServeMux` (`GET /x/{id}`, `{$}`, prefijos), multipart y urlencoded, `sha256_crypt` de
passlib (verifica y produce los mismos hashes, 535.000 rondas), Fernet compatible con
`cryptography` (lo que cifra uno lo lee el otro), JWT HS256, el certificado autofirmado de la
práctica en DER a mano, la hora local por `localtime_r` de libc (las marcas de la base y los
TmstFirma salen en la hora del equipo, como Python y Go).

**Reglas que se repiten de Go**: las claves de los CAF son RSA de 512 bits (formato del SII) y
se firman igual; todo lo que ve el SII sale en ISO-8859-1; si Rust "necesita" otro byte, Rust
está mal (L15).
