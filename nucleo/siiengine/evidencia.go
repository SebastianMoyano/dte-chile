package siiengine

import (
	"fmt"
	"html"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// guardarEvidencia es _guardar_evidencia: deja en
// <RaizStorage>/mipyme_fallidos/<rut>/T<tipo>_F<folio>_<ts>/ lo necesario para diagnosticar
// un fallo DESPUÉS de gastar el folio: respuesta del portal, XML firmado (vale oro: es el
// documento con la firma del SII) y el body enviado, con las claves reemplazadas por *** (L6).
// Best-effort: nunca falla; devuelve la carpeta o "".
func (c *Cliente) guardarEvidencia(tipo, folio int, paso, respuesta, xmlFirmado string, pares []Par, extras map[string]string) string {
	secretos := []string{c.claveCert, c.claveTrib}
	limpiar := func(t string) string {
		for _, sec := range secretos {
			if len(sec) < 4 {
				continue
			}
			for _, v := range variantesSecreto(sec) {
				t = strings.ReplaceAll(t, v, "***")
			}
		}
		return t
	}
	rut := c.Empresa
	if rut == "" {
		rut = "sin_rut"
	}
	raiz := c.RaizStorage
	if raiz == "" {
		raiz = "storage"
	}
	carpeta := filepath.Join(raiz, "mipyme_fallidos", strings.ReplaceAll(rut, "-", ""),
		fmt.Sprintf("T%d_F%d_%s", tipo, folio, time.Now().Format("20060102T150405")))
	if err := os.MkdirAll(carpeta, 0o755); err != nil {
		return ""
	}
	escribir := func(nombre, contenido string) {
		os.WriteFile(filepath.Join(carpeta, nombre), aLatin1Reemplazo(contenido), 0o644)
	}
	escribir("respuesta_"+paso+".html", limpiar(respuesta))
	if xmlFirmado != "" {
		escribir("dte_firmado.xml", xmlFirmado)
	}
	// Una sola línea x-www-form-urlencoded (como viaja), parseable con parse_qsl.
	limpios := make([]Par, len(pares))
	for i, p := range pares {
		limpios[i] = Par{p.Nombre, limpiar(p.Valor)}
	}
	if b, err := CodificarLatin1(limpios); err == nil {
		os.WriteFile(filepath.Join(carpeta, "body_"+paso+".txt"), b, 0o644)
	}
	for nombre, contenido := range extras {
		escribir(nombre, limpiar(contenido))
	}
	return carpeta
}

// variantesSecreto: el secreto tal cual, url-encoded (quote y quote_plus, UTF-8 y latin-1) y
// html-escapado, como en Python.
func variantesSecreto(sec string) []string {
	out := []string{sec, quoteUTF8(sec), string(CodificarUTF8([]Par{{"", sec}})[1:]), escapeHTMLPython(sec)}
	if b, err := ABytesLatin1(sec); err == nil {
		out = append(out, quotePlus(b))
	}
	return out
}

// quoteUTF8 es urllib.parse.quote(s) (safe="/"): como quotePlus pero el espacio va %20 y '/'
// queda.
func quoteUTF8(s string) string {
	const hex = "0123456789ABCDEF"
	var sb strings.Builder
	for _, c := range []byte(s) {
		switch {
		case c >= 'a' && c <= 'z', c >= 'A' && c <= 'Z', c >= '0' && c <= '9', c == '_', c == '.', c == '-', c == '~', c == '/':
			sb.WriteByte(c)
		default:
			sb.WriteByte('%')
			sb.WriteByte(hex[c>>4])
			sb.WriteByte(hex[c&15])
		}
	}
	return sb.String()
}

// escapeHTMLPython es html.escape(s, quote=True): &, <, >, " y ' (este último como &#x27;).
func escapeHTMLPython(s string) string {
	r := strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", `"`, "&quot;", "'", "&#x27;")
	return r.Replace(s)
}

var _ = html.EscapeString // (Go escapa ' como &#39;; Python como &#x27;, por eso el replacer)

// aLatin1Reemplazo codifica ISO-8859-1 reemplazando lo que no cabe con '?' (errors="replace").
func aLatin1Reemplazo(s string) []byte {
	out := make([]byte, 0, len(s))
	for _, r := range s {
		if r > 0xFF {
			out = append(out, '?')
		} else {
			out = append(out, byte(r))
		}
	}
	return out
}
