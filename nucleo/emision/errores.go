package emision

import "fmt"

// Error es un error de dominio con el mismo código y status que core/errors.py, para que el
// servidor responda idéntico a Python: sin_folios/folio/conflicto (409), caf/certificado/
// validacion (422).
type Error struct {
	Codigo  string
	Status  int
	Mensaje string
	Detalle map[string]any
}

func (e *Error) Error() string { return e.Mensaje }

func errSinFolios(rut string, tipo int) *Error {
	return &Error{Codigo: "sin_folios", Status: 409, Detalle: map[string]any{"rut_emisor": rut, "tipo_dte": tipo},
		Mensaje: fmt.Sprintf("No hay folios disponibles para el emisor %s y tipo DTE %d. Verifique que el CAF esté cargado y activo.", rut, tipo)}
}

func errFolio(msg string, detalle map[string]any) *Error {
	return &Error{Codigo: "folio", Status: 409, Mensaje: msg, Detalle: detalle}
}

func errConflicto(msg string, detalle map[string]any) *Error {
	return &Error{Codigo: "conflicto", Status: 409, Mensaje: msg, Detalle: detalle}
}

func errCAF(msg string) *Error { return &Error{Codigo: "caf", Status: 422, Mensaje: msg} }

// ErrValidacion es un 422 "validacion" (p. ej. el sobre no pasa el XSD).
func ErrValidacion(msg string) *Error { return &Error{Codigo: "validacion", Status: 422, Mensaje: msg} }

// ErrCertificado es un 422 "certificado".
func ErrCertificado(msg string) *Error {
	return &Error{Codigo: "certificado", Status: 422, Mensaje: msg}
}
