// Reemplazo CONSISTENTE de datos personales (RUT, correos, celulares) por ficticios.
// No tacha: sustituye cada valor real por uno inventado que siempre es el mismo dentro de la
// captura (hash del valor + una semilla por grabación), así un agente sigue viendo "este RUT
// aparece en estas tres páginas" sin saber cuál es. Los RUT ficticios son válidos (módulo 11)
// y conservan el formato (puntos, guion). Mismo algoritmo en limpiar_captura.py.
(function (raiz) {
  // FNV-1a de 32 bits sobre UTF-8: determinista y portable (Python lo replica).
  function fnv(s) {
    let h = 0x811c9dc5;
    for (const b of new TextEncoder().encode(s)) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
    return h >>> 0;
  }
  function digitos(semilla, valor, n) {
    let out = "";
    for (let i = 0; out.length < n; i++) out += String(fnv(semilla + "|" + valor + "|" + i)).padStart(10, "0");
    return out.slice(0, n);
  }
  function dvRut(num) {
    let s = 0, m = 2;
    for (const c of String(num).split("").reverse()) { s += Number(c) * m; m = m === 7 ? 2 : m + 1; }
    const r = 11 - (s % 11);
    return r === 11 ? "0" : r === 10 ? "K" : String(r);
  }
  // Un RUT ficticio del mismo "tipo": personas 10-24 millones, empresas 76-77 millones.
  function rutFicticio(semilla, numReal) {
    const n = Number(numReal);
    const d = digitos(semilla, "rut:" + n, 7);
    const base = n >= 50_000_000 ? 76_000_000 + (Number(d) % 2_000_000) : 10_000_000 + (Number(d) % 15_000_000);
    return { num: String(base), dv: dvRut(base) };
  }
  function conFormato(original, nuevosDigitos) {
    // Sustituye solo los dígitos, en orden; conserva puntos, guiones, espacios y '+'.
    let k = 0;
    return original.replace(/\d/g, () => nuevosDigitos[k++] ?? "0");
  }
  const RE_RUT = /\b(\d{1,2}\.?\d{3}\.?\d{3})-([\dkK])\b/g;
  const RE_RUT_PARAM = /((?:^|[?&;"'\s])[A-Za-z_]*rut[A-Za-z_]*(?:[\\]?["']?\s*[:=]\s*[\\]?["']?))(\d{7,8})(?![\d-])/gi;
  const RE_MAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
  const RE_CEL = /(?<![\d])(\+?56[\s.-]?)?(9[\s.-]?\d{4}[\s.-]?\d{4})(?![\d])/g;
  function crear(semilla) {
    const mailDe = m => { const d = digitos(semilla, "mail:" + m.toLowerCase(), 4); return `persona${d}@ejemplo.cl`; };
    function reemplazar(texto) {
      if (texto == null) return texto;
      return String(texto)
        .replace(RE_RUT, (todo, num) => { const f = rutFicticio(semilla, num.replace(/\./g, "")); return conFormato(num, f.num) + "-" + f.dv; })
        .replace(RE_RUT_PARAM, (todo, pre, num) => pre + rutFicticio(semilla, num).num)
        .replace(RE_MAIL, m => mailDe(m))
        .replace(RE_CEL, (todo, pre, cel) => (pre || "") + conFormato(cel, "9" + digitos(semilla, "cel:" + cel.replace(/\D/g, ""), 8)));
    }
    function sobre(obj) {   // aplica a todas las cadenas de un objeto (entrada de la captura)
      if (typeof obj === "string") return reemplazar(obj);
      if (Array.isArray(obj)) return obj.map(sobre);
      if (obj && typeof obj === "object") { const o = {}; for (const [k, v] of Object.entries(obj)) o[k] = sobre(v); return o; }
      return obj;
    }
    return { reemplazar, sobre };
  }
  function auditar(texto) {
    const s = String(texto || "");
    return { ruts: (s.match(RE_RUT) || []).length, correos: (s.match(RE_MAIL) || []).length, celulares: (s.match(RE_CEL) || []).length };
  }
  raiz.CapturaPII = { crear, auditar, fnv, dvRut };
})(typeof self !== "undefined" ? self : globalThis);
