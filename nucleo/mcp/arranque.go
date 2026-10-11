package mcp

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"

	"dtechile/nucleo/cliutil"
	"dtechile/nucleo/servidor"
)

// Arrancar levanta el motor en proceso y el servidor MCP encima, con la misma regla de
// carpeta que la app (cliutil.ResolverRaiz): --env explícito, o el .env del directorio actual,
// o la carpeta de datos del usuario. db (opcional) fuerza la base. Sin RVD automático (eso es
// del servidor de verdad, no de cada cliente MCP) y con clave de la app efímera.
// Devuelve el servidor y un cierre que suelta la base.
func Arrancar(env, db string) (*Servidor, func(), error) {
	raiz, _, err := cliutil.ResolverRaiz(env)
	if err != nil {
		return nil, nil, err
	}
	cfg, err := cliutil.ConfigDeRaiz(raiz)
	if err != nil {
		return nil, nil, err
	}
	if db != "" {
		cfg.DatabasePath = db
	}
	if cfg.AppShellKey == "" {
		b := make([]byte, 32)
		_, _ = rand.Read(b)
		cfg.AppShellKey = "mcp-" + hex.EncodeToString(b) // efímera (≥ 24 caracteres, como exige el motor)
	}
	cfg.RVDSchedulerActivo = false
	s, err := servidor.Nuevo(cfg)
	if err != nil {
		return nil, nil, fmt.Errorf("no pude arrancar el motor: %w", err)
	}
	var cuenta int64 = 1
	if v := os.Getenv("MCP_CUENTA_ID"); v != "" {
		fmt.Sscan(v, &cuenta)
	}
	return Nuevo(s, cuenta, cfg.SIIAmbiente), s.Cerrar, nil
}
