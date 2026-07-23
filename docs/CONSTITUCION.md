# Constitución del motor DTE

> **Leyes inviolables.** Cada una se paga con días de trabajo o con plata real del
> contribuyente si se rompe. Todas nacen de un error que YA se cometió en este proyecto.
> Si una ley te estorba, **no la rodees: discútela con el usuario**.
>
> Este archivo es corto a propósito y se lee SIEMPRE. El detalle vive en
> [`MAPA.md`](MAPA.md) (dónde está qué) y [`LECCIONES-SII.md`](LECCIONES-SII.md) (por qué).

---

## L1 — Los documentos tributarios son reales. Certificación no.

- `certificacion` (maullin / pangal / apicert) = **sandbox**. Sin efecto tributario, no entra
  al RCV ni al **F29**. Es donde se prueba TODO.
- `produccion` (palena / rahue) = **documentos reales con efecto tributario**. Un envío
  equivocado le crea al usuario un problema con el SII y con su F29.
- **Nunca** apuntar a producción sin intención explícita del usuario. `settings.sii_ambiente`
  gobierna; `main.py` aborta el arranque si hay config insegura en producción.
- Antes de cualquier envío, **di a qué ambiente va**.

## L2 — La firma del DTE se hace SOLO con `core/sobre.py`

El SII verifica la firma del DTE **extrayéndolo como documento independiente**, sin el
`xmlns:xsi` que declara el sobre. Por lo tanto:

1. El `<DTE>` se firma **standalone**, en su propio árbol (`firmar_documento_standalone`).
2. El sobre se arma **concatenando strings**, con el DTE insertado **verbatim**
   (`armar_sobre_firmado`).
3. **Después de firmar, los bytes NO se tocan.** Nada de re-parsear ni re-serializar.

> *"no xmlns attributes in the individual DTE when signed" + "do not reformat after signing"*

Firmar el DTE ya embebido o reformatear después ⇒ **`DTE-3-505 Firma DTE Incorrecta`**.
Costó 11 variantes de firma a ciegas descubrirlo. Verificado: TrackID 253113966 →
`ACEPTADOS: 1`. Detalle en [`LECCIONES-SII.md`](LECCIONES-SII.md).

🔒 **Esta ley tiene tests: `test_sobre.py`. Córrelo antes de dar por buena cualquier cosa que
toque la firma, el sobre o el preview.**

## L3 — `EPR` NO significa "aceptado"

`EPR` = *"Envío Procesado"*: el **sobre** se procesó. El veredicto de cada documento está en
`ACEPTADOS` / `RECHAZADOS` / `REPAROS`. **Nunca** reportar éxito mirando `estado`.

Este malentendido tuvo al proyecto creyendo que el pipeline funcionaba mientras el SII
rechazaba todo. Usar `consultar_estado()["todo_aceptado"]`, nunca `estado == "EPR"`.

## L4 — La resolución de la carátula es POR EMPRESA (no global)

Usar **siempre** `core.resolucion.resolucion_emisor(rut)` → `(fecha_iso, numero)`. El SII
valida la resolución **por RUT del emisor**: cada empresa tiene la suya (en certificación y en
producción). Mandar la de otra empresa/ambiente hace que el SII rechace el sobre entero con
`CRT-3-19 "Fecha/Numero Resolucion Invalido"`.

⚠️ **NO usar `settings.resolucion` directo** (es solo el default/fallback global) ni
`sii_fecha_resolucion`/`sii_numero_resolucion` a pelo. El default global le sirvió a una
empresa y rechazó a otra (a SOFTWARE DEMO SPA le tocaba 2026-07-19 en cert / 99-2014-10-21 en
prod, no el global 2026-07-08). `resolucion_emisor` saca el valor del registro del SII por RUT (con
caché) y cae al default solo si la consulta falla. Cableado en `orchestrator.py`,
`orchestrator_boleta.py`, `preview.py`, `scheduler.py`. Ver `core/resolucion.py`.

## L5 — El correo del usuario es intocable (salvo un canal acotado)

**NUNCA** uses las herramientas de Gmail (`search_threads`, `get_thread`, …). Sigue vigente.

Lo único autorizado es la skill **`correos-sii`**: un endpoint que el usuario construyó, de
**solo lectura** y limitado a sus **últimos 20 correos**. Es la vía para obtener el **código**
de un rechazo — el SOAP de facturas solo da conteos y el detalle llega **solo por correo**.

El token vive en **`.env`** (`SII_MAIL_TOKEN`) y **lo rota el usuario**; `.env` está en
`.gitignore` (comprobado). Sigue siendo una **credencial**: no la loguees, no la devuelvas por la
API, no la pegues en un chat. Y **borra el JSON descargado al terminar**: contiene correo personal.

## L6 — Los certificados no se escriben en claro

`.p12`/`.pfx` y sus claves: **en memoria** para firmar, **cifrados (Fernet)** en el keystore.
Jamás a disco ni a la BD en texto plano, jamás en logs, jamás en un Artifact.
Los PEM temporales para mTLS del portal se borran en un `finally`.

## L7 — El consumo de folios es atómico y escaso

- `consumir_siguiente_folio` usa `BEGIN IMMEDIATE` para evitar una carrera TOCTOU.
  **No dupliques esa lógica**: reusa `OrquestadorDTE._preparar_emision`.
- **Anti-acaparamiento**: el SII **bloquea el timbraje** si acumulas folios sin usar (ya
  pasó con T33/T61 y sigue bloqueado). No pidas folios de más. Respeta el guardrail de
  `PortalSII.max_folios_por_tipo`.

## L8 — El XML del SII es frágil por diseño

- **ISO-8859-1**, nunca UTF-8. Sin pretty-print.
- **El orden de los elementos es XSD-significativo**: el SII rechaza tags fuera de orden.
  Cualquier cambio se valida contra `core/xsd/`.
- El SII usa un **perfil restringido de XMLDSig**: exactamente **un** `Transform`, y
  `KeyValue`/`RSAKeyValue` obligatorios **antes** de `X509Data`. Por eso **no se puede usar
  una librería estándar tal cual** (signxml emite dos transforms y no emite KeyValue).

## L9 — Las boletas son otra infraestructura, no un tipo más

Boletas (39/41) ≠ facturas. **Servidores propios, REST (no SOAP), token propio**, y
reporte diario obligatorio (RVD). Nunca las mandes por el camino de facturas: usar
`OrquestadorBoleta` / `ClienteBoletaSII`. El punto de entrada que rutea solo es
`core/orchestrator.py::emitir_documento`.

## L10 — Lee el repo antes de experimentar. Y no confíes en tu criterio por sobre lo escrito.

La solución al `DTE-3-505` **llevaba días escrita en DOS lugares**: un comentario de
`certificacion_sii.py` y la memoria del proyecto (que además registraba un
**`ACEPTADOS: 1`**). Se probaron **11 variantes de firma contra el SII vivo** sin leer
ninguno, y se afirmó en falso que *"ningún DTE fue aceptado jamás"*.

- Antes de investigar un error del SII: **busca en el repo y en `LECCIONES-SII.md`**.
- Los scripts de certificación **reimplementan el pipeline inline**; cuando el orquestador y
  un script no coinciden, **el script suele ser el que funciona** (está probado contra el SII).
- **Si el usuario te contradice con evidencia suya, él suele tener razón**: investiga por qué,
  no defiendas tu hipótesis.

## L11 — Documentación desactualizada es un bug, y arreglarla incluye el encabezado

Lo obsoleto suele vivir en los archivos **más visibles**, y ahí hace más daño que en ninguna
parte: `CHECKPOINT.md` y `task.md` enseñaban una teoría de C14N ya revertida, y la memoria
`firma-sii-metodo` **tenía la respuesta pero su `description` anunciaba la teoría vieja** —
así nadie la abrió.

- Cuando un hallazgo cambie, **actualiza el encabezado y la descripción**, no agregues una
  sección al final. Lo primero que se lee es lo único que muchos leen.
- **Todo "verificado/probado" debe decir contra qué** (TrackID, código de error, test).
  ⚠️ Un `EPR` **no** es evidencia de aceptación.
- **Para borrar algo hay que PROBARLO falso** contra el código o contra el SII — no basta
  con que "suene viejo". Lo que no puedas probar, **márcalo como no verificado, no lo borres**.
- Documento histórico ≠ basura: márcalo como tal, con la corrección y la evidencia al lado.

## L12 — No confundas "no falló" con "funciona"

- Un **CAF sintético** (con `<DA>` alterado) rompe la `<FRMA>` del SII: sirve para XSD y
  PDF, **jamás para probar firma**.
- **`signxml` no es oráculo**: rechaza firmas que el SII acepta.
- El SII da **mensajes engañosos**: `401 "NO ESTA AUTENTICADO"` cuando falta el
  `User-Agent`; `500 "Acceso Denegado"` cuando el host es el equivocado. Un error puede no
  significar lo que dice — **verifica la causa, no la etiqueta**.
- Cuando cambias algo y **el error no se mueve**, la causa está en otra parte. No insistas.

## L13 — Español, y honestidad en los reportes

- Código, comentarios e identificadores **en español** (el dominio es chileno).
- Reporta lo que pasó: si el SII rechazó, dilo con el código. **No adornes.** Este proyecto
  se quemó dos veces con conclusiones sobreafirmadas.
