// Package cliutil: lo que comparten los binarios del operador: cargar el certificado desde un
// .p12 (clave por entorno, Llavero o prompt oculto) o desde el keystore cifrado del motor
// (--cert-id), sin que la clave pase nunca por un flag.
package cliutil

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
	"syscall"

	"golang.org/x/term"

	"dtechile/nucleo/firma"
	"dtechile/nucleo/servidor"
)

// ClaveCertificado: NUCLEO_CLAVE_CERTIFICADO, el Llavero de macOS (DTE_KEYCHAIN_SERVICE,
// default dte-cert-firma) o, si hay terminal, un prompt oculto.
func ClaveCertificado() string {
	if v := os.Getenv("NUCLEO_CLAVE_CERTIFICADO"); v != "" {
		return v
	}
	if v := os.Getenv("NUCLEO_CERT_CLAVE"); v != "" { // nombre antiguo de nucleo-sii
		return v
	}
	servicio := os.Getenv("DTE_KEYCHAIN_SERVICE")
	if servicio == "" {
		servicio = "dte-cert-firma"
	}
	if out, err := exec.Command("security", "find-generic-password", "-s", servicio, "-w").Output(); err == nil && strings.TrimSpace(string(out)) != "" {
		return strings.TrimSpace(string(out))
	}
	if term.IsTerminal(int(syscall.Stdin)) {
		fmt.Fprint(os.Stderr, "Clave del certificado (.p12): ")
		b, err := term.ReadPassword(int(syscall.Stdin))
		fmt.Fprintln(os.Stderr)
		if err == nil {
			return string(b)
		}
	}
	return ""
}

// CargarCertificado: con certID > 0 lo saca del keystore del motor (env/db); si no, del .p12.
func CargarCertificado(certPath string, certID, cuenta int64, env, db string) (*firma.Certificado, error) {
	if certID > 0 {
		cfg, err := servidor.CargarConfig(env)
		if err != nil {
			return nil, err
		}
		if db != "" {
			cfg.DatabasePath = db
		}
		cfg.RVDSchedulerActivo = false
		s, err := servidor.Nuevo(cfg)
		if err != nil {
			return nil, err
		}
		defer s.Cerrar()
		return s.CertificadoDelKeystore(certID, cuenta)
	}
	if certPath == "" {
		certPath = os.Getenv("DTE_CERT_PATH")
	}
	if certPath == "" {
		return nil, fmt.Errorf("falta --cert (ruta del .p12) o --cert-id (keystore)")
	}
	p12, err := os.ReadFile(certPath)
	if err != nil {
		return nil, err
	}
	clave := ClaveCertificado()
	if clave == "" {
		return nil, fmt.Errorf("falta la clave del certificado: NUCLEO_CLAVE_CERTIFICADO o el Llavero")
	}
	return firma.CargarP12(p12, clave)
}
