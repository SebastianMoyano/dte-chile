// Package firma: certificado PKCS#12, firma XMLDSig enveloped (RSA-SHA1 + C14N 1.0) del
// DTE standalone y del sobre, como core/crypto.py::firmar_xml_sii y core/sobre.py.
package firma

import (
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha1"
	"crypto/x509"
	"encoding/asn1"
	"encoding/base64"
	"encoding/pem"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"

	pkcs12 "software.sslmate.com/src/go-pkcs12"

	"dtechile/nucleo/c14n"
)

const (
	NSDsig = "http://www.w3.org/2000/09/xmldsig#"
	NSXsi  = "http://www.w3.org/2001/XMLSchema-instance"
	NSSii  = "http://www.sii.cl/SiiDte"
	RutSII = "60803000-K"
)

type Certificado struct {
	Clave *rsa.PrivateKey
	Cert  *x509.Certificate
}

func CargarP12(datos []byte, clave string) (*Certificado, error) {
	k, c, err := pkcs12.Decode(datos, clave)
	if err != nil {
		return nil, fmt.Errorf("no se pudo cargar el certificado: %w", err)
	}
	rk, ok := k.(*rsa.PrivateKey)
	if !ok {
		return nil, errors.New("la clave del certificado no es RSA")
	}
	return &Certificado{Clave: rk, Cert: c}, nil
}

// CargarPEM arma el certificado desde el par cert/clave en PEM (lo que entrega el keystore
// del motor por `contexto-emision`). La clave puede venir PKCS#1 ("RSA PRIVATE KEY") o PKCS#8.
func CargarPEM(certPEM, keyPEM []byte) (*Certificado, error) {
	bc, _ := pem.Decode(certPEM)
	if bc == nil {
		return nil, errors.New("cert_pem no es PEM")
	}
	c, err := x509.ParseCertificate(bc.Bytes)
	if err != nil {
		return nil, fmt.Errorf("certificado: %w", err)
	}
	bk, _ := pem.Decode(keyPEM)
	if bk == nil {
		return nil, errors.New("key_pem no es PEM")
	}
	var rk *rsa.PrivateKey
	if k1, err := x509.ParsePKCS1PrivateKey(bk.Bytes); err == nil {
		rk = k1
	} else if k8, err2 := x509.ParsePKCS8PrivateKey(bk.Bytes); err2 == nil {
		var ok bool
		if rk, ok = k8.(*rsa.PrivateKey); !ok {
			return nil, errors.New("la clave no es RSA")
		}
	} else {
		return nil, fmt.Errorf("clave privada ilegible: %v / %v", err, err2)
	}
	return &Certificado{Clave: rk, Cert: c}, nil
}

var reRut = regexp.MustCompile(`(\d{7,8}-[\dkK])`)

// RutEmisor replica CertificadoDigital.rut_emisor: primero el CN, luego el SAN con el OID
// chileno 1.3.6.1.4.1.8321.1.
func (c *Certificado) RutEmisor() (string, error) {
	if m := reRut.FindString(c.Cert.Subject.CommonName); m != "" {
		return m, nil
	}
	for _, ext := range c.Cert.Extensions {
		if !ext.Id.Equal(asn1.ObjectIdentifier{2, 5, 29, 17}) {
			continue
		}
		var seq asn1.RawValue
		if _, err := asn1.Unmarshal(ext.Value, &seq); err != nil {
			continue
		}
		rest := seq.Bytes
		for len(rest) > 0 {
			var gn asn1.RawValue
			var err error
			rest, err = asn1.Unmarshal(rest, &gn)
			if err != nil {
				break
			}
			if gn.Tag != 0 || gn.Class != asn1.ClassContextSpecific {
				continue
			}
			var oid asn1.ObjectIdentifier
			after, err := asn1.Unmarshal(gn.Bytes, &oid)
			if err != nil || !oid.Equal(asn1.ObjectIdentifier{1, 3, 6, 1, 4, 1, 8321, 1}) {
				continue
			}
			if m := reRut.FindString(string(after)); m != "" {
				return m, nil
			}
		}
	}
	return "", errors.New("el certificado no trae el RUT ni en el CN ni en el SAN")
}

func envolver64(b64 string) string {
	if len(b64) <= 64 {
		return b64
	}
	var partes []string
	for i := 0; i < len(b64); i += 64 {
		j := i + 64
		if j > len(b64) {
			j = len(b64)
		}
		partes = append(partes, b64[i:j])
	}
	return "\n" + strings.Join(partes, "\n") + "\n"
}

func (c *Certificado) firmar(datos []byte) ([]byte, error) {
	h := sha1.Sum(datos)
	return rsa.SignPKCS1v15(rand.Reader, c.Clave, crypto.SHA1, h[:])
}

// Signature produce el elemento <Signature> para un nodo referenciado.
//
//   - referenciado: XML del elemento al que apunta la URI (serializado sin los xmlns
//     heredados; se le pasan en `nsRef`, como lxml los renderiza al serializar el subárbol).
//   - nsSignedInfo: namespaces heredados por el <SignedInfo> en su posición final (además
//     del default xmldsig#): en el DTE ninguno; en el sobre, xsi.
func (c *Certificado) Signature(uri, referenciado string, nsRef, nsSignedInfo map[string]string) (string, error) {
	can, err := c14n.Canonicalizar(referenciado, nsRef)
	if err != nil {
		return "", fmt.Errorf("C14N del elemento referenciado: %w", err)
	}
	dig := sha1.Sum(can)
	signedInfo := `<SignedInfo>` +
		`<CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>` +
		`<SignatureMethod Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1"/>` +
		`<Reference URI="` + uri + `">` +
		`<Transforms><Transform Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/></Transforms>` +
		`<DigestMethod Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"/>` +
		`<DigestValue>` + base64.StdEncoding.EncodeToString(dig[:]) + `</DigestValue>` +
		`</Reference></SignedInfo>`
	ns := map[string]string{"": NSDsig}
	for k, v := range nsSignedInfo {
		ns[k] = v
	}
	canSI, err := c14n.Canonicalizar(signedInfo, ns)
	if err != nil {
		return "", fmt.Errorf("C14N del SignedInfo: %w", err)
	}
	sig, err := c.firmar(canSI)
	if err != nil {
		return "", err
	}
	pub := c.Clave.PublicKey
	mod := base64.StdEncoding.EncodeToString(pub.N.Bytes())
	exp := base64.StdEncoding.EncodeToString(bigEndian(pub.E))
	cert := base64.StdEncoding.EncodeToString(c.Cert.Raw)
	return `<Signature xmlns="` + NSDsig + `">` + signedInfo +
		`<SignatureValue>` + base64.StdEncoding.EncodeToString(sig) + `</SignatureValue>` +
		`<KeyInfo><KeyValue><RSAKeyValue><Modulus>` + envolver64(mod) + `</Modulus>` +
		`<Exponent>` + envolver64(exp) + `</Exponent></RSAKeyValue></KeyValue>` +
		`<X509Data><X509Certificate>` + envolver64(cert) + `</X509Certificate></X509Data></KeyInfo>` +
		`</Signature>`, nil
}

func bigEndian(e int) []byte {
	var b []byte
	for e > 0 {
		b = append([]byte{byte(e & 0xff)}, b...)
		e >>= 8
	}
	return b
}

// FirmarDTE recibe el <DTE> sin firmar serializado (con su xmlns) y el XML del <Documento>
// (sin xmlns) y devuelve el DTE firmado como string (core/sobre.py::firmar_documento_standalone).
func (c *Certificado) FirmarDTE(dteSinFirma, documento string, tipo, folio int) (string, error) {
	sig, err := c.Signature(fmt.Sprintf("#T%dF%d", tipo, folio), documento, map[string]string{"": NSSii}, nil)
	if err != nil {
		return "", err
	}
	cierre := "</DTE>"
	if !strings.HasSuffix(dteSinFirma, cierre) {
		return "", errors.New("el DTE no termina en </DTE>")
	}
	return dteSinFirma[:len(dteSinFirma)-len(cierre)] + sig + cierre, nil
}

var raices = map[string]string{"EnvioDTE": "EnvioDTE_v10.xsd", "EnvioBOLETA": "EnvioBOLETA_v11.xsd"}

// Sobre arma y firma el EnvioDTE/EnvioBOLETA por concatenación (core/sobre.py::armar_sobre_firmado).
// Devuelve los bytes finales en ISO-8859-1.
func (c *Certificado) Sobre(docsFirmados []string, subtotales map[int]int, rutEmisor, rutEnvia,
	fechaResol string, nroResol int, raiz, marca string) ([]byte, error) {
	xsd, ok := raices[raiz]
	if !ok {
		return nil, fmt.Errorf("raíz desconocida %q", raiz)
	}
	var tipos []int
	for t := range subtotales {
		tipos = append(tipos, t)
	}
	sort.Ints(tipos)
	var sub strings.Builder
	for _, t := range tipos {
		fmt.Fprintf(&sub, "<SubTotDTE><TpoDTE>%d</TpoDTE><NroDTE>%d</NroDTE></SubTotDTE>", t, subtotales[t])
	}
	caratula := `<Caratula version="1.0"><RutEmisor>` + rutEmisor + `</RutEmisor>` +
		`<RutEnvia>` + rutEnvia + `</RutEnvia><RutReceptor>` + RutSII + `</RutReceptor>` +
		`<FchResol>` + fechaResol + `</FchResol><NroResol>` + fmt.Sprint(nroResol) + `</NroResol>` +
		`<TmstFirmaEnv>` + marca + `</TmstFirmaEnv>` + sub.String() + `</Caratula>`
	setDTE := `<SetDTE ID="SetDoc">` + caratula + strings.Join(docsFirmados, "") + `</SetDTE>`
	envio := `<` + raiz + ` xmlns="` + NSSii + `" xmlns:xsi="` + NSXsi + `" ` +
		`xsi:schemaLocation="` + NSSii + ` ` + xsd + `" version="1.0">` + setDTE + `</` + raiz + `>`
	sig, err := c.Signature("#SetDoc", setDTE, map[string]string{"": NSSii, "xsi": NSXsi},
		map[string]string{"xsi": NSXsi})
	if err != nil {
		return nil, err
	}
	// lxml serializa el subárbol <Signature> para insertarlo por string, y al hacerlo le
	// renderiza en el ápice el xmlns:xsi heredado del sobre (54 bytes que el corpus detectó).
	sig = strings.Replace(sig, `<Signature xmlns="`+NSDsig+`">`,
		`<Signature xmlns="`+NSDsig+`" xmlns:xsi="`+NSXsi+`">`, 1)
	cierre := "</" + raiz + ">"
	final := envio[:len(envio)-len(cierre)] + sig + cierre
	out := []byte("<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>\n")
	for _, r := range final {
		if r > 0xFF {
			return nil, fmt.Errorf("carácter %q no representable en ISO-8859-1", r)
		}
		out = append(out, byte(r))
	}
	return out, nil
}
