package servidor

// El mundo de práctica (EMPRESA DEMO SPA), réplica de core/simulacion.py: emisor ficticio
// (RUT 77.777.777-7, ley L14), CAF de mentira por tipo (clave RSA real para el timbre, firma
// del SII placeholder), certificado demo (el fijo del corpus dorado si existe; si no, uno
// autofirmado en memoria con el RUT en el SAN), resolución fija. Nada sale del computador.

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/asn1"
	"encoding/base64"
	"encoding/pem"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"time"

	"dtechile/nucleo/firma"
)

const (
	rutDemo            = "77777777-7"
	rutPersonaDemo     = "12345678-5"
	rutClienteDemo     = "76111111-6"
	rutConsumidorFinal = "66666666-6"
	ambienteDemo       = "simulacion"
	estadoDemo         = "simulado"
	foliosPorTipo      = 100
)

var tiposDemo = []int{33, 34, 39, 41, 56, 61}

// emisorDemo es EMISOR_DEMO.model_dump() (todos los campos, también los por defecto).
var emisorDemo = map[string]any{
	"rut": rutDemo, "razon_social": "EMPRESA DEMO SPA", "giro": "Cafetería", "codigo_actividad": 561000,
	"direccion": "Calle Ficticia 123", "comuna": "Santiago", "ciudad": "Santiago", "telefono": nil,
	"email": "hola@empresademo.cl", "es_receptor_boleta": true,
}

var clienteDemo = map[string]any{"rut": rutClienteDemo, "razon_social": "CLIENTE DEMO SPA", "giro": "Oficina",
	"direccion": "Avenida Imaginaria 456", "comuna": "Providencia", "ciudad": "Santiago"}

// cafFicticio es _caf_ficticio: XML de CAF con clave RSA 1024 real y FRMA de mentira.
func cafFicticio(tipo, desde, hasta int) (string, error) {
	key, err := rsa.GenerateKey(rand.Reader, 1024)
	if err != nil {
		return "", err
	}
	pemKey := string(pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)}))
	m := base64.StdEncoding.EncodeToString(key.N.Bytes())
	e := base64.StdEncoding.EncodeToString(big.NewInt(int64(key.E)).Bytes())
	return fmt.Sprintf(`<?xml version="1.0" encoding="ISO-8859-1"?>
<AUTORIZACION>
  <CAF version="1.0">
    <DA>
      <RE>%s</RE>
      <RS>%s</RS>
      <TD>%d</TD>
      <RNG><D>%d</D><H>%d</H></RNG>
      <FA>%s</FA>
      <RSAPK><M>%s</M><E>%s</E></RSAPK>
      <IDK>100</IDK>
    </DA>
    <FRMA algoritmo="SHA1withRSA">U0lNVUxBQ0lPTi1OTy1FUy1VTkEtRklSTUEtREVMLVNJSQ==</FRMA>
  </CAF>
  <RSASK>
%s  </RSASK>
</AUTORIZACION>
`, rutDemo, emisorDemo["razon_social"], tipo, desde, hasta, hoyISO(), m, e, pemKey), nil
}

// certificadoDemo es certificado_demo(): el fijo del corpus dorado (clave "demo") si está;
// si no, uno autofirmado de "Ana" con el RUT en el otherName chileno del SAN, en memoria.
func (s *Servidor) certificadoDemo() (*firma.Certificado, error) {
	if s.certDemo != nil {
		return s.certDemo, nil
	}
	for _, ruta := range []string{"tests/dorado/fixtures/cert_demo.p12", filepath.Join(filepath.Dir(s.cfg.DatabasePath), "tests", "dorado", "fixtures", "cert_demo.p12")} {
		if b, err := os.ReadFile(ruta); err == nil {
			if c, err := firma.CargarP12(b, "demo"); err == nil {
				s.certDemo = c
				return c, nil
			}
		}
	}
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		return nil, err
	}
	// SAN = SEQUENCE { otherName [0] { OID 1.3.6.1.4.1.8321.1, [0] EXPLICIT IA5String(rut) } }
	rutIA5, _ := asn1.Marshal(asn1.RawValue{Tag: asn1.TagIA5String, Bytes: []byte(rutPersonaDemo)})
	oid, _ := asn1.Marshal(asn1.ObjectIdentifier{1, 3, 6, 1, 4, 1, 8321, 1})
	valor, _ := asn1.Marshal(asn1.RawValue{Class: asn1.ClassContextSpecific, Tag: 0, IsCompound: true, Bytes: rutIA5})
	otro, _ := asn1.Marshal(asn1.RawValue{Class: asn1.ClassContextSpecific, Tag: 0, IsCompound: true, Bytes: append(oid, valor...)})
	san, _ := asn1.Marshal(asn1.RawValue{Tag: asn1.TagSequence, IsCompound: true, Bytes: otro})
	serial, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 120))
	ahora := time.Now().UTC()
	tpl := &x509.Certificate{
		SerialNumber: serial,
		Subject:      pkix.Name{Country: []string{"CL"}, Organization: []string{"SIMULACION DTE CHILE"}, CommonName: "ANA DEMO " + rutPersonaDemo},
		NotBefore:    ahora.Add(-24 * time.Hour), NotAfter: ahora.Add(3650 * 24 * time.Hour),
		ExtraExtensions: []pkix.Extension{{Id: asn1.ObjectIdentifier{2, 5, 29, 17}, Value: san}},
		KeyUsage:        x509.KeyUsageDigitalSignature,
	}
	der, err := x509.CreateCertificate(rand.Reader, tpl, tpl, &key.PublicKey, key)
	if err != nil {
		return nil, err
	}
	cert, err := x509.ParseCertificate(der)
	if err != nil {
		return nil, err
	}
	s.certDemo = &firma.Certificado{Clave: key, Cert: cert}
	return s.certDemo, nil
}
