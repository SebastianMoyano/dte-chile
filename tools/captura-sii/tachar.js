// Tachado de secretos, compartido por el fondo (background.js) y por la auditoría final.
// Dos capas: (1) por NOMBRE: cualquier parámetro/campo/clave JSON/cabecera cuyo nombre CONTENGA
// una palabra sensible (api_token, access-token, x-csrf, sessionId…), en URLs, formularios, JSON
// y HTML; (2) por VALOR: lo que parezca credencial aunque su nombre sea inocente: JWT
// (eyJ….eyJ….firma), Bearer, hex largo (≥32), base64url largo junto a nombres sensibles.
// Se aplica a cuerpos, respuestas, HTML, texto visible, URLs y, al final, al JSON entero.
(function (raiz) {
  const PALABRAS = "clave|contrase[nñ]a|password|passwd|pwd|pass|token|secret|api_?key|apikey|auth|csrf|xsrf|otp|pin|session|sess|sid|jwt|bearer|credential|myPass|SII_PASSWORD|SII_CERT_PASS";
  const NOMBRE = `[A-Za-z0-9_.\\-]*(?:${PALABRAS})[A-Za-z0-9_.\\-]*`;
  // Comilla "tolerante": dentro de un JSON serializado las comillas van escapadas (\"), y un
  // tachado que no lo sepa deja pasar \"api_token\": \"…\". Fue el agujero de la v3.0.
  const Q = `\\\\?["']`;
  const RE = {
    jwt: /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g,
    bearer: /(Bearer\s+)[A-Za-z0-9._~+\/=-]{8,}/gi,
    query: new RegExp(`((?:^|[?&;])${NOMBRE}=)[^&;\\s"'<>\\\\]*`, "gi"),
    json: new RegExp(`(${Q}${NOMBRE}${Q}\\s*:\\s*${Q})[^"'\\\\]*(${Q})`, "gi"),
    html: new RegExp(`(name=${Q}${NOMBRE}${Q}[^>]*value=${Q})[^"'\\\\]*(${Q})`, "gi"),
    htmlInv: new RegExp(`(value=${Q})[^"'\\\\]*(${Q}[^>]*name=${Q}${NOMBRE}${Q})`, "gi"),
    password: new RegExp(`(<input[^>]*type=${Q}password${Q}[^>]*value=${Q})[^"'\\\\]*(${Q})`, "gi"),
    asignacion: new RegExp(`(\\b${NOMBRE}\\s*[:=]\\s*${Q})[^"'\\\\]{6,}(${Q})`, "gi"),
    hexLargo: /\b[a-f0-9]{32,}\b/gi,
    uuidTrasNombre: new RegExp(`(${NOMBRE}(?:${Q})?\\s*[:=]\\s*(?:${Q})?)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`, "gi"),
    cookie: /(NETSCAPE_LIVEWIRE\.mac=|(?:TOKEN|CSESSIONID|JSESSIONID|PHPSESSID)=)[^;\s"]*/g,
  };
  const NOMBRE_RE = new RegExp(`^${NOMBRE}$`, "i");
  // Aplica el tachado a cada cadena de un objeto (recorriéndolo), NO al JSON serializado: así
  // los escapes (\n, \", \uXXXX) nunca se parten y quien serialice después produce JSON válido.
  function sobre(obj) {
    if (typeof obj === "string") return tachar(obj);
    if (Array.isArray(obj)) return obj.map(sobre);
    if (obj && typeof obj === "object") { const o = {}; for (const [k, v] of Object.entries(obj)) o[k] = sobre(v); return o; }
    return obj;
  }
  function tachar(texto) {
    if (texto == null) return texto;
    return String(texto)
      .replace(RE.jwt, "***JWT***")
      .replace(RE.bearer, "$1***")
      .replace(RE.query, "$1***")
      .replace(RE.json, "$1***$2")
      .replace(RE.html, "$1***$2")
      .replace(RE.htmlInv, "$1***$2")
      .replace(RE.password, "$1***$2")
      .replace(RE.uuidTrasNombre, "$1***")
      .replace(RE.asignacion, "$1***$2")
      .replace(RE.hexLargo, "***HEX***")
      .replace(RE.cookie, "$1***");
  }
  // Lo que quede que PAREZCA secreto después de tachar: para avisar, no para confiar.
  function auditar(texto) {
    const s = String(texto || "");
    const jwt = (s.match(/eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g) || []).length;
    const uuidTok = (s.match(new RegExp(`${NOMBRE}(?:${Q})?\\s*[:=]\\s*(?:${Q})?[0-9a-f]{8}-[0-9a-f]{4}-`, "gi")) || []).length;
    const largos = (s.match(/\b[A-Za-z0-9_-]{48,}\b/g) || []).filter(x => !/^\*+$/.test(x)).length;
    const conteo = {};
    for (const u of s.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi) || []) conteo[u.toLowerCase()] = (conteo[u.toLowerCase()] || 0) + 1;
    const repetidos = Object.entries(conteo).filter(([, n]) => n >= 3).map(([u, n]) => `${u.slice(0, 8)}… ×${n}`);
    return { jwt_sin_tachar: jwt, uuid_tras_nombre_sensible: uuidTok, cadenas_largas: largos, uuids_repetidos_3_o_mas: repetidos };
  }
  raiz.CapturaTachar = { tachar, sobre, auditar, esNombreSensible: n => NOMBRE_RE.test(n || "") };
})(typeof self !== "undefined" ? self : globalThis);
