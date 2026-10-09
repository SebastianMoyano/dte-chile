-- 0001_base: el esquema completo que Python creaba al arrancar (core/database.py::SCHEMA_SQL,
-- core/keystore.py, core/apikeys.py, core/negocios.py, core/resolucion.py, core/rcv.py,
-- core/folios_auto.py), copiado literal el 2026-10-09. Desde aquí el esquema lo define Go
-- (fase 7 del port); Python sigue corriendo sus CREATE TABLE IF NOT EXISTS sin efecto.

CREATE TABLE IF NOT EXISTS dtes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_dte INTEGER NOT NULL,
    folio INTEGER NOT NULL,
    rut_emisor TEXT NOT NULL,
    rut_receptor TEXT NOT NULL,
    razon_social_receptor TEXT,
    fecha_emision TEXT NOT NULL,
    monto_neto INTEGER DEFAULT 0,
    monto_exento INTEGER DEFAULT 0,
    iva INTEGER DEFAULT 0,
    monto_total INTEGER NOT NULL,
    estado TEXT DEFAULT 'generado',
    track_id INTEGER,
    xml_firmado TEXT,
    pdf_path TEXT,
    ambiente TEXT DEFAULT 'certificacion',
    creado_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL,
    UNIQUE(rut_emisor, tipo_dte, folio)
);

CREATE TABLE IF NOT EXISTS cafs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_dte INTEGER NOT NULL,
    rut_emisor TEXT NOT NULL,
    folio_desde INTEGER NOT NULL,
    folio_hasta INTEGER NOT NULL,
    folio_siguiente INTEGER NOT NULL,
    fecha_autorizacion TEXT NOT NULL,
    caf_xml TEXT NOT NULL,
    activo INTEGER DEFAULT 1,
    creado_en TEXT NOT NULL,
    UNIQUE(rut_emisor, tipo_dte, folio_desde, folio_hasta)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    accion TEXT NOT NULL,
    tipo_dte INTEGER,
    folio INTEGER,
    rut_emisor TEXT,
    detalle TEXT,
    ip_origen TEXT,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    nombre_completo TEXT,
    email TEXT,
    activo INTEGER DEFAULT 1,
    creado_en TEXT NOT NULL,
    ultimo_acceso TEXT
);

CREATE TABLE IF NOT EXISTS rvd_envios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rut_emisor TEXT NOT NULL,
    fecha TEXT NOT NULL,
    sec_envio INTEGER NOT NULL DEFAULT 1,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    track_id TEXT,
    xml_path TEXT,
    detalle TEXT,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT,
    UNIQUE(rut_emisor, fecha, sec_envio)
);

CREATE TABLE IF NOT EXISTS valores (
    indicador   TEXT NOT NULL,
    fecha       TEXT NOT NULL,
    valor       REAL NOT NULL,
    actualizado TEXT NOT NULL,
    PRIMARY KEY (indicador, fecha)
);

CREATE INDEX IF NOT EXISTS idx_rvd_rut_fecha ON rvd_envios(rut_emisor, fecha);
CREATE INDEX IF NOT EXISTS idx_dtes_tipo_folio ON dtes(tipo_dte, folio);
CREATE INDEX IF NOT EXISTS idx_dtes_rut_emisor ON dtes(rut_emisor);
CREATE INDEX IF NOT EXISTS idx_dtes_estado ON dtes(estado);
CREATE INDEX IF NOT EXISTS idx_dtes_fecha ON dtes(fecha_emision);
CREATE INDEX IF NOT EXISTS idx_cafs_rut_tipo ON cafs(rut_emisor, tipo_dte);
CREATE INDEX IF NOT EXISTS idx_audit_fecha ON audit_log(creado_en);
CREATE INDEX IF NOT EXISTS idx_audit_accion ON audit_log(accion);

CREATE TABLE IF NOT EXISTS api_keys (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT NOT NULL,
    prefijo    TEXT NOT NULL,
    key_hash   TEXT NOT NULL UNIQUE,
    activo     INTEGER NOT NULL DEFAULT 1,
    creado     TEXT NOT NULL,
    ultimo_uso TEXT
);

CREATE TABLE IF NOT EXISTS folios_gestion (
    clave         TEXT PRIMARY KEY,
    ultima_accion TEXT,
    ultimo_ts     TEXT,
    detalle       TEXT
);

CREATE TABLE IF NOT EXISTS certificados (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id     INTEGER NOT NULL,
    rut           TEXT NOT NULL,
    nombre        TEXT,
    alias         TEXT,
    vencimiento   TEXT,
    p12_cifrado   BLOB NOT NULL,
    clave_cifrada BLOB NOT NULL,
    creado        TEXT NOT NULL,
    UNIQUE(cuenta_id, rut)
);

CREATE TABLE IF NOT EXISTS claves_sii (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id            INTEGER NOT NULL,
    rut_empresa          TEXT NOT NULL,
    rut_usuario          TEXT,
    tributaria_cifrada   BLOB,
    certificado_cifrada  BLOB,
    actualizado          TEXT NOT NULL,
    UNIQUE(cuenta_id, rut_empresa)
);

CREATE TABLE IF NOT EXISTS negocios (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id    INTEGER NOT NULL,
    rut          TEXT NOT NULL,
    razon_social TEXT,
    cert_id      INTEGER,
    ambiente     TEXT DEFAULT 'certificacion',
    creado       TEXT NOT NULL,
    UNIQUE(cuenta_id, rut)
);

CREATE TABLE IF NOT EXISTS resolucion_cache (
    rut       TEXT NOT NULL,
    ambiente  TEXT NOT NULL,
    fecha_iso TEXT NOT NULL,
    numero    INTEGER NOT NULL,
    ts        TEXT NOT NULL,
    PRIMARY KEY (rut, ambiente)
);

CREATE TABLE IF NOT EXISTS rcv_documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rut_empresa TEXT NOT NULL,
    tipo_operacion TEXT NOT NULL,
    periodo TEXT NOT NULL,
    tipo_dte INTEGER NOT NULL,
    folio INTEGER NOT NULL,
    fecha_doc TEXT,
    rut_contraparte TEXT DEFAULT '',
    razon_social TEXT DEFAULT '',
    monto_exento INTEGER DEFAULT 0,
    monto_neto INTEGER DEFAULT 0,
    monto_iva INTEGER DEFAULT 0,
    monto_iva_no_rec INTEGER DEFAULT 0,
    monto_iva_uso_comun INTEGER DEFAULT 0,
    monto_total INTEGER DEFAULT 0,
    estado_sii TEXT DEFAULT 'REGISTRO',
    clasificacion TEXT,
    origen TEXT DEFAULT 'rcv',
    creado_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL,
    UNIQUE(rut_empresa, tipo_operacion, tipo_dte, folio, rut_contraparte)
);
CREATE INDEX IF NOT EXISTS idx_rcv_empresa_periodo ON rcv_documentos(rut_empresa, periodo);
CREATE INDEX IF NOT EXISTS idx_rcv_operacion ON rcv_documentos(tipo_operacion);
