# Conectar tu IA al motor

Cómo hacer que un asistente de IA trabaje con tu facturación: ver documentos, revisar
folios, preparar y emitir. Hay dos mundos y conviene no confundirlos: **lo que importa no es
dónde está la ventana, sino desde dónde sale la conexión**.

| el asistente corre… | cómo se conecta | qué necesita |
|---|---|---|
| **en tu computador** (Claude Code, app de Claude, Cursor, VS Code, Windsurf, Gemini CLI, Codex CLI) | MCP por stdio: el cliente lanza `nucleo-mcp` (o la app con `--mcp`) y le habla por tuberías | nada: ni red, ni cuenta, ni token |
| **en la nube de un tercero** (claude.ai en el navegador o el celular, la app de ChatGPT, la app de Gemini) | sus conectores llaman **desde los servidores de esa empresa**, aunque la app esté instalada en tu PC | una URL pública con HTTPS y OAuth; está previsto (ver al final), no está hecho |

## En tu computador: un click

### Desde la app de escritorio

Pestaña **Tu IA**. Lista los asistentes que encontró en el computador y un botón "Conectar" por
cada uno. Al apretarlo, la app escribe en la configuración de ese programa una entrada que apunta
a **la misma app** lanzada con `--mcp` (no hay segundo binario). Reinicias el asistente y listo.
"Desconectar" la saca.

### Desde la terminal

```bash
nucleo/bin/nucleo-mcp clientes                 # qué asistentes hay y cuáles ya están conectados
nucleo/bin/nucleo-mcp instalar --en claude-code
nucleo/bin/nucleo-mcp instalar --en todos      # en todos los detectados
nucleo/bin/nucleo-mcp instalar --en cursor --quitar
nucleo/bin/nucleo-mcp instalar --en codex --env /ruta/a/mi/.env --json
```

Clientes y dónde escribe (macOS; en Windows `%APPDATA%`, en Linux `~/.config`):

| id | programa | archivo |
|---|---|---|
| `claude-code` | Claude Code | `~/.claude.json` (`mcpServers`, con `type: stdio`) |
| `claude-desktop` | app de escritorio de Claude | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| `cursor` | Cursor | `~/.cursor/mcp.json` |
| `vscode` | VS Code (Copilot) | `~/Library/Application Support/Code/User/mcp.json` (`servers`) |
| `windsurf` | Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| `gemini` | Gemini CLI | `~/.gemini/settings.json` |
| `codex` | Codex CLI | `~/.codex/config.toml` (`[mcp_servers.dte-chile]`) |

El instalador **conserva todo lo demás** del archivo (otros servidores, preferencias) y es
idempotente. Si el archivo no es JSON válido (VS Code admite comentarios) se niega a tocarlo y
te dice qué pegar a mano.

### Con doble click (app de Claude)

`./tools/empaquetar_mcpb.sh` produce `nucleo/bin/dte-chile.mcpb`: el paquete de instalación de la
app de escritorio de Claude (un zip con `manifest.json` y el binario, para macOS universal, Linux
y Windows). Se abre con doble click, Claude pregunta si instalar, y ya está. Sin Python, sin Node.

### Qué datos ve la IA

`nucleo-mcp` lleva el motor adentro, así que no necesita la app abierta. Decide su carpeta con la
misma regla que la app (`cliutil.ResolverRaiz`):

1. `--env /ruta/.env` explícito: esa carpeta.
2. un `.env` en el directorio actual (desarrollo, desde el repo).
3. la **carpeta de datos de la app** (`~/Library/Application Support/Faro`, `%AppData%\Faro`,
   `~/.config/Faro`; `DTE_DATOS` la cambia). Si no existe, la crea con su `.env`; si existe la
   antigua `DTE Chile`, la renombra la primera vez.

Así la IA y la app ven exactamente lo mismo, y si abren la base a la vez no pasa nada: cada una
es una conexión SQLite más, con el mismo `BEGIN IMMEDIATE` para los folios (`mcp.TestDosMotoresMismaBase`).

### Qué puede hacer

Las 20 herramientas de `nucleo/mcp` (las de `mcp_server.py`): salud, certificados y negocios del
keystore, empresa autorizada, timbrajes, situación y salud de folios (por empresa y por cartera),
solicitar y anular folios, diagnóstico de onboarding, datos del software, previsualizar, emitir,
enviar, estado de envíos. Las que gastan folios o cuentan ante el SII lo dicen en su descripción;
la IA se lo muestra al usuario antes. Las credenciales nunca viajan por el protocolo: cada tool
recibe un `cert_id` del keystore cifrado.

## En la nube de un tercero: lo que falta (y por qué no es un túnel)

Para claude.ai, ChatGPT o Gemini en la nube, el motor tiene que ser alcanzable desde internet y
autenticar con OAuth. La decisión (2026-10-11) es:

- **El motor no sabe por dónde lo alcanzan.** Sirve un handler HTTP; quien quiera exponerlo pone
  su propio reverse proxy, Cloudflare Tunnel, Tailscale Funnel o lo que exista mañana.
  **No se embebe ningún túnel en el binario**: cada uno exige cuenta de un tercero y engorda el
  producto, y lo local cubre a casi todos sin infraestructura.
- Lo que sí va dentro del motor cuando se haga: OAuth 2.1 (descubrimiento, registro dinámico,
  PKCE) con el login y los usuarios que ya existen, **alcances** (solo lectura vs. emitir), audit
  de cada llamada, límite de tasa y revocación desde el panel. El transporte ya es el de la
  spec: `nucleo-mcp --http` habla *Streamable HTTP* (sin estado: `POST /mcp` con JSON, `Origin`
  validado, `MCP-Protocol-Version`), así que cualquier cliente `http` lo conecta hoy, con
  `MCP_AUTH_TOKEN` como bearer, detrás de un proxy con TLS; nunca HTTP plano a internet.

  ```bash
  MCP_AUTH_TOKEN=... nucleo-mcp --http 127.0.0.1:8090 --db dte_database.db
  claude mcp add --transport http dte http://127.0.0.1:8090/mcp --header "Authorization: Bearer $MCP_AUTH_TOKEN"
  ```

## REST y CLI

Lo que no habla MCP se conecta igual de directo: `curl` a `http://127.0.0.1:<puerto>/api/v1/...`
con una API key (panel `/apikeys`), y los binarios `nucleo-*` con `--json` para scripts. Ver
[`PLATAFORMA.md`](PLATAFORMA.md).
