// nucleo-emitir: emite un documento con el núcleo en Go contra la base y el storage del
// motor (fase 2 del plan). Lee el documento en JSON por stdin y escribe el resultado en JSON.
//
//	nucleo-emitir --db dte_database.db --storage storage --cert firma.p12 --ambiente certificacion \
//	              --resolucion-fecha 2026-07-08 --resolucion-numero 0 < documento.json
//
// La clave del certificado va en NUCLEO_CERT_CLAVE (nunca como argumento: se vería en ps).
// RELOJ_FIJO fija la hora (solo pruebas). No genera PDF ni envía al SII.
// Los CAF que entrega el SII traen claves RSA de 512 bits; Go >= 1.24 las rechaza por defecto
// ("512-bit keys are insecure"). Se habilitan aquí porque firmar el TED con esa clave no es
// opcional: es el formato del SII. No afecta a la firma del DTE (certificado de 2048).
//
//go:debug rsa1024min=0
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"time"

	"dtechile/nucleo/almacen"
	"dtechile/nucleo/emision"
	"dtechile/nucleo/firma"
)

func main() {
	db := flag.String("db", "dte_database.db", "ruta de la base SQLite del motor")
	storage := flag.String("storage", "storage", "carpeta storage del motor")
	certPath := flag.String("cert", "", "certificado .p12/.pfx")
	ambiente := flag.String("ambiente", "certificacion", "certificacion | produccion | simulacion")
	fResol := flag.String("resolucion-fecha", "", "FchResol de la carátula (la del emisor y ambiente)")
	nResol := flag.Int("resolucion-numero", 0, "NroResol de la carátula")
	contextoPath := flag.String("contexto", "", "archivo JSON con la respuesta de /keystore/negocios/{id}/contexto-emision (el camino de la app; reemplaza a --cert/--db/--storage/--ambiente/--resolucion-*)")
	flag.Parse()
	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		fatal(err)
	}
	doc, err := emision.DocumentoDesdeJSON(raw)
	if err != nil {
		fatal(err)
	}
	var cert *firma.Certificado
	dbPath, storagePath, amb, fr, nr := *db, *storage, *ambiente, *fResol, *nResol
	if *contextoPath != "" {
		cj, err := os.ReadFile(*contextoPath)
		if err != nil {
			fatal(err)
		}
		ctx, err := emision.ContextoDesdeJSON(cj)
		if err != nil {
			fatal(err)
		}
		cert, dbPath, storagePath, amb, fr, nr = ctx.Cert, ctx.DatabasePath, ctx.StoragePath, ctx.Ambiente, ctx.FechaResolucion, ctx.NumeroResolucion
	} else {
		if *certPath == "" || *fResol == "" {
			fatal(fmt.Errorf("faltan --cert y/o --resolucion-fecha (o --contexto)"))
		}
		p12, err := os.ReadFile(*certPath)
		if err != nil {
			fatal(err)
		}
		if cert, err = firma.CargarP12(p12, os.Getenv("NUCLEO_CERT_CLAVE")); err != nil {
			fatal(err)
		}
	}
	alm, err := almacen.Abrir(dbPath)
	if err != nil {
		fatal(err)
	}
	defer alm.Cerrar()
	marca := os.Getenv("RELOJ_FIJO")
	if marca == "" {
		marca = time.Now().Format("2006-01-02T15:04:05")
	}
	res, err := emision.Emitir(emision.Contexto{Almacen: alm, Cert: cert, StorageBase: storagePath, Ambiente: amb,
		FechaResolucion: fr, NumeroResolucion: nr, Marca: marca}, doc)
	if err != nil {
		fatal(err)
	}
	out, _ := json.Marshal(res)
	fmt.Println(string(out))
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "nucleo-emitir:", err)
	os.Exit(1)
}
