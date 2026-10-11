# Seguridad

Este motor firma y envía documentos tributarios reales. Lo que protege son dos cosas: el
certificado digital de la persona y los folios de la empresa.

## Qué nunca entra al repo

- Certificados (`.p12`, `.pfx`), claves privadas, el `.env`, la base de datos, `storage/`.
  Están en `.gitignore` y el gate `publico` (`tools/auditar_publico.py`) revisa el árbol **y
  toda la historia** antes de cada push (`./tools/instalar_hooks.sh`) y en CI.
- RUTs reales de empresas o personas. En docs, pruebas y ejemplos van solo los ficticios de
  la constitución (`77777777-7`, `76111111-6`, `12345678-5`); el auditor detecta cualquier RUT
  con dígito verificador válido que no esté en esa lista.
- Claves tributarias, tokens, cookies del SII, API keys. Las claves se piden por entorno, por
  el Llavero del sistema o por prompt oculto; nunca por flag ni por log.

## Cómo está protegido el motor en uso

- Los certificados se guardan **cifrados** en la base (clave maestra `DTE_MASTER_KEY`) y se
  usan solo en memoria. `nucleo-servidor rotar-claves` re-cifra todo con una clave nueva.
- La API exige JWT o API key; la clave de la app de escritorio es efímera y solo existe en el
  proceso. El MCP local habla por stdio en la misma máquina: sin red, sin token.
- Lo único pensado para ser público es el buscador `/consulta`, acotado por dominio
  (`DOMINIO_PUBLICO_BOLETAS`). **No expongas la API a internet** sin un proxy con TLS delante.
- El MCP por HTTP (`nucleo-mcp --http`) es para 127.0.0.1 o detrás de TLS. Nunca HTTP plano.

## Reportar una vulnerabilidad

Abre un *issue* marcado "seguridad" sin incluir datos reales, o escribe al contacto del
repositorio. Si el problema expone certificados, folios o datos de contribuyentes, dilo en la
primera línea. Se responde antes de publicar cualquier arreglo.
