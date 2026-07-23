# 🚀 Guía de inicio rápido

De cero a emitir tu primer documento, paso a paso. Pensada para alguien que sabe usar la
terminal pero **no es experto en el SII**. Tiempo estimado: 20–30 minutos.

> ¿Solo quieres entender la plataforma o integrarla desde otra app/IA? Ve a
> [`PLATAFORMA.md`](PLATAFORMA.md). Esta guía es para **ponerla a andar y emitir**.

---

## Antes de empezar necesitas

1. **Docker** instalado — es la vía más fácil ([Docker Desktop](https://www.docker.com/products/docker-desktop/), un instalador normal).
2. Tu **certificado digital** (`.pfx` o `.p12`) a nombre del **representante legal** de la empresa. Se compra en e-cert, Acepta, etc.
3. Estar **inscrito ante el SII** como emisor electrónico para el tipo de documento que emitirás. Si aún no lo estás, hay que **certificar** primero (ver [`CERTIFICACION.md`](CERTIFICACION.md)).

---

## Paso 1 — Levantar el motor

```bash
git clone https://github.com/SebastianMoyano/dte-chile.git
cd dte-chile
cp .env.example .env      # la configuración; los valores por defecto sirven para empezar
docker compose up -d      # levanta el servidor en segundo plano
```

Espera ~1 minuto y comprueba que está vivo:

```bash
curl http://localhost:8000/health
# debe responder {"status":"ok", ...}
```

**La clave del admin** se genera sola la primera vez y se imprime **una sola vez** en el log:

```bash
docker compose logs | grep -i "password\|admin"
```

Guárdala. *(Alternativa: pon `ADMIN_PASSWORD=tu-clave` en el `.env` **antes** del primer arranque.)*

---

## Paso 2 — Abrir la interfaz

- **Swagger** (probar la API haciendo clic): http://localhost:8000/docs
- **Gestión de API keys** (para conectar tu propia app luego): http://localhost:8000/apikeys

En Swagger, arriba a la derecha hay un botón **Authorize** 🔓 — ahí pegas tu token para probar los endpoints protegidos. Consíguelo así:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"LA-CLAVE-DEL-PASO-1"}'
# copia el "access_token" y pégalo en Authorize como:  Bearer <token>
```

---

## Paso 3 — Subir tu certificado

Sube tu `.pfx` una vez. Se guarda **cifrado** en la base de datos (nunca en disco):

```bash
TOKEN="<tu-access_token>"
curl -X POST http://localhost:8000/api/v1/keystore/certificados \
  -H "Authorization: Bearer $TOKEN" \
  -F "archivo=@/ruta/a/tu-certificado.pfx" \
  -F "password=CLAVE-DEL-PFX" \
  -F "nombre=Mi certificado"
# anota el "id" que devuelve (ej. 1) — es tu cert_id
```

---

## Paso 4 — Registrar tu empresa

```bash
curl -X POST http://localhost:8000/api/v1/keystore/negocios \
  -H "Authorization: Bearer $TOKEN" \
  -F "rut=76111111-6" -F "cert_id=1"
# el motor autocompleta la razón social desde el SII
```

---

## Paso 5 — ¿Qué me falta? (diagnóstico)

El motor lee tu situación real en el SII y te dice qué está listo y qué falta:

```bash
curl "http://localhost:8000/api/v1/onboarding/diagnostico?rut=76111111-6&cert_id=1" \
  -H "Authorization: Bearer $TOKEN"
```

Te dirá si estás autorizado, qué tipos de documento puedes emitir, y si necesitas certificar.

---

## Paso 6 — Folios

Baja tu primer lote de folios (el CAF del SII). **De ahí en adelante se reponen solos** cuando
bajan del umbral.

```bash
# desde el CLI del motor (dentro del contenedor):
docker compose exec dte-api python solicitar_caf_sii.py --rut 76111111-6 --tipo 39 --cantidad 10
```

*(La cantidad la decides tú; para un emisor nuevo el SII suele dar lotes chicos.)*

---

## Paso 7 — Emitir tu primer documento

Ejemplo: una **boleta** (tipo 39) de $1.000 a consumidor final.

```bash
curl -X POST http://localhost:8000/api/v1/dte/emitir \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "dte": {
      "tipo_dte": 39,
      "emisor": {"rut": "76111111-6", "razon_social": "MI EMPRESA SPA",
                 "giro": "Servicios", "codigo_actividad": 620900,
                 "direccion": "Calle 123", "comuna": "Santiago", "ciudad": "Santiago"},
      "receptor": {"rut": "66666666-6", "razon_social": "CONSUMIDOR FINAL"},
      "items": [{"numero_linea": 1, "nombre": "Servicio", "cantidad": 1, "precio_unitario": 1000}]
    }
  }'
```

Devuelve el **folio**, el **TrackID** del SII, y el estado. Para facturas usa `"tipo_dte": 33`
y agrega los datos reales del receptor.

---

## Paso 8 — El buscador de consulta

Tus clientes verifican su documento en `http://localhost:8000/consulta` (o en tu dominio). Es
público a propósito: es el **Link de Consulta** que el SII exige que imprimas en la boleta.

---

## Conectar tu propia app / una IA

- **Tu app** → crea una API key en http://localhost:8000/apikeys y llama a la API con
  `Authorization: Bearer dte_...`. No expone tu login.
- **Una IA/agente** → levanta el servidor MCP: `MCP_AUTH_TOKEN=<clave> python mcp_server.py http 0.0.0.0 8090`
  y apúntala ahí. Trae ~20 herramientas listas (emitir, folios, estado, diagnóstico).

Detalle en [`PLATAFORMA.md`](PLATAFORMA.md) §3–4.

---

## Problemas comunes

| Síntoma | Causa / solución |
|---|---|
| `CRT-3-19` al enviar | Resolución de carátula equivocada — el motor la saca por empresa; verifica que el RUT esté bien registrado. |
| `401` en un endpoint | Falta el `Authorization: Bearer` (token o API key). |
| No encuentro la clave del admin | Está en `docker compose logs` (primer arranque), o defínela con `ADMIN_PASSWORD` en `.env`. |
| El SII "acepta" pero el set de boletas rechaza | El set de certificación va por DTEUpload, no por el REST — ver [`LECCIONES-SII.md`](LECCIONES-SII.md). |
| Me quedé sin folios a mitad de venta | Suben el umbral (`FOLIOS_AUTO_UMBRAL`) o el lote — se reponen solos. |

---

## Siguiente paso

- [`PLATAFORMA.md`](PLATAFORMA.md) — la referencia completa (API, seguridad, integración).
- [`CERTIFICACION.md`](CERTIFICACION.md) — cómo certificarte ante el SII si aún no eres emisor.
- [`CONSTITUCION.md`](CONSTITUCION.md) — reglas del motor (si vas a modificar el código).
