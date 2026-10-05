# Corpus dorado — la salida del motor, byte a byte

> `test_dorado.py` · `tests/dorado/` · `core/reloj.py`

## Qué es

Un conjunto de **entradas fijas** y las **salidas exactas** que el motor produce con ellas:
el TED, el DTE firmado y el sobre (EnvioDTE / EnvioBOLETA), guardados como bytes. Con hora
fija, certificado fijo y CAF fijos, el pipeline de firma es determinista (RSA-SHA1 con
PKCS#1 v1.5 no tiene azar), así que **la misma entrada produce siempre los mismos bytes**.

Sirve para dos cosas:

1. **Detectar cualquier cambio de salida** del motor Python. Si un refactor mueve un tag,
   cambia un espacio o re-serializa algo, el corpus falla y dice en qué byte. Esto es la
   protección contra la lección más cara del proyecto (`DTE-3-505`, ver CONSTITUCIÓN): la
   firma depende de los bytes exactos.
2. **Probar un port** (Go, Rust, lo que sea) sin tocar al SII. El port lee `entrada.json` y
   los fixtures, y debe escribir exactamente `ted.xml`, `dte.xml` y `envio.xml`. Primero se
   iguala al corpus en local; recién cuando es idéntico en todos los casos se prueba contra
   el ambiente de certificación del SII. En ese orden, nunca al revés.

## Dónde está cada cosa

```
tests/dorado/
├── fixtures/            entradas fijas, ficticias (ley L14), versionadas
│   ├── cert_demo.p12    certificado autofirmado de "Ana" (12345678-5), clave "demo"
│   └── caf_<tipo>.xml   CAF de EMPRESA DEMO SPA (77777777-7) por tipo, folios 1-100
├── casos/*.json         cada caso: tipo, folio, fecha, receptor, ítems, referencias
└── esperado/<caso>/     lo que debe salir: entrada.json, ted.xml, dte.xml, envio.xml, totales.json
```

Constantes fijas del harness: hora `2026-01-15T10:30:00`, resolución `2026-01-01` / `0`,
emisor `EMISOR_DEMO` de `core/simulacion.py`.

## Probar un port externo

```bash
.venv/bin/python test_dorado.py --port "./nucleo/bin/nucleo-dorado"
.venv/bin/python test_dorado.py --port ".venv/bin/python tests/dorado/port_ejemplo.py"   # ejemplo que pasa
```

Por cada caso el runner ejecuta `<comando> <entrada.json> <fixtures/> <salida/>` con
`RELOJ_FIJO`, `DORADO_RESOLUCION_FECHA` y `DORADO_RESOLUCION_NUMERO` en el entorno. El port
escribe `ted.xml`, `dte.xml` y `envio.xml` en `<salida/>`; el runner los compara byte a byte
y reporta el primer byte distinto. `tests/dorado/port_ejemplo.py` es la referencia de qué se
lee y qué se escribe. El plan de port está en [`PLAN-PORT.md`](PLAN-PORT.md).

## Cómo se corre

```bash
.venv/bin/python test_dorado.py              # compara; falla y muestra el primer byte distinto
.venv/bin/python test_dorado.py --generar    # reescribe lo esperado (solo a propósito, ver abajo)
.venv/bin/python tests/dorado/generar_fixtures.py   # una sola vez; si se vuelve a correr cambian TODAS las firmas
```

El harness además comprueba que dos corridas en el mismo proceso den lo mismo y que la hora
fija aparezca en la salida (si no aparece, alguien volvió a usar `datetime.now()` fuera del
reloj: así se encontró el de `core/boleta.py` el primer día).

## Reglas

- **Lo esperado se regenera solo cuando el cambio de salida es intencional y entendido**, y se
  dice en el commit qué cambió y por qué. Regenerar para que "pase" es ocultar un bug.
- Toda hora que el SII ve sale de `core/reloj.marca()`. Un `datetime.now()` nuevo en el camino
  de firma rompe el corpus a propósito.
- `RELOJ_FIJO` (entorno) solo en pruebas. Nunca en una instalación que emite.
- El corpus prueba la **capa pura** (sin BD, sin red). El folio atómico, la BD y el envío se
  prueban aparte (`test_simulacion.py`, `test_mvp.py`, certificación).

## El contrato para un port

Un port se considera correcto en local cuando, para cada carpeta de `esperado/`:

| lee | produce | igual a |
|---|---|---|
| `entrada.json` + `fixtures/caf_<tipo>.xml` | TED firmado con la clave del CAF | `ted.xml` |
| lo anterior + `fixtures/cert_demo.p12` | `<DTE>` firmado standalone (ISO-8859-1) | `dte.xml` |
| lo anterior | sobre con carátula y firma | `envio.xml` |

Las trampas que un port va a encontrar, en el orden en que suelen aparecer: canonicalización
C14N exactamente como la de lxml (orden de atributos, namespaces, saltos de línea del TED),
codificación ISO-8859-1 de la "é" de *Café*, el `Id` del `<Documento>` (`T39F1`) y su `URI` en
la firma, y el sobre armado por concatenación de strings sin re-serializar el DTE. Cada una
de esas es una lección ya pagada; el corpus las cobra gratis.

## Lo que todavía no cubre

- Documentos con descuentos, guías (52), notas de débito (56), más de un DTE por sobre.
- Los XML **aceptados por el SII** de empresas reales (TrackID 253113966 y los T34 de
  certificación): están en `storage/` y no pueden entrar al repo (L14). Son el segundo nivel
  de verificación, local y privado: un port también debería reproducirlos.
