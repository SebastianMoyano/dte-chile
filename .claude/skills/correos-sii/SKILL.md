---
name: correos-sii
description: Lee los correos del SII (resultados de envíos y de sets de certificación) desde el endpoint propio del usuario. Úsala cuando necesites el CÓDIGO de error de un rechazo — el SOAP de facturas solo da conteos y el detalle llega SOLO por correo.
---

# Leer los correos del SII

## Por qué existe

El detalle de un rechazo de **factura** llega **solo por correo**. El SOAP (`QueryEstUp`) da
únicamente conteos (`ACEPTADOS: 0, RECHAZADOS: 1`) **sin el código** — y sin código no se puede
diagnosticar. (El REST de boletas sí devuelve el código al instante; esta skill es para facturas
y para los resultados de los sets de certificación.)

Sin esto hay que pedirle al usuario que pegue cada correo a mano. Eso costó tiempo real.

## Regla (no negociable)

**NUNCA uses las herramientas de Gmail** (`search_threads`, `get_thread`, etc.). La regla del
usuario sigue vigente. Lo único autorizado es **este endpoint**, que él construyó: solo lectura,
solo sus **últimos 20 correos**.

## El token

Vive en **`.env`** como `SII_MAIL_TOKEN` — **el usuario lo rota ahí** (se regenera en el Apps
Script y se reemplaza; nada más lo referencia). Se expone como `settings.sii_mail_token`.

- `.env` **está en `.gitignore`** — comprobado con un `git status` real, no leyendo el archivo.
- Es una **credencial**: no lo loguees, no lo devuelvas por la API, no lo pegues en un chat ni
  en un Artifact. Si el script falla, **no lo imprimas para depurar**.
- Si no está configurado, **pídeselo al usuario**. No lo busques por otra vía.

Verificado (2026-07-17): la URL **sin** token responde
`{"error":"No autorizado. Token inválido o ausente."}` — el token es el **único** secreto; la
URL por sí sola no da acceso. Por eso la URL sí está en el script.

## Uso

```bash
.venv/bin/python .claude/skills/correos-sii/leer_correos.py            # tabla resumen
.venv/bin/python .claude/skills/correos-sii/leer_correos.py 253113966  # el correo completo de un envío
.venv/bin/python .claude/skills/correos-sii/leer_correos.py --set 4943175   # resultado de un set
```

Toma el token de `.env` solo. Para probar con otro sin tocar `.env`:
`SII_MAIL_TOKEN='<otro>' .venv/bin/python ...` (el entorno tiene prioridad).

La tabla resumen muestra, por envío: fecha, tipo/folio, aceptados/rechazados y **el código de
error** (`DTE-3-505`, `CAF-3-517`, `CRT-3-19`, `HED-3-861`…).

## Cómo leer lo que devuelve

Los códigos y su significado están en **[`docs/LECCIONES-SII.md`](../../../docs/LECCIONES-SII.md)**
(tiene índice por código). Los que más aparecen:

| Código | Qué es |
|---|---|
| `DTE-3-101` | folio ya recibido → usa uno fresco |
| `CAF-3-517` | CAF vencido (>6 meses) → pide folios nuevos |
| `CRT-3-19` | resolución equivocada en la carátula → `settings.resolucion` |
| `DTE-3-505` | firma del DTE incorrecta → `core/sobre.py` |
| `HED-3-861` | actividad económica no registrada → usa el acteco REAL |
| `SRH` | **set** de certificación rechazado (distinto de un envío) |

⚠️ **`EPR` no significa "aceptado"** — significa que el *sobre* se procesó. Mira la columna
`Aceptados`. Igual con `LOK` en los libros: cuadra el libro, no aprueba el set.

**El SII valida en orden** (`folio → CAF → TED → firma → datos`) y **un error temprano enmascara
los siguientes**. Si arreglas uno y aparece otro, eso es progreso, no un retroceso.

## Higiene

- Borra cualquier JSON descargado al terminar: **contiene correo personal** del usuario.
- Usa el endpoint solo para los correos del SII. Aunque devuelva otros, no son asunto tuyo.
