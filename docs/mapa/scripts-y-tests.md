# Mapa — Scripts, tests y artefactos

> Hoja del [`MAPA.md`](../MAPA.md). Cárgala si trabajas en los scripts de la raíz, en los
> tests, en `core/xsd/` o en `storage/`.

## Scripts de la raíz

| Script | Qué hace | ¿Duplica `core/`? |
|---|---|---|
| `certificacion_sii.py` | Define los 16 casos del Set de Pruebas y los envía | 🔴 **Sí — reimplementa `core/sobre.py` entero** (`:428-465`) |
| `dry_run_certificacion.py` | Los 16 casos en local (XML+firma+TED+XSD+PDF), sin enviar | 🟡 verificadores propios |
| `reenviar_certificacion.py` | Reenvía por *olas* con CAF frescos | 🔴 **no ejecutable**: depende de `/tmp/of_ref/*` (borrado) |
| `solicitar_caf_sii.py` | Pide CAF por `CrFolio.jws` | 🟡 `ClienteSOAP` duplica `core/sii.py` |
| `load_cafs.py` | `storage/cafs/*.xml` → BD | ✅ usa `core/` |
| `setup.py` | Init: `.env` con secretos fuertes, BD, admin | ⚠️ **no es un `setup.py` de setuptools** — nombre trampa |
| `rotar_claves.py` | Rota JWT/master key **re-cifrando** los certs | ✅ |
| `keystore_cli.py` | CRUD de certs cifrados | ✅ fachada |
| `generar_f29.py` | Propuesta F29 desde el RCV | ✅ fachada |
| `crear_caf_mock_61.py` | CAF **falso** T61 | ⚠️ mock: inútil para probar firma (L11) |
| `ejecutar_certificacion.sh` | Wrapper | ✅ arreglado — antes validaba un `.pfx` distinto del que cargaba `certificacion_sii.py`; ahora ambos usan `DTE_CERT_PATH`/`--cert` |

## Tests — scripts planos, cero pytest

```bash
.venv/bin/python test_sobre.py       # ⭐ Ley L2: la firma que el SII acepta (32 checks)
.venv/bin/python test_boleta.py      # 46 checks: boletas, RVD, scheduler, guardarraíles, EPR
.venv/bin/python test_robustez.py    # 10 bloques: errores, envelope, MCP, auth, reintentos, XXE
.venv/bin/python test_mvp.py         # smoke de imports + totales + PDF
.venv/bin/python test_rcv.py         # RCV/F29 local (el mejor test del repo: asserts numéricos)
.venv/bin/python test_rcv_live.py    # ⚠️ PRODUCCIÓN — exploración, sin asserts
.venv/bin/python test_orchestrator.py
```

⚠️ **`test_boleta.py` necesita la clave del `.pfx`**: la saca de `TEST_PFX_PASS` o del Llavero
(`security add-generic-password -s dte-cert-sebastian -a $USER -w '<clave>'`). Nunca hardcodeada.

**Sin runner agregado, sin CI.** `test_boleta.py`/`test_robustez.py` salen con código ≠0 si
fallan; **`test_mvp.py` y `test_orchestrator.py` siempre salen 0** (no pueden reprobar).

### 🔴 Huecos de cobertura

✅ **`core/sobre.py` YA tiene tests** (`test_sobre.py`, 2026-07-16) — era el hueco más caro.
Verifica las firmas **sobre los bytes finales**, como el SII: el sobre en contexto, y el DTE
**extraído como documento suelto** (así lo valida el SII — verificarlo en contexto **falla a
propósito**, y ese es justamente el mecanismo del `DTE-3-505`). Incluye el test de que
`preview.py` sigue siendo un pre-vuelo fiel: la regresión que de verdad ocurrió. Probado que
caza los 3 fallos reales: firmar con el método de la semilla, re-serializar el sobre, y que un
llamador vuelva al camino viejo.

**Sin un solo test**: `core/rut.py`, `core/keystore.py`, `core/libro.py`, `core/negocios.py`,
`api/routes/*`. Tampoco hay test de que `settings.resolucion` se use en la carátula (L4).

⚠️ `test_orchestrator.py` hace `return` silencioso si falta el `.pfx` (`:151-152`) → **pasa sin
ejecutar nada**; y su `except` imprime sin fallar (`:191-194`) → **no puede reprobar**.

## `core/xsd/` — 6 esquemas, **ninguno parcheado**

Son los oficiales del SII (conservan el mojibake ISO-8859-1 del original → no fueron
reescritos). **Léelos con `grep -a`**: son ISO-8859-1 y `grep` los trata como binarios.

| Archivo | Rol · restricciones que importan |
|---|---|
| `DTE_v10.xsd` | Documento. Define `TipoDTE` (el del `IdDoc`) |
| `EnvioDTE_v10.xsd` | Sobre de facturas. `SubTotDTE maxOccurs=20`, 2000 DTE/sobre. Define `TpoDTE` (el de la carátula) |
| `EnvioBOLETA_v11.xsd` | Sobre de boletas. **Autocontenido** (redefine sus tipos; su `DTEType` = solo 39/41). `SubTotDTE maxOccurs=2`. **`DTE` es `maxOccurs="unbounded"`** ⚠️ |
| `ConsumoFolio_v10.xsd` | RVD. `Resumen maxOccurs=3` → de ahí `TIPOS_CONSUMO = (39,41,61)` |
| `xmldsignature_v10.xsd` | **Perfil restringido**: `Transform maxOccurs=1`, `KeyValue` antes de `X509Data` → por eso `signxml` es inservible |
| `SiiTypes_v10.xsd` | 37 simpleTypes |

⚠️ **`TipoDTE` vs `TpoDTE` NO es un bug local**: son dos elementos legítimos y distintos del
esquema del SII. Hubo comentarios que lo trataban como "discrepancia del XSD local" — falso.

## `storage/`

| Dir | Qué |
|---|---|
| `cafs/` | CAFs activos — 🔴 **mezcla vigentes y vencidos** |
| `cafs_vencidos/` | 🔴 **mal nombrado**: ahí hay un CAF vigente archivado por *folio consumido* |
| `cafs_mock_backup/` | CAF T61 **falso** (FRMA placeholder) |
| `dtes/`, `pdfs/`, `dtes_cert/`, `pdfs_cert/`, `rvd/` | Artefactos de emisión |
| `resultados_*.json` | Resultados de corridas — ⚠️ desincronizados del código actual |

### Estado de los CAF (regla `CAF-3-517`: vencen a los 6 meses)

- ✅ **Vigentes** (todos FA 2026-07-16 salvo el T33): T33 [101], T34 [104-106], [107-109],
  [110-112], T39 [1-3], [4-6], [7-12].
- 🔴 **Vencidos pero en `cafs/`**: T34 [1-100] (FA 2024-01-27), **T56 [80-157]** y
  **T61 [80-157]** (FA 2025-02-10). T56 y T61 **no tienen ningún CAF vigente** → sus casos del
  set no son emitibles hoy.

## ⚠️ Deuda conocida (auditada 2026-07-16)

| Sev | Qué | Dónde |
|:-:|---|---|
| 🔴 | **`certificacion_sii.py` elige el CAF equivocado**: `cafs[tipo] = caf` dentro de un glob → **el último gana en silencio**. Por orden alfabético, el T34 que gana es el **vencido de 2024** → `CAF-3-517`. | `certificacion_sii.py:110-116` |
| 🔴 | Reimplementa `core/sobre.py` y **hardcodea la resolución** (`FchResol=2026-07-08`, `NroResol=0`) → viola L4: con `SII_AMBIENTE=produccion` mandaría la de certificación. | `certificacion_sii.py:428-465`, `:445` |
| ✅ | ~~`CHECKPOINT.md`/`task.md` enseñaban la teoría C14N ya revertida~~ → **marcados como históricos 2026-07-16**, con la refutación y la evidencia arriba. No se borraron: su parte cierta sigue sirviendo. Igual se corrigió la memoria `firma-sii-metodo`, cuya `description` ocultaba la respuesta. | — |
| ✅ | ~~`CHECKPOINT.md` con contraseña en claro~~ → **arreglada**; ahora sale del Llavero. Y se creó `.gitignore` (el repo no tenía). | — |
| ✅ | ~~`dry_run` silenciaba fallos XSD y probaba `_c14n_en_contexto` como "método actual"~~ → **arreglado 2026-07-16**: el XSD vuelve a ser bloqueante (su excusa era falsa: los XSD SON los oficiales) y `_c14n_reparse` va primero, con los demás rotulados "NO es el del SII". | — |
| 🔵 | `requirements.txt`: `python-jose` duplicado; `signxml` declarada aunque es inservible para el SII. | — |
| 🔵 | Dockerfile corre como **root** y hace `cp .env.example .env` si falta. | — |
| 🔵 | Basura en la raíz: `.dmg` (9 MB), `.mp3`, `.DS_Store`, `.env.bak-*`, `db.bak-*`, y **CAFs reales sueltos en `.playwright-cli/`**. | — |

## 🔍 Conocimiento aún enterrado (rescatar a `LECCIONES-SII.md`)

Comentarios valiosos que **solo existen ahí**:

| Dónde | Qué |
|---|---|
| `solicitar_caf_sii.py:435-438` | Un `<SignedInfo>` con prefijo `ds:` distinto del firmado → el SII devuelve **`Estado=10 "Error Interno"`**. Otro caso de "el SII miente". |
| `solicitar_caf_sii.py:464-467` | **`CrFolio.jws` no existe en Maullín** (404); solo en producción. Explica por qué los folios van por scraping (`core/sii_portal.py`). |
| `dry_run_certificacion.py:227-237` | Para **verificar** el TED hay que usar la misma canonicalización que al generarlo (C14N + aplanado + ISO-8859-1); con otra, marca inválida una firma correcta. |
| `test_rcv_live.py:38` | El facade del RCV exige **`Accept: */*`**; con `application/json` da **HTTP 500**. |
| `reenviar_certificacion.py:4-14` | **`REF-3-750`** ("DTE referenciado no recibido") y la táctica de **olas** para no quemar folios. |
