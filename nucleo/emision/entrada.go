package emision

import (
	"encoding/json"
	"fmt"

	"dtechile/nucleo/firma"
	"dtechile/nucleo/xmlgen"
)

// entradaJSON es la forma del documento que aceptan nucleo-emitir y la app: la misma que
// DTEInput en Python (tipo_dte, folio, fecha_emision, emisor, receptor, items, referencias…).
type entradaJSON struct {
	TipoDTE      int    `json:"tipo_dte"`
	Folio        int    `json:"folio"`
	FechaEmision string `json:"fecha_emision"`
	Emisor       struct {
		Rut             string `json:"rut"`
		RazonSocial     string `json:"razon_social"`
		Giro            string `json:"giro"`
		CodigoActividad int    `json:"codigo_actividad"`
		Direccion       string `json:"direccion"`
		Comuna          string `json:"comuna"`
		Ciudad          string `json:"ciudad"`
		Telefono        string `json:"telefono"`
		Email           string `json:"email"`
	} `json:"emisor"`
	Receptor struct {
		Rut         string `json:"rut"`
		RazonSocial string `json:"razon_social"`
		Giro        string `json:"giro"`
		Direccion   string `json:"direccion"`
		Comuna      string `json:"comuna"`
		Ciudad      string `json:"ciudad"`
		Email       string `json:"email"`
	} `json:"receptor"`
	Items []struct {
		NumeroLinea    int      `json:"numero_linea"`
		Nombre         string   `json:"nombre"`
		Descripcion    string   `json:"descripcion"`
		Cantidad       *float64 `json:"cantidad"`
		UnidadMedida   string   `json:"unidad_medida"`
		PrecioUnitario float64  `json:"precio_unitario"`
		DescuentoPct   float64  `json:"descuento_pct"`
		DescuentoMonto float64  `json:"descuento_monto"`
		Exento         bool     `json:"exento"`
		CodigoProducto string   `json:"codigo_producto"`
	} `json:"items"`
	Referencias []struct {
		NumeroLinea int    `json:"numero_linea"`
		TipoDocRef  int    `json:"tipo_doc_ref"`
		FolioRef    int    `json:"folio_ref"`
		FechaDocRef string `json:"fecha_doc_ref"`
		CodigoRef   int    `json:"codigo_ref"`
		RazonRef    string `json:"razon_ref"`
	} `json:"referencias"`
	FormaPago         *int   `json:"forma_pago"`
	FechaVencimiento  string `json:"fecha_vencimiento"`
	IndicadorServicio int    `json:"indicador_servicio"`
	IndServicio       int    `json:"ind_servicio"`
}

// DocumentoDesdeJSON parsea y valida lo mínimo (tipo, fecha, emisor con RUT, al menos un ítem).
func DocumentoDesdeJSON(raw []byte) (xmlgen.Documento, error) {
	var e entradaJSON
	if err := json.Unmarshal(raw, &e); err != nil {
		return xmlgen.Documento{}, err
	}
	if e.TipoDTE == 0 || e.FechaEmision == "" || e.Emisor.Rut == "" || len(e.Items) == 0 {
		return xmlgen.Documento{}, fmt.Errorf("faltan tipo_dte, fecha_emision, emisor.rut o items")
	}
	doc := xmlgen.Documento{TipoDTE: e.TipoDTE, Folio: e.Folio, FechaEmision: e.FechaEmision, FormaPago: 1,
		FechaVencimiento: e.FechaVencimiento, IndicadorServicio: e.IndicadorServicio, IndServicioBoleta: e.IndServicio,
		Emisor: xmlgen.Emisor{Rut: e.Emisor.Rut, RazonSocial: e.Emisor.RazonSocial, Giro: e.Emisor.Giro,
			CodigoActividad: e.Emisor.CodigoActividad, Direccion: e.Emisor.Direccion, Comuna: e.Emisor.Comuna,
			Ciudad: e.Emisor.Ciudad, Telefono: e.Emisor.Telefono, Email: e.Emisor.Email},
		Receptor: xmlgen.Receptor{Rut: e.Receptor.Rut, RazonSocial: e.Receptor.RazonSocial, Giro: e.Receptor.Giro,
			Direccion: e.Receptor.Direccion, Comuna: e.Receptor.Comuna, Ciudad: e.Receptor.Ciudad, Email: e.Receptor.Email}}
	if e.FormaPago != nil {
		doc.FormaPago = *e.FormaPago
	}
	for i, it := range e.Items {
		c := 1.0
		if it.Cantidad != nil {
			c = *it.Cantidad
		}
		nl := it.NumeroLinea
		if nl == 0 {
			nl = i + 1
		}
		doc.Items = append(doc.Items, xmlgen.Item{NumeroLinea: nl, Nombre: it.Nombre, Descripcion: it.Descripcion,
			Cantidad: c, UnidadMedida: it.UnidadMedida, PrecioUnitario: it.PrecioUnitario, DescuentoPct: it.DescuentoPct,
			DescuentoMonto: it.DescuentoMonto, Exento: it.Exento, CodigoProducto: it.CodigoProducto})
	}
	for _, r := range e.Referencias {
		doc.Referencias = append(doc.Referencias, xmlgen.Referencia{NumeroLinea: r.NumeroLinea, TipoDocRef: r.TipoDocRef,
			FolioRef: r.FolioRef, FechaDocRef: r.FechaDocRef, CodigoRef: r.CodigoRef, RazonRef: r.RazonRef})
	}
	return doc, nil
}

// ContextoEmision es la respuesta de `GET /api/v1/keystore/negocios/{id}/contexto-emision`
// ya convertida: certificado cargado desde PEM, resolución y rutas.
type ContextoEmision struct {
	Rut              string
	Ambiente         string
	FechaResolucion  string
	NumeroResolucion int
	DatabasePath     string
	StoragePath      string
	Cert             *firma.Certificado
}

func ContextoDesdeJSON(raw []byte) (*ContextoEmision, error) {
	var c struct {
		Rut        string `json:"rut"`
		Ambiente   string `json:"ambiente"`
		Resolucion struct {
			Fecha  string `json:"fecha"`
			Numero int    `json:"numero"`
		} `json:"resolucion"`
		CertPEM      string `json:"cert_pem"`
		KeyPEM       string `json:"key_pem"`
		DatabasePath string `json:"database_path"`
		StoragePath  string `json:"storage_path"`
	}
	if err := json.Unmarshal(raw, &c); err != nil {
		return nil, err
	}
	cert, err := firma.CargarPEM([]byte(c.CertPEM), []byte(c.KeyPEM))
	if err != nil {
		return nil, err
	}
	if c.Resolucion.Fecha == "" || c.DatabasePath == "" || c.StoragePath == "" {
		return nil, fmt.Errorf("el contexto de emisión viene incompleto (resolución, base o storage)")
	}
	return &ContextoEmision{Rut: c.Rut, Ambiente: c.Ambiente, FechaResolucion: c.Resolucion.Fecha,
		NumeroResolucion: c.Resolucion.Numero, DatabasePath: c.DatabasePath, StoragePath: c.StoragePath, Cert: cert}, nil
}
