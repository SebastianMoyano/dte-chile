// nucleo-sii: el cliente SII del núcleo, para probarlo contra Maullín/Palena.
//
//	nucleo-sii token   --ambiente certificacion --cert firma.pfx            (NUCLEO_CERT_CLAVE)
//	nucleo-sii estado  --track 261542052 --rut 77777777-7 --ambiente certificacion --cert …
//	nucleo-sii enviar  --archivo storage/dtes/EnvioDTE_34_112.xml --rut 77777777-7 --ambiente … --cert …
//
// token y estado no gastan nada; enviar sube un sobre real (en certificación, sin efecto
// tributario, pero el folio ya está gastado al emitir).
//
//go:debug rsa1024min=0
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"

	"dtechile/nucleo/firma"
	"dtechile/nucleo/sii"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "uso: nucleo-sii token|estado|enviar [opciones]")
		os.Exit(2)
	}
	fs := flag.NewFlagSet(os.Args[1], flag.ExitOnError)
	amb := fs.String("ambiente", sii.Certificacion, "certificacion | produccion")
	certPath := fs.String("cert", "", "certificado .p12/.pfx (clave en NUCLEO_CERT_CLAVE)")
	rut := fs.String("rut", "", "RUT de la empresa con DV (estado, enviar)")
	track := fs.Int64("track", 0, "TrackID (estado)")
	archivo := fs.String("archivo", "", "sobre EnvioDTE a subir (enviar)")
	_ = fs.Parse(os.Args[2:])
	if *certPath == "" {
		fatal(fmt.Errorf("falta --cert"))
	}
	p12, err := os.ReadFile(*certPath)
	if err != nil {
		fatal(err)
	}
	cert, err := firma.CargarP12(p12, os.Getenv("NUCLEO_CERT_CLAVE"))
	if err != nil {
		fatal(err)
	}
	cli, err := sii.Nuevo(*amb, cert)
	if err != nil {
		fatal(err)
	}
	rutN, dv := "", ""
	if *rut != "" {
		p := strings.SplitN(*rut, "-", 2)
		if len(p) != 2 {
			fatal(fmt.Errorf("--rut con DV: 77777777-7"))
		}
		rutN, dv = p[0], p[1]
	}
	switch os.Args[1] {
	case "token":
		t, err := cli.Token()
		if err != nil {
			fatal(err)
		}
		fmt.Printf(`{"token_obtenido": true, "largo": %d, "ambiente": %q}`+"\n", len(t), *amb)
	case "estado":
		if *track == 0 || rutN == "" {
			fatal(fmt.Errorf("faltan --track y --rut"))
		}
		e, err := cli.EstadoTrack(*track, rutN, dv)
		if err != nil {
			fatal(err)
		}
		out, _ := json.Marshal(e)
		fmt.Println(string(out))
	case "enviar":
		if *archivo == "" || rutN == "" {
			fatal(fmt.Errorf("faltan --archivo y --rut"))
		}
		xml, err := os.ReadFile(*archivo)
		if err != nil {
			fatal(err)
		}
		tr, _, err := cli.EnviarDTE(xml, rutN, dv)
		if err != nil {
			fatal(err)
		}
		fmt.Printf(`{"track_id": %d, "mensaje": "Envío exitoso"}`+"\n", tr)
	default:
		fatal(fmt.Errorf("subcomando desconocido %q", os.Args[1]))
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "nucleo-sii:", err)
	os.Exit(1)
}
