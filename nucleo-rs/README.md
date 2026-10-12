# `nucleo-rs/`: el núcleo en Rust (fase 8 del port)

La forma final del motor, transcrita desde `nucleo/` (Go) módulo por módulo y juzgada por los
mismos gates que no saben en qué lenguaje está lo que los pasa (`docs/PLAN-PORT.md`, fase 8).
Python sigue siendo la referencia y Go el producto que se descarga, hasta que esto pase todo.

```bash
cd nucleo-rs && cargo test && cargo clippy --release -- -D warnings && cargo build --release
cd .. && .venv/bin/python test_dorado.py --port nucleo-rs/target/release/nucleo-dorado   # 15/15 byte a byte
```

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

**Dependencias** (sin OpenSSL): `rsa` + `sha1` (RSA-SHA1 PKCS#1 v1.5), `p12-keystore`
(PKCS#12 con PBES2/AES), `x509-cert` (CN y SAN del certificado), `quick-xml` (lector para la
C14N y el XSD), `regex`, `serde_json`, `base64`, `flate2` (streams del PDF y PNG), `ureq` con
`rustls` (HTTP, incluido TLS de cliente para el portal) y `rusqlite` con SQLite embebido.
`Cargo.lock` fija las versiones.

**Reglas que se repiten de Go**: las claves de los CAF son RSA de 512 bits (formato del SII) y
se firman igual; todo lo que ve el SII sale en ISO-8859-1; si Rust "necesita" otro byte, Rust
está mal (L15).
