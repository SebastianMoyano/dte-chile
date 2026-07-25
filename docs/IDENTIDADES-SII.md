# ¿Con qué identidad entro a cada trámite del SII?

> **Por qué existe este documento**: cada aplicación del SII exige una identidad distinta —
> a veces la **empresa**, a veces la **persona autorizada**, a veces el **representante
> legal** — y ninguna pantalla te lo dice antes de rebotarte. Este mapa se pagó con días de
> prueba y error (2026-07, verificado en vivo). Si un trámite te rechaza, lo primero que hay
> que revisar es **con qué RUT entraste**, no tus permisos.

## Las tres identidades

| Identidad | Qué es | Credencial típica |
|---|---|---|
| **EMPRESA** | El RUT de la sociedad (ej. `77777777-7`) | Clave Tributaria **de la empresa** |
| **PERSONA autorizada** | Una persona natural registrada como usuaria/firmante de la empresa | Su Clave Tributaria / Clave Única / certificado digital **personal** |
| **REP. LEGAL** | El representante legal de la sociedad | Su clave o certificado personal (el SII verifica el vínculo) |

Regla de oro: **los documentos los firman personas; los atributos de la empresa los declara la
empresa.** Si el trámite produce un documento (boleta, factura, NC), pide una persona; si
configura cómo opera la sociedad (modelo de emisión, régimen), pide la empresa.

## El mapa de trámites

| Trámite | URL | Entrar como | Notas |
|---|---|---|---|
| **Emitir boletas/facturas con software propio** (este motor) | — (API del motor) | **PERSONA** (su certificado digital firma los DTE) | El cert debe ser de un firmante autorizado de la empresa |
| **Timbraje / solicitar folios (CAF)** | `palena.sii.cl/cvc_cgi/dte` (prod) / `maullin` (cert) | **PERSONA** (certificado) | Solo puede anular rangos quien los timbró (mandatario) |
| **Mantención de usuarios autorizados** (permisos Firmar/Enviar/Registro) | `.../cvc_cgi/dte/eu_enrola_usuarios` | **PERSONA** (el usuario administrador) | "Firmar Documentos" = ser firmante/signatario (Res. 74) |
| **Declaración de modelo de emisión** (voucher vs boleta) | `www4.sii.cl/actatributointernetui` | **EMPRESA** | Con clave/cert de persona responde *"solo para usuarios de boletas"* → ver [`MODELO-EMISION.md`](MODELO-EMISION.md) |
| **Emitir NC de anulación de boletas (portal MIPYME)** | `www1.sii.cl/cgi-bin/Portal001/mipeSelEmpresaBol.cgi` | **PERSONA** (Clave Única / RUT+clave; login nuevo) | ⚠️ Bloqueo conocido incluso con la persona correcta → ver [`ANULAR-BOLETA.md`](ANULAR-BOLETA.md); Mesa de Ayuda (2) 2395 1115 |
| **Postulación a certificación** (factura o boleta) | `maullin.sii.cl/cvc_cgi/dte/pe_ingrut` | **REP. LEGAL** (certificado) | Ver [`CERTIFICACION.md`](CERTIFICACION.md) |
| **Declaración de Cumplimiento** (go-live) | portal de certificación del SII | **REP. LEGAL** | Único paso estrictamente humano del go-live |
| **Registro de Compras y Ventas** (RCV) | `www4.sii.cl/consdcvinternetui` | **EMPRESA** (o persona con vínculo) | Ahí aparecen las ventas informadas (boletas, vouchers cód. 48) |
| **Consultar validez / contenido de una boleta** | `www4.sii.cl/bolcoreinternetui` / `www2.sii.cl/bolcore/` | **Público** (sin login para validez; contenido pide datos del doc) | |
| **Consultar autorización DTE de cualquier RUT** | `.../cvc_cgi/dte/ee_empresa_rut` | **Público** | El motor la usa (`consultar_empresa_autorizada`) |
| **F29 / declaraciones mensuales** | Mi SII | **EMPRESA** (o contador con vínculo) | |

## Los dos rechazos clásicos (y qué significan)

- *"No es posible hacerlo con el RUT y Clave de la empresa… ingrese con la persona
  autorizada"* → entraste como **empresa** a un trámite de **persona** (o hay una sesión
  anterior pegada: cierra todo y reintenta). Si persiste con la persona correcta y en más de
  una empresa: [`ANULAR-BOLETA.md`](ANULAR-BOLETA.md#si-aun-así-te-rebota).
- *"Esta aplicación es solo para usuarios de boletas de ventas y servicios electrónicas"* →
  entraste como **persona** a un trámite de **empresa** (la app lee tu RUT personal, que no
  es emisor de boletas).

## Otra trampa: sesiones pegadas

El SII limita las **sesiones concurrentes por RUT** y no las cierra solo. Una sesión anterior
abierta produce rechazos que parecen de permisos ("superó el máximo de sesiones", rebotes al
login). Antes de pelear con un trámite: **Cerrar Sesión** en todas las pestañas y reintentar
limpio. (El motor cierra las suyas automáticamente — `autTermino.cgi` en `finally`.)
