# nucleo — el núcleo de firma del motor, en Go

Port de la capa pura de `core/` (totales → TED → XML del DTE → firma XMLDSig → sobre),
medido contra el corpus dorado del motor Python (`docs/DORADO.md`): misma entrada, mismos
bytes. Sin red, sin base de datos.

```bash
go build -o bin/nucleo-dorado ./cmd/nucleo-dorado
cd .. && .venv/bin/python test_dorado.py --port nucleo/bin/nucleo-dorado    # 15/15 idénticos
```

| paquete | qué replica |
|---|---|
| `totales` | `core/dte.py::calcular_totales` (half-up sobre la repr decimal, boleta con precio bruto) |
| `ted` | `core/caf.py::generar_ted` (DD aplanado, RSA-SHA1 en ISO-8859-1, CAF incrustado) |
| `xmlgen` | `GeneradorDTE.generar_documento_xml` y `generar_documento_boleta`, serializados como lxml |
| `c14n` | Canonical XML 1.0 inclusiva con el ápice "reparseado" (`core/crypto.py::_c14n_reparse`) |
| `firma` | PKCS#12, `firmar_xml_sii`, `firmar_documento_standalone`, `armar_sobre_firmado` |

Regla (L15): si un byte difiere del corpus, el error está aquí o en Python, y se averigua cuál
contra el SII antes de tocar lo esperado. Plan y fases en `docs/PLAN-PORT.md`.
