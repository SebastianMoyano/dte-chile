# 🧾 DTE Chile — facturación electrónica para el SII, libre y para aprender

Motor **self-hosted** que emite **boletas y facturas electrónicas** (DTE) ante el **SII de
Chile**: asigna folio, timbra, firma, arma el sobre, envía por el canal correcto, guarda el
PDF y registra lo que el SII respondió. Viene en dos cuerpos que hacen exactamente lo mismo,
byte a byte: **Python + FastAPI** (la referencia, donde se descubrió cómo funciona el SII) y
**Go** (`nucleo/`, un binario sin dependencias que corre dentro de la app de escritorio y en
cualquier servidor). Licencia **MIT**: gratis, sin garantía.

**En simple**: si tienes una empresa en Chile, este programa emite tus boletas y facturas
directo con el SII, desde tu computador o tu servidor, sin pagar un proveedor. Tú pones tu
certificado digital; él hace el resto. Y si quieres **entender** cómo funciona la facturación
electrónica, el repo está escrito para eso.

> Pensado para **una persona que opera sus propias empresas**, no como servicio multi-cliente.

## Dos puertas

### 🎓 Quiero aprender

El proyecto nació para enseñar facturación electrónica a alumnos de colegio con un programa
real, y se nota en cómo está escrito.

- **La app de escritorio** trae una **empresa de práctica**: todo lo que emites ahí se forma,
  se firma y se timbra como un documento real, pero nunca sale del computador. Un tour te
  lleva de cero a tu primera boleta, sin jerga. [`docs/APP.md`](docs/APP.md).
- **[`docs/INICIO-RAPIDO.md`](docs/INICIO-RAPIDO.md)** y el **[glosario](docs/GLOSARIO.md)**:
  qué es un folio, un CAF, un timbre, un TrackID, en dos líneas cada uno.
- **[`docs/aprender/`](docs/aprender/)**: el plan de lecciones por tramos, con quiz y videos.
- **[`docs/CONSTITUCION.md`](docs/CONSTITUCION.md)**: las leyes del motor. Cada una se pagó con
  días de trabajo o con folios reales; leerlas es la forma más rápida de aprender lo que el SII
  no documenta. Y [`docs/LECCIONES-SII.md`](docs/LECCIONES-SII.md), el diario de errores del SII
  y cómo se resolvieron.
- **El corpus dorado** ([`docs/DORADO.md`](docs/DORADO.md)): quince documentos con su salida
  esperada byte a byte. Sirve para verificar el motor, y sirve como ejercicio: reimplementa
  una parte en el lenguaje que quieras y mide si llegas al mismo byte. Así se portó a Go.

### 🧑‍💻 Quiero usarlo

| Cómo | Para quién |
|---|---|
| **App de escritorio** (macOS; motor Go adentro, sin instalar nada más) | quien factura desde su computador |
| **Binario Go** `nucleo-servidor servir` (macOS, Linux, Windows; un archivo) | un servidor propio, una Raspberry, un VPS chico |
| **Docker** con el motor Python (`docker-compose up -d`) | quien ya opera con contenedores |
| **Tu IA** (Claude Code, app de Claude, Cursor, VS Code, Gemini CLI, Codex): `nucleo-mcp instalar --en …` o la pestaña "Tu IA" de la app | operar la facturación conversando, todo local |

```bash
# Go: un binario, sin Python
cd nucleo && go build -o bin/nucleo-servidor ./cmd/nucleo-servidor
bin/nucleo-servidor servir --puerto 8000        # API en http://127.0.0.1:8000/api/v1

# Python (la referencia): Docker o venv
cp .env.example .env && docker-compose up -d    # Swagger en /docs
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python setup.py && uvicorn main:app --reload --port 8000
```

Guías: [`docs/PLATAFORMA.md`](docs/PLATAFORMA.md) (API e integración),
[`docs/CONECTAR.md`](docs/CONECTAR.md) (tu IA), [`nucleo/README.md`](nucleo/README.md) (los
binarios), [`docs/CERTIFICACION.md`](docs/CERTIFICACION.md) (lo que el SII exige una vez antes
de emitir con software propio; el motor te guía).

## Qué hace

- **Emite factura y boleta** (33/34/39/41/52/56/61): folio → TED → firma → sobre → envío al SII → PDF → base.
- **Firma XMLDSig como el SII la acepta** (RSA-SHA1 + C14N; DTE firmado *standalone* e insertado *verbatim* en el sobre).
- **Envía por el canal correcto**: boletas por REST, facturas y el reporte diario de boletas (RVD) por DTEUpload; resolución de carátula por empresa y ambiente.
- **Repone folios solo** cuando bajan del umbral, y avisa por webhook.
- **Buscador público** `/consulta`, el "link de consulta" que exige el SII, con PDF y XML.
- **PDF con timbre PDF417** (carta y 80 mm térmico).
- **Trae lo emitido en el sistema gratuito del SII** y emite por él (facturas y notas de crédito) para empresas que todavía no tienen software propio.
- **Registro RCV y borrador del F29**: lo que vendiste, el IVA y lo que va a pedir el formulario.
- **Auth por JWT o API key**, keystore de certificados cifrado, rotación de claves, y un **servidor MCP** con 20 herramientas para una IA.

## Cómo se sabe que funciona

Cada pieza nace con su gate automático y todos corren de una vez, sin tocar al SII:

```bash
./tools/prueba_final.sh --sin-red
```

Corpus dorado (15 documentos byte a byte, en Python y en Go), esquema de la base idéntico,
contrato HTTP idéntico entre los dos motores (203 pasos), vectores por paquete (1.070 del
validador XSD, PDF417, portal, RCV, RVD, certificación), la app arrancando el motor en proceso,
el MCP, y la auditoría pública (ni RUTs reales, ni personas, ni secretos, en el árbol ni en la
historia). El mismo workflow corre en GitHub Actions. Contra el SII vivo: facturas, boletas y
notas de crédito aceptadas en certificación y en producción; los detalles, con sus TrackID, en
[`docs/LECCIONES-SII.md`](docs/LECCIONES-SII.md). Antes y después del port, medido:
[`docs/COMPARACION-PYTHON-GO.md`](docs/COMPARACION-PYTHON-GO.md).

## Requisitos

- Un **certificado digital** de persona natural (`.p12`/`.pfx`), el mismo con que entras al SII.
- Una empresa con **inicio de actividades** en primera categoría.
- Para emitir con software propio, el SII exige **certificarse** una vez.

## Autenticación y seguridad

Todo se autentica con `Authorization: Bearer <token>`: **JWT** para la gestión (admin creado
al primer arranque con clave impresa una vez) o **API key** para integraciones (`/apikeys`,
no expira, en la base solo va su hash). Los certificados se cifran en la base y se usan en
memoria. Lo único público es `/consulta`. Qué nunca entra al repo y cómo reportar un problema:
[`SECURITY.md`](SECURITY.md).

## Preguntas típicas

- **¿El voucher de la tarjeta ya cuenta como boleta?** Depende de tu "modelo de emisión", y si
  no declaras nada el SII asume que sí: [`docs/MODELO-EMISION.md`](docs/MODELO-EMISION.md).
- **¿Cómo anulo una boleta?** No se borra: se anula con una nota de crédito.
  [`docs/ANULAR-BOLETA.md`](docs/ANULAR-BOLETA.md).
- **"Debe ingresar con la persona autorizada"…** Entraste con la identidad equivocada (empresa,
  persona o representante): [`docs/IDENTIDADES-SII.md`](docs/IDENTIDADES-SII.md).

## Documentación

[`docs/MAPA.md`](docs/MAPA.md) es el índice de todo. Para contribuir:
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Licencia

**Copyright © 2026 Extralatte.** Distribuido bajo la **licencia MIT**, ver [`LICENSE`](LICENSE).

En palabras simples: **es gratis.** Puedes usarlo, modificarlo, integrarlo en tu producto y
cobrar por él, sin pedir permiso y sin obligación de publicar tus cambios. La única condición es
conservar el aviso de licencia. Si arreglas algo, un *pull request* ayuda a todos los que
facturan en Chile.

**Sin garantía y sin responsabilidad.** Este motor emite documentos tributarios reales. Se
entrega tal cual: **quien lo opera es responsable de lo que emite, declara o envía al SII**, de
verificar los resultados y de cumplir sus obligaciones tributarias. Los autores no responden por
folios perdidos, documentos rechazados, multas ni cualquier otro daño derivado de su uso.

> Las versiones publicadas antes de octubre de 2026 se distribuyeron bajo AGPL-3.0; desde la
> 1.0.0 la licencia es MIT.

## Créditos

El formato de documentos, sobres y reportes se implementó desde las **especificaciones
oficiales del SII** (XSD, instructivos, resoluciones). Se consultó
[**LibreDTE**](https://www.libredte.cl) (© SASCO SpA, AGPL-3.0) como referencia del
comportamiento correcto del SII en varios puntos; este proyecto es una implementación
independiente y no incluye su código.
