# Contribuir

Gracias por querer mejorar la facturación electrónica de Chile. Tres reglas y un método.

## Las reglas

1. **Lee [`docs/CONSTITUCION.md`](docs/CONSTITUCION.md) antes de tocar código.** Cada ley se
   pagó con días de trabajo o con folios reales. La más cara: la firma se hace *standalone* y el
   sobre se arma por concatenación de strings (`core/sobre.py`, `nucleo/sobre`); re-serializar lo
   firmado es un `DTE-3-505` seguro.
2. **Nada real en el repo.** RUTs ficticios, sin certificados, sin claves, sin capturas con
   datos de contribuyentes. `python tools/auditar_publico.py` lo verifica; instálalo como hook con
   `./tools/instalar_hooks.sh`.
3. **Nunca regeneres un esperado para que una prueba pase.** Si el corpus dorado cambia, alguien
   movió un byte de la firma: se averigua, no se regenera (L15).

## El método: los gates son la definición de terminado

```bash
./tools/prueba_final.sh --sin-red   # todo, sin tocar el SII: corpus, esquema, contrato, Go, MCP, app, público
```

Cada bloque del motor nace con su gate automático. Un cambio está listo cuando todos pasan,
en Python y en Go, y cuando la documentación sigue siendo verdad. Si agregas una ruta, va en los
dos motores y la mide `tools/contrato_api.py`. Si agregas un tipo de documento, va al corpus.

## Dónde está cada cosa

[`docs/MAPA.md`](docs/MAPA.md) es el índice. Python (`core/`, `api/`) es la referencia que fija
el comportamiento; Go (`nucleo/`) es el motor que se distribuye; la app (`app/`) lo corre en
proceso. Los commits van en español, como el código.
