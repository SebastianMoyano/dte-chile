"""
main.py — Punto de entrada de la API REST de Facturación Electrónica DTE Chile.

Uso:
    uvicorn main:app --reload --port 8000

Documentación interactiva disponible en:
    http://localhost:8000/docs  (Swagger UI)
    http://localhost:8000/redoc (ReDoc)
"""

import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from core.config import settings
from core.database import init_db
from core.folios_auto import programador_folios
from core.scheduler import programador
from core.models import obtener_usuario_por_username, crear_usuario, listar_usuarios
from core.auth import hash_password, requerir_autenticacion

from api.routes import certificado, caf, dte, status, auth, db, keystore, onboarding, monitoreo, consulta, apikeys
from api.errors import registrar_manejo_errores


# ---- Logging ----
def configurar_logging():
    """Configura el sistema de logging."""
    log_dir = Path(settings.log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(settings.log_file, encoding="utf-8"),
        ],
    )


# ---- Lifespan (startup/shutdown) ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events: se ejecuta al iniciar y detener la aplicación."""
    logger = logging.getLogger("dte.startup")

    logger.info(f"Iniciando {settings.app_name} v{settings.app_version}")
    logger.info(f"Ambiente SII: {settings.sii_ambiente}")
    logger.info(f"Base de datos: {settings.database_url}")

    # ---- Chequeo de seguridad: avisar siempre; en producción, abortar ----
    problemas = settings.problemas_seguridad()
    for p in problemas:
        logger.warning("SEGURIDAD: %s", p)
    if problemas and settings.es_produccion:
        raise RuntimeError(
            "Arranque abortado: hay configuración insegura en PRODUCCIÓN. "
            "Corrige antes de emitir DTE reales → " + " | ".join(problemas))

    # Crear directorios necesarios
    settings.ensure_directories()
    logger.info(f"Directorio storage: {settings.storage_dir}")

    # Inicializar base de datos
    init_db()
    logger.info("Base de datos inicializada correctamente")

    # Crear usuario admin si no existe ningún usuario
    usuarios = listar_usuarios()
    if not usuarios:
        # Password admin: el de ADMIN_PASSWORD (env) o uno ALEATORIO fuerte, mostrado
        # UNA sola vez. Nunca más el universal "admin123".
        generada = not os.environ.get("ADMIN_PASSWORD")
        admin_password = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
        crear_usuario(
            username="admin",
            hashed_password=hash_password(admin_password),
            nombre_completo="Administrador",
            email="admin@localhost",
        )
        logger.warning("=" * 60)
        logger.warning("USUARIO ADMIN CREADO — usuario: admin")
        if generada:
            logger.warning("  Password (ALEATORIA, se muestra solo esta vez): %s", admin_password)
        else:
            logger.warning("  Password: la definida en ADMIN_PASSWORD")
        logger.warning("  Guárdala y cámbiala tras el primer login.")
        logger.warning("=" * 60)
    else:
        logger.info(f"Usuarios registrados: {len(usuarios)}")

    # Programador del RVD diario (obligación de boletas). Vive dentro del proceso —sin
    # cron ni launchd— para que el servidor funcione igual en Windows, macOS y Linux.
    if settings.rvd_scheduler_activo:
        programador.intervalo_seg = settings.rvd_intervalo_seg
        programador.iniciar()
    else:
        logger.info("Programador de RVD desactivado (RVD_SCHEDULER_ACTIVO=false)")

    # Gestión automática de folios (independiente del RVD): repone antes de quedarse sin folios.
    if settings.folios_auto_activo:
        programador_folios.intervalo_seg = settings.folios_auto_intervalo_seg
        programador_folios.iniciar()
    else:
        logger.info("Gestión automática de folios desactivada (FOLIOS_AUTO_ACTIVO=false)")

    logger.info(f"API disponible en http://{settings.host}:{settings.port}")
    logger.info(f"Documentación: http://localhost:{settings.port}/docs")

    yield

    await programador.detener()
    await programador_folios.detener()
    logger.info("Deteniendo DTE Chile API...")


# ---- Metadata de la API ----
app = FastAPI(
    title=settings.app_name,
    description="""
## API REST para Facturación Electrónica en Chile

Motor de facturación electrónica (DTE) compatible con el SII de Chile.
Permite generar, firmar y enviar Documentos Tributarios Electrónicos.

### Funcionalidades

- **Autenticación**: Login con JWT para proteger endpoints.
- **Certificado Digital**: Validación de certificados `.p12`/`.pfx` y firma XML.
- **CAF (Folios)**: Carga y validación de Códigos de Autorización de Folios.
- **DTE**: Generación de Facturas, Boletas y Notas de Crédito/Débito en formato XML firmado.
- **SII**: Envío de documentos al SII y consulta de estado por TrackID.
- **PDF**: Generación de representación gráfica con timbre PDF417.
- **Base de Datos**: Persistencia de DTEs emitidos, CAFs y logs de auditoría.

### Tipos de DTE Soportados

| Tipo | Documento |
|------|-----------|
| 33   | Factura Electrónica |
| 34   | Factura No Afecta o Exenta |
| 39   | Boleta Electrónica |
| 41   | Boleta No Afecta o Exenta |
| 52   | Guía de Despacho Electrónica |
| 56   | Nota de Débito Electrónica |
| 61   | Nota de Crédito Electrónica |

### Flujo de Uso Típico

1. `POST /api/v1/auth/login` — Autenticarse y obtener token JWT.
2. `POST /api/v1/certificado/validar` — Verificar el certificado digital.
3. `POST /api/v1/caf/info` — Cargar y revisar el CAF de folios.
4. `POST /api/v1/dte/generar` — Generar y firmar el DTE.
5. `POST /api/v1/dte/enviar` — Enviar el DTE al SII.
6. `GET  /api/v1/estado/track` — Consultar el estado del envío.
7. `POST /api/v1/dte/pdf` — Generar el PDF del DTE.
    """,
    version=settings.app_version,
    contact={
        "name": "DTE Chile API",
        "url": "https://github.com/tuusuario/dte-chile-api",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---- Middleware CORS ----
# Con orígenes "*" NO se permiten credenciales (la spec CORS lo prohíbe y los
# navegadores lo rechazan); restringe CORS_ORIGINS para habilitar credenciales.
_cors_wildcard = settings.cors_origins.strip() == "*"
if _cors_wildcard:
    logging.getLogger("dte.startup").warning(
        "SEGURIDAD: CORS abierto a '*' (sin credenciales). Restringe CORS_ORIGINS.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=not _cors_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Exposición pública acotada: el subdominio público solo ve el buscador de boletas ----
# Si el Host de la request es `settings.dominio_publico_boletas`, la app redirige "/" a
# "/consulta" y responde 404 a cualquier ruta que no sea "/consulta*" (ni /docs ni la API,
# que tiene endpoints sin JWT). El acceso INTERNO (por IP:puerto) no lleva ese Host → sin
# restricción. La seguridad asume que Internet solo entra por el reverse proxy con ese Host.
_HOST_PUBLICO = settings.dominio_publico_boletas.strip().lower()


@app.middleware("http")
async def _acotar_dominio_publico(request: Request, call_next):
    if _HOST_PUBLICO:
        host = (request.headers.get("host") or "").split(":")[0].lower()
        if host == _HOST_PUBLICO:
            path = request.url.path
            if path == "/":
                return RedirectResponse("/consulta", status_code=302)
            if not (path == "/consulta" or path.startswith("/consulta/")
                    or path.startswith("/static/")):
                return JSONResponse({"detail": "No disponible"}, status_code=404)
    return await call_next(request)


# ---- Manejo de errores uniforme + request-id + logging de acceso ----
registrar_manejo_errores(app)

# ---- Registrar routers ----
app.include_router(auth.router)
# Routers antes abiertos: se protegen a nivel de router (JWT o API key) para cerrar el hueco.
_PROTEGIDO = [Depends(requerir_autenticacion)]
app.include_router(certificado.router, dependencies=_PROTEGIDO)
app.include_router(caf.router, dependencies=_PROTEGIDO)
app.include_router(dte.router, dependencies=_PROTEGIDO)
app.include_router(status.router, dependencies=_PROTEGIDO)
app.include_router(db.router)
app.include_router(keystore.router)
app.include_router(onboarding.router)
app.include_router(apikeys.router)
app.include_router(monitoreo.router)
app.include_router(consulta.router)


# ---- Frontend (páginas estáticas) ----
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/certificados", tags=["Frontend"], include_in_schema=False,
         summary="Página de gestión de certificados")
async def pagina_certificados():
    """Sirve la página para subir/gestionar certificados (usa /api/v1/keystore/*)."""
    return FileResponse(str(_STATIC_DIR / "certificados.html"))


@app.get("/onboarding", tags=["Frontend"], include_in_schema=False,
         summary="Asistente de puesta en marcha (wizard)")
async def pagina_onboarding():
    """Sirve el wizard de onboarding (cert → empresa → diagnóstico + plan)."""
    return FileResponse(str(_STATIC_DIR / "onboarding.html"))


@app.get("/apikeys", tags=["Frontend"], include_in_schema=False,
         summary="Gestión de API keys")
async def pagina_apikeys():
    """Sirve la UI para crear/revocar API keys (integraciones/agentes)."""
    return FileResponse(str(_STATIC_DIR / "apikeys.html"))


# ---- Rutas raíz ----
@app.get("/", tags=["Health"], summary="Health check")
async def root():
    """Verifica que la API esté funcionando correctamente."""
    return {
        "status": "ok",
        "servicio": settings.app_name,
        "version": settings.app_version,
        "documentacion": "/docs",
        "ambiente_sii": settings.sii_ambiente,
        "empresa_configurada": settings.empresa_configurada,
    }


@app.get("/health", tags=["Health"], summary="Estado detallado del servicio")
async def health():
    """Retorna el estado detallado del servicio."""
    from datetime import datetime

    dependencias = {}
    libs = ["lxml", "cryptography", "signxml", "reportlab", "pdf417gen", "httpx"]
    for lib in libs:
        try:
            __import__(lib)
            dependencias[lib] = "ok"
        except ImportError:
            dependencias[lib] = "no instalada"

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "python_version": sys.version,
        "ambiente_sii": settings.sii_ambiente,
        "empresa_configurada": settings.empresa_configurada,
        "dependencias": dependencias,
    }


# ---- Inicialización al importar ----
configurar_logging()
