package servidor

// Fernet (cryptography.fernet) compatible con Python: token = base64url( 0x80 | timestamp 8B BE |
// IV 16B | AES-128-CBC/PKCS7 | HMAC-SHA256 32B ). La clave son 32 bytes en base64url: los
// primeros 16 firman, los últimos 16 cifran. Los blobs que Python cifró en `certificados` y
// `claves_sii` se descifran aquí tal cual, y lo que Go cifra lo lee Python.
//
// Clave maestra: DTE_MASTER_KEY; si no está, Python deriva una de sha256(JWT_SECRET_KEY) y aquí
// se hace lo mismo (core/keystore.py::_fernet).

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"errors"
	"time"
)

type fernet struct{ firma, cifra []byte }

func nuevoFernet(claveB64 string, jwtSecret string) (*fernet, error) {
	var raw []byte
	var err error
	if claveB64 != "" {
		raw, err = base64.URLEncoding.DecodeString(claveB64)
		if err != nil {
			raw, err = base64.RawURLEncoding.DecodeString(claveB64)
		}
		if err != nil {
			return nil, errors.New("DTE_MASTER_KEY no es base64url")
		}
	} else {
		h := sha256.Sum256([]byte(jwtSecret))
		raw = h[:]
	}
	if len(raw) != 32 {
		return nil, errors.New("la clave Fernet debe tener 32 bytes")
	}
	return &fernet{firma: raw[:16], cifra: raw[16:]}, nil
}

func (f *fernet) Cifrar(texto []byte) ([]byte, error) {
	iv := make([]byte, 16)
	if _, err := rand.Read(iv); err != nil {
		return nil, err
	}
	bloque, err := aes.NewCipher(f.cifra)
	if err != nil {
		return nil, err
	}
	relleno := 16 - len(texto)%16
	plano := append(append([]byte{}, texto...), repetir(byte(relleno), relleno)...)
	cif := make([]byte, len(plano))
	cipher.NewCBCEncrypter(bloque, iv).CryptBlocks(cif, plano)
	tok := make([]byte, 0, 1+8+16+len(cif)+32)
	tok = append(tok, 0x80)
	tok = binary.BigEndian.AppendUint64(tok, uint64(time.Now().Unix()))
	tok = append(tok, iv...)
	tok = append(tok, cif...)
	mac := hmac.New(sha256.New, f.firma)
	mac.Write(tok)
	tok = append(tok, mac.Sum(nil)...)
	return []byte(base64.URLEncoding.EncodeToString(tok)), nil
}

func (f *fernet) Descifrar(token []byte) ([]byte, error) {
	raw, err := base64.URLEncoding.DecodeString(string(token))
	if err != nil {
		return nil, errors.New("token Fernet inválido")
	}
	if len(raw) < 1+8+16+32 || raw[0] != 0x80 || (len(raw)-57)%16 != 0 {
		return nil, errors.New("token Fernet inválido")
	}
	cuerpo, firma := raw[:len(raw)-32], raw[len(raw)-32:]
	mac := hmac.New(sha256.New, f.firma)
	mac.Write(cuerpo)
	if !hmac.Equal(firma, mac.Sum(nil)) {
		return nil, errors.New("token Fernet inválido (firma)")
	}
	iv, cif := raw[9:25], raw[25:len(raw)-32]
	bloque, err := aes.NewCipher(f.cifra)
	if err != nil {
		return nil, err
	}
	plano := make([]byte, len(cif))
	cipher.NewCBCDecrypter(bloque, iv).CryptBlocks(plano, cif)
	if len(plano) == 0 {
		return nil, errors.New("token Fernet inválido (vacío)")
	}
	relleno := int(plano[len(plano)-1])
	if relleno < 1 || relleno > 16 || relleno > len(plano) {
		return nil, errors.New("token Fernet inválido (relleno)")
	}
	for _, b := range plano[len(plano)-relleno:] {
		if int(b) != relleno {
			return nil, errors.New("token Fernet inválido (relleno)")
		}
	}
	return plano[:len(plano)-relleno], nil
}

func repetir(b byte, n int) []byte {
	out := make([]byte, n)
	for i := range out {
		out[i] = b
	}
	return out
}
