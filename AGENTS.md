# AGENTS.md - DTE Chile API

## Quick Start

```bash
# Setup inicial (crea .env, BD SQLite, usuario admin)
python setup.py

# Iniciar servidor
uvicorn main:app --reload --port 8000

# Con Docker
docker-compose up -d
```

**Usuario admin:** se crea en el primer arranque con una **contraseña aleatoria** que se
imprime UNA vez en el log (o la de `ADMIN_PASSWORD` si la defines). Guárdala y cámbiala.

## Architecture

**Framework:** FastAPI + Pydantic v2
**BD:** SQLite (archivo `dte_database.db`, se crea automáticamente)
**Config:** `.env` via pydantic-settings (ver `.env.example`)

### Entry Points
- `main.py` - FastAPI app con lifespan events
- `core/` - Lógica de negocio (DTE, CAF, firma XML, SII, PDF)
- `api/routes/` - Endpoints REST

### Critical Modules
- `core/crypto.py` - Firma XMLDSig (RSA-SHA1, C14N) para certificados .p12
- `core/caf.py` - Manejo de CAF y generación de TED (timbre PDF417)
- `core/dte.py` - Generador XML DTE (tipos 33, 34, 39, 41, 52, 56, 61)
- `core/sii.py` - Cliente SOAP para SII (ambientes: certificacion/produccion)
- `core/rut.py` - Validador RUT chileno (módulo 11)
- `core/auth.py` - JWT auth (sha256_crypt, NO bcrypt - incompatibilidad versión)

### Database Tables
- `dtes` - Documentos emitidos (estado: generado/enviado/aceptado/rechazado)
- `cafs` - Folios autorizados por SII (control de folio_siguiente)
- `audit_log` - Registro de auditoría
- `usuarios` - Autenticación JWT

## Commands

```bash
# Verificar setup
python setup.py

# Probar módulos sin servidor
python test_mvp.py

# Iniciar con hot reload
uvicorn main:app --reload --port 8000

# Ver docs interactivas
open http://localhost:8000/docs
```

## Endpoints Protegidos

`requerir_autenticacion` (`core/auth.py`) acepta un **JWT** o una **API key** (`dte_...`,
creadas en `/apikeys` vía `core/apikeys.py`) en `Authorization: Bearer <token>`.

Protección **a nivel de router** en `main.py` (todo el router, no endpoint por endpoint):
- `certificado`, `caf`, `dte`, `status`

Protección **por endpoint** (además de los routers de arriba):
- `GET /api/v1/db/dtes` - Listar DTEs
- `GET /api/v1/db/cafs` - Listar CAFs
- `GET /api/v1/db/folios/siguiente/{rut}/{tipo}` - Siguiente folio disponible
- `GET /api/v1/db/logs` - Logs de auditoría
- `GET /api/v1/auth/usuarios` - Listar usuarios
- `DELETE /api/v1/auth/usuarios/{id}` - Desactivar usuario

Login: `POST /api/v1/auth/login` con `{"username": "...", "password": "..."}`

## Environment Variables Críticas

```env
SII_AMBIENTE=certificacion  # o "produccion"
EMPRESA_RUT=76543210-5
EMPRESA_RAZON_SOCIAL=Mi Empresa SpA
JWT_SECRET_KEY=<generar con: openssl rand -hex 32>
```

## SII Integration Gotchas

- **Ambiente certificación:** URLs de Maullin (pruebas)
- **Ambiente producción:** URLs de Palena (real)
- **Token SII:** Expira en ~1 hora, se renueva automáticamente
- **Firma XML:** Debe usar SHA-1 (no SHA-256) para compatibilidad SII
- **Encoding XML:** ISO-8859-1 (no UTF-8) para envío al SII
- **CAF:** Archivo XML del SII con folios autorizados. La clave privada del CAF firma el TED, NO el certificado del contribuyente

## Testing

```bash
# Test básico de módulos
python test_mvp.py

# Probar API completa
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<tu-password>"}'
```

## Docker

```bash
# Build y run
docker-compose up -d

# Logs
docker-compose logs -f dte-api

# Detener
docker-compose down
```

Volumen persistente: `dte-chile-data` (BD + storage)

## Common Tasks

### Agregar nuevo tipo de DTE
1. Agregar enum en `core/dte.py:TipoDTE`
2. Actualizar `NOMBRES_DTE` en `core/pdf_gen.py`
3. Ajustar lógica de IVA si es exento

### Cambiar ambiente SII
Editar `.env`: `SII_AMBIENTE=produccion` (requiere certificación previa)

### Resetear BD
```bash
rm dte_database.db
python setup.py  # Recrea tablas y usuario admin
```

## File Conventions

- XML DTE: ISO-8859-1, sin pretty-print para envío
- PDF: ReportLab con timbre PDF417 (pdf417gen)
- Certificados: .p12/.pfx en memoria, NO persistidos
- Storage: `storage/dtes/`, `storage/pdfs/`, `storage/cafs/`

## Security Notes

- Certificados .p12 NUNCA se guardan en texto plano (keystore cifrado con Fernet)
- **`setup.py` genera secretos fuertes** en el `.env` (`JWT_SECRET_KEY`, `DTE_MASTER_KEY`)
- **Arranque fail-closed:** `main.py` chequea `settings.problemas_seguridad()` al iniciar;
  avisa siempre y **aborta en producción** si hay secretos por defecto/inseguros
- **Admin con password aleatoria** en el primer arranque (o `ADMIN_PASSWORD`), mostrada 1 vez
- **CORS:** con `*` se deshabilitan credenciales (spec CORS); restringe `CORS_ORIGINS` en prod

## MCP + Robustez (API)

**Servidor MCP** — expone el toolkit del SII como herramientas para IA (ver
`docs/MCP.md`). Reusa el mismo `core/` que la API REST.
```bash
.venv/bin/python mcp_server.py      # stdio, para clientes MCP (Claude Desktop/Code)
```

**Errores uniformes** — toda respuesta de error usa el envelope
`{"error": {codigo, mensaje, detalle, request_id}}` (ver `docs/ERRORES-API.md`).
- Errores de dominio tipados en `core/errors.py` (`ValidacionError`, `SinFoliosError`,
  `SIIError`, `SIIRechazoError`, `CAFError`, …), cada uno con `codigo` estable + status.
- Handlers globales + request-id + logging de acceso en `api/errors.py`
  (`registrar_manejo_errores(app)` en `main.py`). Las excepciones no manejadas → 500
  genérico con la traza SOLO en el log.

**Reintentos/backoff al SII** — `core/reintentos.py::ClienteReintentos` (subclase de
`httpx.Client`) reintenta SOLO fallos transitorios (HTTP 429/502/503/504 + errores de
red) con backoff exponencial + jitter, respetando `Retry-After`. Ya está enchufado en
`ClienteSII` y `PortalSII` (todas las llamadas al SII pasan por él). No reintenta 4xx.

```bash
.venv/bin/python test_robustez.py   # envelope, 404/422/500, request-id, MCP, auth, reintentos
```
