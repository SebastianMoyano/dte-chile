// Package ted construye y firma el Timbre Electrónico (TED) exactamente como
// core/caf.py::ManejadorCAF.generar_ted (docs/DORADO.md §2).
package ted

import (
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha1"
	"crypto/x509"
	"encoding/base64"
	"encoding/pem"
	"errors"
	"fmt"
	"regexp"
	"strings"
)

// CAF es lo mínimo que el TED necesita del archivo de autorización de folios.
type CAF struct {
	// Elemento <CAF …>…</CAF> tal cual aparece en el archivo, MÁS el texto que lo sigue
	// hasta el siguiente '<' (lxml serializa el elemento con su "tail").
	Serializado string
	FolioDesde  int
	FolioHasta  int
	Clave       *rsa.PrivateKey
}

var (
	reRNG    = regexp.MustCompile(`<RNG>\s*<D>(\d+)</D>\s*<H>(\d+)</H>\s*</RNG>`)
	reRSASK  = regexp.MustCompile(`(?s)<RSASK>(.*?)</RSASK>`)
	reBlanco = regexp.MustCompile(`>\s+<`)
)

// ParsearCAF recibe el archivo CAF decodificado a string (ISO-8859-1 → runas).
func ParsearCAF(contenido string) (*CAF, error) {
	ini := strings.Index(contenido, "<CAF")
	fin := strings.Index(contenido, "</CAF>")
	if ini < 0 || fin < 0 {
		return nil, errors.New("el archivo no tiene un elemento <CAF>")
	}
	fin += len("</CAF>")
	cola := contenido[fin:]
	if k := strings.Index(cola, "<"); k >= 0 {
		cola = cola[:k]
	}
	c := &CAF{Serializado: contenido[ini:fin] + cola}
	m := reRNG.FindStringSubmatch(contenido)
	if m == nil {
		return nil, errors.New("el CAF no tiene rango <RNG>")
	}
	fmt.Sscan(m[1], &c.FolioDesde)
	fmt.Sscan(m[2], &c.FolioHasta)
	k := reRSASK.FindStringSubmatch(contenido)
	if k == nil {
		return nil, errors.New("el CAF no contiene la clave privada RSASK")
	}
	bloque, _ := pem.Decode([]byte(strings.TrimSpace(k[1])))
	if bloque == nil {
		return nil, errors.New("RSASK no es PEM")
	}
	if key, err := x509.ParsePKCS1PrivateKey(bloque.Bytes); err == nil {
		c.Clave = key
	} else if k8, err2 := x509.ParsePKCS8PrivateKey(bloque.Bytes); err2 == nil {
		rk, ok := k8.(*rsa.PrivateKey)
		if !ok {
			return nil, errors.New("la clave del CAF no es RSA")
		}
		c.Clave = rk
	} else {
		return nil, fmt.Errorf("clave del CAF ilegible: %v / %v", err, err2)
	}
	return c, nil
}

// EscaparTexto es el escape de texto XML que aplican lxml y la C14N: & < >.
func EscaparTexto(s string) string {
	s = strings.ReplaceAll(s, "&", "&amp;")
	s = strings.ReplaceAll(s, "<", "&lt;")
	s = strings.ReplaceAll(s, ">", "&gt;")
	return s
}

// Latin1 codifica un string (runas) a bytes ISO-8859-1. Falla si hay una runa > 255.
func Latin1(s string) ([]byte, error) {
	out := make([]byte, 0, len(s))
	for _, r := range s {
		if r > 0xFF {
			return nil, fmt.Errorf("carácter %q no representable en ISO-8859-1", r)
		}
		out = append(out, byte(r))
	}
	return out, nil
}

func recortar(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		r = r[:n]
	}
	return string(r)
}

type Datos struct {
	Folio               int
	RutEmisor           string
	RutReceptor         string
	TipoDTE             int
	FechaEmision        string // YYYY-MM-DD
	MontoTotal          int64
	RazonSocialReceptor string
	PrimerItem          string
	Marca               string // hora del reloj, YYYY-MM-DDTHH:MM:SS
}

// Generar devuelve el TED como string (runas; el archivo se escribe en ISO-8859-1).
func Generar(c *CAF, d Datos) (string, error) {
	if d.Folio < c.FolioDesde || d.Folio > c.FolioHasta {
		return "", fmt.Errorf("el folio %d no está en el rango del CAF [%d-%d]", d.Folio, c.FolioDesde, c.FolioHasta)
	}
	dd := "<DD>\n" +
		"<RE>" + d.RutEmisor + "</RE>\n" +
		fmt.Sprintf("<TD>%d</TD>\n<F>%d</F>\n", d.TipoDTE, d.Folio) +
		"<FE>" + d.FechaEmision + "</FE>\n" +
		"<RR>" + d.RutReceptor + "</RR>\n" +
		"<RSR>" + EscaparTexto(recortar(d.RazonSocialReceptor, 40)) + "</RSR>\n" +
		fmt.Sprintf("<MNT>%d</MNT>\n", d.MontoTotal) +
		"<IT1>" + EscaparTexto(recortar(d.PrimerItem, 40)) + "</IT1>\n" +
		c.Serializado + "\n" +
		"<TSTED>" + d.Marca + "</TSTED>\n" +
		"</DD>"
	// Lo firmado: C14N del DD (para este DD sin namespaces equivale al propio string),
	// aplanado (>\s+< → ><) y en ISO-8859-1.
	plano, err := Latin1(reBlanco.ReplaceAllString(dd, "><"))
	if err != nil {
		return "", err
	}
	h := sha1.Sum(plano)
	firma, err := rsa.SignPKCS1v15(rand.Reader, c.Clave, crypto.SHA1, h[:])
	if err != nil {
		return "", err
	}
	return "<TED version=\"1.0\">\n" + dd + "\n<FRMT algoritmo=\"SHA1withRSA\">" +
		base64.StdEncoding.EncodeToString(firma) + "</FRMT>\n</TED>", nil
}
