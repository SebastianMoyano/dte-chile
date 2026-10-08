// Prueba rápida del tachado y del reemplazo de datos personales: node prueba_tachado.test.js
globalThis.self = globalThis; require("./tachar.js"); require("./pii.js");
const { tachar, sobre, auditar } = self.CapturaTachar; const pii = self.CapturaPII.crear("semilla-prueba");
const JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c";
const U = "3fa85f64-5717-4562-b3fc-2c963f66afa6";
let fallos = 0; const ok = (c, m) => { console.log((c ? "✓ " : "✗ ") + m); if (!c) fallos++; };
const secretos = [`https://x.cl/api?api_token=${U}&user=1`, `{"api_token":"${U}","access-token":"abc123def456"}`,
  `<input name="api_token" value="${U}"><input type="password" value="hola123">`, `window.AUTH={jwt:"${JWT}"}`, `Authorization: Bearer ${JWT}`,
  `const sessionId = "${U}"; var apiKey='9f8e7d6c5b4a39281716151413121110'`];
ok(secretos.every(s => !/3fa85f64|eyJhbGci|hola123|abc123def456|9f8e7d6c/.test(tachar(s))), "secretos: nombre parcial, JWT, Bearer, password, hex, uuid");
ok(tachar("folio 112 total 23.800 rut 12345678-5") === "folio 112 total 23.800 rut 12345678-5", "texto inocente intacto");
const obj = { entradas: [{ texto: "hola\nana.perez@colegio.cl\tRUT 12.345.678-5\r\n+56 9 8765 4321", html: `mailto:ana.perez@colegio.cl\n"api_token": "${U}" ${JWT}` }] };
const json = JSON.stringify(sobre(pii.sobre(obj)), null, 1);
let valido = true; try { JSON.parse(json); } catch { valido = false; }
ok(valido, "pasada final sobre valores → JSON válido");
ok(!/ana\.perez|12\.345\.678|8765 4321|3fa85f64|eyJhbGci/.test(json), "sin datos reales ni secretos tras la pasada final");
ok(JSON.parse(json).entradas[0].texto.includes("\n"), "saltos de línea intactos");
const r1 = pii.reemplazar("12.345.678-5 y 12345678-5"), m = r1.match(/[\d.]+-\w/g);
ok(m && m[0].replace(/\./g, "") === m[1], "mismo RUT con y sin puntos → mismo ficticio");
ok(pii.reemplazar("+56 2 2345 6789 folio 57") === "+56 2 2345 6789 folio 57", "fijo y folio intactos");
const a = auditar(json); ok(a.jwt_sin_tachar === 0 && a.uuid_tras_nombre_sensible === 0, "auditoría en 0");
console.log(fallos ? `FALLOS: ${fallos}` : "TODO OK"); process.exit(fallos ? 1 : 0);
