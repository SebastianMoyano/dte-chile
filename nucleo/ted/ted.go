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
	"time"
)

// CAF es lo mínimo que el TED necesita del archivo de autorización de folios.
type CAF struct {
	// Elemento <CAF …>…</CAF> tal cual aparece en el archivo, MÁS el texto que lo sigue
	// hasta el siguiente '<' (lxml serializa el elemento con su "tail").
	Serializado       string
	FolioDesde        int
	FolioHasta        int
	Clave             *rsa.PrivateKey
	TipoDTE           int    // <DA><TD>
	RutEmisor         string // <DA><RE>
	FechaAutorizacion string // <DA><FA> (YYYY-MM-DD)
}

var (
	reDA     = regexp.MustCompile(`(?s)<DA>(.*?)</DA>`)
	reRE     = regexp.MustCompile(`<RE>([^<]*)</RE>`)
	reTD     = regexp.MustCompile(`<TD>([^<]*)</TD>`)
	reFA     = regexp.MustCompile(`<FA>([^<]*)</FA>`)
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
	da := reDA.FindStringSubmatch(contenido)
	if da == nil {
		return nil, errors.New("El XML no parece ser un CAF válido: falta el elemento <DA>")
	}
	m := reRNG.FindStringSubmatch(da[1])
	re_, td, fa := reRE.FindStringSubmatch(da[1]), reTD.FindStringSubmatch(da[1]), reFA.FindStringSubmatch(da[1])
	if m == nil || re_ == nil || td == nil || fa == nil {
		return nil, errors.New("El CAF está incompleto o tiene una estructura incorrecta.")
	}
	fmt.Sscan(m[1], &c.FolioDesde)
	fmt.Sscan(m[2], &c.FolioHasta)
	fmt.Sscan(strings.TrimSpace(td[1]), &c.TipoDTE)
	c.RutEmisor = strings.TrimSpace(re_[1])
	c.FechaAutorizacion = strings.TrimSpace(fa[1])
	if _, err := time.Parse("2006-01-02", c.FechaAutorizacion); err != nil {
		return nil, fmt.Errorf("Invalid isoformat string: '%s'", c.FechaAutorizacion)
	}
	k := reRSASK.FindStringSubmatch(contenido)
	if k == nil || strings.TrimSpace(k[1]) == "" {
		return nil, errors.New("El CAF no contiene la clave privada RSASK.")
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
	// PrimerItemLiteral: PrimerItem ya viene escapado (como lo manda certificacion_sii.py,
	// que escapa ANTES de recortar a 40): se recorta y no se vuelve a escapar.
	PrimerItemLiteral bool
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
		"<IT1>" + it1(d) + "</IT1>\n" +
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

// it1 es el texto del IT1. En modo literal viene pre-escapado por el script (& < > " ') y
// recortado DESPUÉS de escapar; Python luego parsea el DD y firma su C14N, que escribe las
// comillas sin escapar (&apos; → ', &quot; → "), así que eso es lo que se firma y lo que sale.
func it1(d Datos) string {
	if d.PrimerItemLiteral {
		return strings.NewReplacer("&apos;", "'", "&quot;", `"`).Replace(recortar(d.PrimerItem, 40))
	}
	return EscaparTexto(recortar(d.PrimerItem, 40))
}
