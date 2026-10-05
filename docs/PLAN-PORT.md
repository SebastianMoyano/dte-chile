# Plan: portar el núcleo del motor a un lenguaje compilado

> Estado: **plan aprobado para empezar, sin código del port todavía.** Fecha: 2026-10-04.
> Herramienta de medición: `test_dorado.py --port` ([`DORADO.md`](DORADO.md)).

## Por qué (y por qué no)

Lo que se busca con el port no es velocidad ni "seguridad de memoria": es **un solo binario
que se instala y funciona** sin Python ni `.venv`, y un núcleo de firma que se pueda auditar
en pocas líneas. Lo que NO se busca es reescribir el motor entero: la parte que cambia
seguido (portal MIPYME, RCV, F29, captura) se queda en Python, donde iterar es barato.

El motor Python sigue siendo la **implementación de referencia**: está verificada contra el
SII (TrackID 253113966 aceptado, T34 de certificación aceptados). Un port no se juzga por
parecer correcto sino por producir **los mismos bytes** (L15). Por eso el plan no toca al SII
hasta la fase 3.

## Lenguaje: Go, salvo que se decida Rust a propósito

Recomendación: **Go**. Razones: el cascarón de la app ya es Go (`app/`), así el producto
final es un binario de un solo lenguaje; la biblioteca estándar trae RSA, SHA-1, PKCS#12 y
X.509; el equipo que mantiene esto es pequeño y Go se lee rápido. Rust daría lo mismo en
corrección y un binario igual de autónomo, pero suma un lenguaje más al repo y una curva
más larga; se justifica solo si quien lo va a mantener lo domina. **El plan es idéntico en
ambos casos**: el contrato son archivos, no una API de lenguaje.

## Principios

1. **El corpus manda.** Cada paso se da por hecho cuando `test_dorado.py --port` dice
   "bytes idénticos" en todos los casos. No antes.
2. **Por partes, de adentro hacia afuera**: primero lo puro (totales → TED → XML del DTE →
   firma → sobre), después lo que tiene estado (CAF en BD, folio atómico), al final lo que
   habla con el SII.
3. **Mismo contrato HTTP.** La API (`/api/v1/...`) y la app no cambian. El port entra por
   detrás, reemplazando funciones, no por delante cambiando interfaces.
4. **Nada real hasta la fase 3**, y en la fase 3 solo el ambiente de certificación.

## Fases

### Fase 0 — Preparar la vara (Python, 1-2 días)

- [x] Reloj único (`core/reloj.py`) y corpus dorado con 5 casos.
- [x] Runner para ports externos (`--port`) y port de ejemplo que lo valida.
- [x] Corpus de 15 casos: ND (56), guía (52), descuentos por línea, cantidad decimal,
      afecto + exento, crédito con vencimiento y tildes, NC parcial, boleta mixta con
      `IndServicio`, sobre con 3 DTE, sobre con 2 boletas, receptor mínimo. Los 15 validan XSD.
- [ ] Corpus privado: los XML **aceptados** por el SII (en `storage/`, fuera de git) como
      casos con su entrada reconstruida; comparación local solo.
- [x] Especificación de bytes en `DORADO.md` (totales, TED, DTE firmado, sobre) y modo
      `--parcial` del harness para medir un port a medio camino.

### Fase 1 — Núcleo puro en Go (`nucleo/`, 1-2 semanas)

> Estado 2026-10-04: `nucleo/` existe; `nucleo/bin/nucleo-dorado` produce `ted.xml` y
> `totales.json` idénticos en los 15 casos (`test_dorado.py --port nucleo/bin/nucleo-dorado --parcial`).

Un módulo Go sin red ni BD, con un ejecutable `nucleo-dorado` que cumple el contrato del
runner (`<entrada.json> <fixtures/> <salida/>`). Orden, y cada paso se cierra con el corpus:

| paso | qué | compara contra | trampa conocida |
|---|---|---|---|
| 1.1 ✅ | `calcular_totales` (redondeo half-up CLP, boleta con IVA incluido, exentos) → `nucleo/totales` | `totales.json` | boleta: precio bruto, neto derivado |
| 1.2 ✅ | parseo del CAF y **TED**: `<DD>` aplanado, firma RSA-SHA1 con la clave del CAF, `<CAF>` incrustado tal cual → `nucleo/ted` | `ted.xml` | los saltos de línea del TED son parte de lo firmado |
| 1.3 | generación del `<DTE>` sin firma: orden de tags según XSD, ISO-8859-1, `Id="T{tipo}F{folio}"` | diff estructural (sin `<Signature>`) | orden de elementos; "é" en ISO-8859-1 |
| 1.4 | **C14N** (xml-c14n 2001) + XMLDSig RSA-SHA1 del `<Documento>` standalone | `dte.xml` | C14N exactamente como lxml: namespaces, atributos ordenados, sin xsi del sobre |
| 1.5 | **sobre** por concatenación de strings con el DTE verbatim, firma del `SetDTE` | `envio.xml` | nunca re-serializar el DTE firmado (L1, DTE-3-505) |
| 1.6 | validación XSD con `core/xsd/` (opcional en Go; si no hay librería madura, se delega a Python en esta fase) | — | — |

Criterio de salida: `test_dorado.py --port ./nucleo/bin/nucleo-dorado` → todos idénticos,
incluido el corpus privado de aceptados.

### Fase 2 — Estado: CAF, folios y persistencia (1 semana)

- Lectura de CAF desde la BD SQLite existente (mismo esquema, mismo archivo).
- Folio atómico con `BEGIN IMMEDIATE` (reproducir exactamente `consumir_siguiente_folio`).
- Guardar DTE/PDF/sobre con las mismas rutas y filas que hoy, para que la API Python y la app
  sigan viendo lo mismo.
- Prueba: emitir con el port y con Python alternadamente sobre la misma BD de prueba; los
  folios no se repiten ni se saltan.

### Fase 3 — Contra el SII de certificación (1 semana, con folios de Maullín)

- El port emite el **set de pruebas** completo (`dry_run_certificacion.py` como guía) y se
  envía con el cliente SOAP Python existente (el envío no se porta todavía).
- Resultado esperado: `ACEPTADOS` iguales a los que logra Python con las mismas entradas.
  Cualquier `RECHAZADO` o `DTE-3-505` detiene la fase: se vuelve a la fase 1 con ese caso
  agregado al corpus.

### Fase 4 — Integración en el producto (1 semana)

- El cascarón Go (`app/`) llama al núcleo directo para generar/firmar; Python queda como
  servicio para MIPYME, RCV, F29, portal y envío SOAP.
- Instalador: un binario Go + un Python embebido solo para esos servicios (o PyInstaller del
  motor) hasta que se decida si el envío SOAP también se porta.
- Corpus dorado corriendo en CI contra Python y contra el port, en cada commit.

### Fase 5 — Decidir qué más (abierto)

Con fases 1-4 hechas, se mira el valor de portar: envío SOAP y semilla/token (sencillo),
PDF con PDF417 (hay librerías en Go), boletas EnvioBOLETA + RVD. El portal MIPYME no se
porta: es scraping vivo y cambia con el SII.

## Riesgos y cómo se mitigan

- **C14N distinta** entre lxml y la librería del port. Es el riesgo mayor. Mitigación: la fase
  1.4 se hace con casos mínimos (un `<Documento>` de 3 tags) antes del corpus completo, y la
  especificación de bytes de la fase 0.
- **Codificación**: ISO-8859-1 en todo lo que ve el SII; UTF-8 solo en la API. Un port que
  escriba UTF-8 "porque es lo normal" falla en el byte de la primera tilde. El corpus tiene
  tildes a propósito.
- **Regenerar el corpus para que pase.** Prohibido por L15. Si el port "necesita" otro byte,
  el port está mal, o lo está Python y entonces se prueba contra el SII antes de cambiar.
- **Dos implementaciones divergiendo** con el tiempo. Mitigación: el corpus corre contra ambas
  en CI; la que falla se arregla, no se excluye.

## Qué NO es parte del plan

- Cambiar la API o la app por el port.
- Portar el canal MIPYME, la captura o el F29.
- Tocar producción con el port antes de que certifique en Maullín.
