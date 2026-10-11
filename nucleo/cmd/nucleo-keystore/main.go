// nucleo-keystore: certificados del SII por cuenta en el almacén cifrado (keystore_cli.py)
// y diagnóstico de un .p12 (diagnostico_cert.py).
//
//	nucleo-keystore add  firma.pfx --cuenta 1 --nombre rep-legal      (clave: NUCLEO_CLAVE_CERTIFICADO o prompt oculto)
//	nucleo-keystore list --cuenta 1
//	nucleo-keystore test 3 --cuenta 1          (carga el certificado y muestra RUT y vencimiento)
//	nucleo-keystore portal 3 --cuenta 1 [--rut 77777777-7]   (autentica en el SII; situación de folios)
//	nucleo-keystore remove 3 --cuenta 1
//	nucleo-keystore info --p12 firma.pfx       (subject, RUT, issuer, vigencia; sin tocar la base)
//
// Base y .env: --env (default .env) y --db. La clave NUNCA va por flag.
//
//go:debug rsa1024min=0
package main

import (
	"flag"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"

	"golang.org/x/term"

	"dtechile/nucleo/firma"
	"dtechile/nucleo/portal"
	"dtechile/nucleo/servidor"
)

func main() {
	if len(os.Args) < 2 {
		fatal(fmt.Errorf("uso: nucleo-keystore add|list|test|portal|remove|info …"))
	}
	cmd := os.Args[1]
	args := os.Args[2:]
	var posicional string
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		posicional, args = args[0], args[1:]
	}
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	cuenta := fs.Int64("cuenta", 1, "cuenta dueña")
	nombre := fs.String("nombre", "", "nombre del certificado")
	alias := fs.String("alias", "", "alias")
	rut := fs.String("rut", "", "RUT de empresa (portal: situación de folios)")
	p12Path := fs.String("p12", "", ".p12/.pfx (info)")
	env := fs.String("env", ".env", "archivo .env del motor")
	db := fs.String("db", "", "SQLite (si no, DATABASE_URL del .env)")
	_ = fs.Parse(args)

	if cmd == "info" {
		ruta := *p12Path
		if ruta == "" {
			ruta = posicional
		}
		if ruta == "" {
			ruta = envO("DTE_CERT_PATH", "firma.pfx")
		}
		b, err := os.ReadFile(ruta)
		if err != nil {
			fatal(err)
		}
		cert, err := firma.CargarP12(b, claveCert())
		if err != nil {
			fatal(err)
		}
		rutC, _ := cert.RutEmisor()
		fmt.Println("=== Subject ===\n" + cert.Cert.Subject.String())
		fmt.Println("\n=== RUT extraído ===\n" + rutC)
		fmt.Println("\n=== Issuer ===\n" + cert.Cert.Issuer.String())
		fmt.Printf("\n=== Vigencia ===\n%s → %s\n", cert.Cert.NotBefore.Format("2006-01-02"), cert.Cert.NotAfter.Format("2006-01-02"))
		return
	}
	cfg, err := servidor.CargarConfig(*env)
	if err != nil {
		fatal(err)
	}
	if *db != "" {
		cfg.DatabasePath = *db
	}
	cfg.RVDSchedulerActivo = false
	s, err := servidor.Nuevo(cfg)
	if err != nil {
		fatal(err)
	}
	defer s.Cerrar()
	switch cmd {
	case "add":
		if posicional == "" {
			fatal(fmt.Errorf("falta la ruta del .p12"))
		}
		b, err := os.ReadFile(posicional)
		if err != nil {
			fatal(err)
		}
		info, err := s.GuardarCertificado(*cuenta, b, claveCert(), *nombre, *alias)
		if err != nil {
			fatal(fmt.Errorf("no se pudo guardar: %w", err))
		}
		fmt.Printf("✓ Certificado guardado (id=%d): RUT %s · vence %.10s\n", info.ID, info.Rut, info.Vencimiento)
	case "list":
		certs, err := s.ListarCertificados(*cuenta)
		if err != nil {
			fatal(err)
		}
		if len(certs) == 0 {
			fmt.Printf("(cuenta %d sin certificados)\n", *cuenta)
			return
		}
		fmt.Printf("Certificados de la cuenta %d:\n", *cuenta)
		for _, c := range certs {
			fmt.Printf("  [%d] RUT %-12s %-20s vence %.10s\n", c.ID, c.Rut, c.Nombre, c.Vencimiento)
		}
	case "test", "portal", "remove":
		id, err := strconv.ParseInt(posicional, 10, 64)
		if err != nil {
			fatal(fmt.Errorf("falta el id del certificado"))
		}
		switch cmd {
		case "test":
			cert, err := s.CertificadoDelKeystore(id, *cuenta)
			if err != nil {
				fatal(err)
			}
			r, _ := cert.RutEmisor()
			fmt.Printf("✓ Certificado %d cargado en memoria: RUT %s\n  vence: %s\n", id, r, cert.Cert.NotAfter.Format("2006-01-02 15:04:05"))
		case "portal":
			certPEM, keyPEM, err := s.PEMDelKeystore(id, *cuenta)
			if err != nil {
				fatal(err)
			}
			p, err := portal.Nuevo(certPEM, keyPEM, portal.BaseCertificacion)
			if err != nil {
				fatal(err)
			}
			if _, err := p.Autenticar(""); err != nil {
				fatal(err)
			}
			fmt.Printf("✓ Autenticado en el SII (sesión RUT %s)\n", p.RutSesion)
			if *rut != "" {
				sit, err := p.SituacionFolios(*rut, []int{33, 34, 52, 56, 61})
				if err != nil {
					fatal(err)
				}
				fmt.Printf("  Situación de timbraje de %s:\n", *rut)
				for _, t := range []int{33, 34, 52, 56, 61} {
					est := "ok"
					if sit[t].Bloqueado {
						est = "BLOQUEADO"
					}
					fmt.Printf("    T%d: %s\n", t, est)
				}
			}
		case "remove":
			ok, err := s.EliminarCertificado(*cuenta, id)
			if err != nil {
				fatal(err)
			}
			if ok {
				fmt.Println("✓ Eliminado")
			} else {
				fmt.Println("✗ No encontrado")
			}
		}
	default:
		fatal(fmt.Errorf("subcomando desconocido: %s", cmd))
	}
}

// claveCert: NUCLEO_CLAVE_CERTIFICADO, el Llavero (DTE_KEYCHAIN_SERVICE) o prompt oculto.
func claveCert() string {
	if v := os.Getenv("NUCLEO_CLAVE_CERTIFICADO"); v != "" {
		return v
	}
	if out, err := exec.Command("security", "find-generic-password", "-s", envO("DTE_KEYCHAIN_SERVICE", "dte-cert-firma"), "-w").Output(); err == nil && strings.TrimSpace(string(out)) != "" {
		return strings.TrimSpace(string(out))
	}
	fmt.Fprint(os.Stderr, "Clave del certificado (.p12): ")
	b, err := term.ReadPassword(int(syscall.Stdin))
	fmt.Fprintln(os.Stderr)
	if err != nil {
		fatal(err)
	}
	return string(b)
}

func envO(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}
