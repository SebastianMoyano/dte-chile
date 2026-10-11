package rcv

import "database/sql"

// Agregación para el F29 (IVA mensual) sobre lo persistido en rcv_documentos.

// Resumen es ResumenF29.
type Resumen struct {
	RutEmpresa        string `json:"rut_empresa"`
	Periodo           string `json:"periodo"`
	VentasNetas       int64  `json:"ventas_netas"`
	VentasExentas     int64  `json:"ventas_exentas"`
	DebitoFiscal      int64  `json:"debito_fiscal"`
	NDocsVenta        int    `json:"n_docs_venta"`
	ComprasNetas      int64  `json:"compras_netas"`
	ComprasExentas    int64  `json:"compras_exentas"`
	CreditoFiscal     int64  `json:"credito_fiscal"`
	IVANoRecuperable  int64  `json:"iva_no_recuperable"`
	NDocsCompra       int    `json:"n_docs_compra"`
	PPM               int64  `json:"ppm"`
	RemanenteAnterior int64  `json:"remanente_anterior"`
}

func (r Resumen) IVADeterminado() int64 {
	return r.DebitoFiscal - r.CreditoFiscal - r.RemanenteAnterior
}
func (r Resumen) RemanenteSiguiente() int64 {
	if n := r.IVADeterminado(); n < 0 {
		return -n
	}
	return 0
}
func (r Resumen) TotalAPagar() int64 {
	b := r.IVADeterminado()
	if b < 0 {
		b = 0
	}
	return b + r.PPM
}

type filaRCV struct {
	op            string
	tipo          int
	neto, exento  int64
	iva, ivaNoRec int64
}

func filasPeriodo(db *sql.DB, rut, periodo string) ([]filaRCV, error) {
	rows, err := db.Query(`SELECT tipo_operacion, tipo_dte, COALESCE(monto_neto,0), COALESCE(monto_exento,0), COALESCE(monto_iva,0), COALESCE(monto_iva_no_rec,0)
		FROM rcv_documentos WHERE rut_empresa=? AND periodo=?`, rut, periodo)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []filaRCV
	for rows.Next() {
		var f filaRCV
		if err := rows.Scan(&f.op, &f.tipo, &f.neto, &f.exento, &f.iva, &f.ivaNoRec); err != nil {
			return nil, err
		}
		out = append(out, f)
	}
	return out, rows.Err()
}

// CalcularResumen es calcular_resumen_f29: las NC (61) restan; el crédito excluye el IVA no
// recuperable; PPM y remanente son insumos externos.
func CalcularResumen(db *sql.DB, rut, periodo string, ppm, remanente int64) (*Resumen, error) {
	r := &Resumen{RutEmpresa: NormalizarRut(rut), Periodo: NormalizarPeriodo(periodo), PPM: ppm, RemanenteAnterior: remanente}
	filas, err := filasPeriodo(db, r.RutEmpresa, r.Periodo)
	if err != nil {
		return nil, err
	}
	for _, f := range filas {
		s := int64(SignoDocumento(f.tipo))
		if f.op == Venta {
			r.VentasNetas += s * f.neto
			r.VentasExentas += s * f.exento
			r.DebitoFiscal += s * f.iva
			r.NDocsVenta++
		} else {
			r.ComprasNetas += s * f.neto
			r.ComprasExentas += s * f.exento
			r.CreditoFiscal += s * (f.iva - f.ivaNoRec)
			r.IVANoRecuperable += s * f.ivaNoRec
			r.NDocsCompra++
		}
	}
	return r, nil
}

// CodigosF29: códigos oficiales del F29 verificados contra el anverso del formulario.
var CodigosF29 = map[string][2]string{
	"503": {"Facturas emitidas — cantidad", "OK"}, "502": {"Facturas emitidas — débito", "OK"},
	"110": {"Boletas — cantidad", "OK"}, "111": {"Boletas — débito", "OK"},
	"512": {"Notas de débito emitidas — cantidad", "OK"}, "513": {"Notas de débito emitidas — débito", "OK"},
	"509": {"Notas de crédito emitidas por facturas — cantidad", "OK"}, "510": {"Notas de crédito emitidas por facturas — rebaja al débito", "OK"},
	"586": {"Ventas/servicios exentos o no gravados — cantidad", "OK"}, "142": {"Ventas/servicios exentos o no gravados — monto neto", "OK"},
	"538": {"TOTAL DÉBITOS", "OK"},
	"519": {"Facturas recibidas del giro — cantidad", "OK"}, "520": {"Facturas recibidas del giro — crédito recuperable", "OK"},
	"524": {"Facturas activo fijo — cantidad", "OK"}, "525": {"Facturas activo fijo — crédito", "OK"},
	"527": {"Notas de crédito recibidas — cantidad", "OK"}, "528": {"Notas de crédito recibidas — rebaja al crédito", "OK"},
	"504": {"Remanente crédito fiscal mes anterior", "OK"}, "537": {"TOTAL CRÉDITOS", "OK"},
	"89": {"IVA determinado (a pagar)", "OK"}, "77": {"Remanente crédito fiscal para el período siguiente", "OK"},
	"563": {"Base imponible PPM (ingresos brutos del giro)", "OK"}, "62": {"PPM neto determinado", "OK"},
	"595": {"Subtotal impuesto determinado anverso", "OK"}, "91": {"TOTAL A PAGAR dentro del plazo legal", "OK"},
}

var boletas, notaDebito = map[int]bool{39: true, 41: true}, map[int]bool{56: true}

// Linea es LineaF29: un casillero.
type Linea struct {
	Codigo    string `json:"codigo"`
	Glosa     string `json:"glosa"`
	Valor     int64  `json:"valor"`
	Confianza string `json:"confianza"`
}

// Desglose es DesgloseF29 (separa facturas, boletas y notas; pesos).
type Desglose struct {
	RutEmpresa           string `json:"rut_empresa"`
	Periodo              string `json:"periodo"`
	FactEmitidasCant     int    `json:"fact_emitidas_cant"`
	FactEmitidasDebito   int64  `json:"fact_emitidas_debito"`
	BoletasCant          int    `json:"boletas_cant"`
	BoletasDebito        int64  `json:"boletas_debito"`
	NCEmitidasCant       int    `json:"nc_emitidas_cant"`
	NCEmitidasDebito     int64  `json:"nc_emitidas_debito"`
	NDEmitidasCant       int    `json:"nd_emitidas_cant"`
	NDEmitidasDebito     int64  `json:"nd_emitidas_debito"`
	VentasExentas        int64  `json:"ventas_exentas"`
	ExentasCant          int    `json:"exentas_cant"`
	TotalDebitos         int64  `json:"total_debitos"`
	FactRecibidasCant    int    `json:"fact_recibidas_cant"`
	FactRecibidasCredito int64  `json:"fact_recibidas_credito"`
	NCRecibidasCant      int    `json:"nc_recibidas_cant"`
	NCRecibidasCredito   int64  `json:"nc_recibidas_credito"`
	IVANoRecuperable     int64  `json:"iva_no_recuperable"`
	TotalCreditos        int64  `json:"total_creditos"`
	RemanenteAnterior    int64  `json:"remanente_anterior"`
	PPM                  int64  `json:"ppm"`
	BasePPM              int64  `json:"-"`
}

func (d Desglose) IVADeterminado() int64 {
	return d.TotalDebitos - d.TotalCreditos - d.RemanenteAnterior
}
func (d Desglose) RemanenteSiguiente() int64 {
	if n := d.IVADeterminado(); n < 0 {
		return -n
	}
	return 0
}
func (d Desglose) TotalAPagar() int64 {
	b := d.IVADeterminado()
	if b < 0 {
		b = 0
	}
	return b + d.PPM
}

// CalcularDesglose es calcular_desglose_f29.
func CalcularDesglose(db *sql.DB, rut, periodo string, ppm, remanente int64) (*Desglose, error) {
	d := &Desglose{RutEmpresa: NormalizarRut(rut), Periodo: NormalizarPeriodo(periodo), RemanenteAnterior: remanente, PPM: ppm}
	filas, err := filasPeriodo(db, d.RutEmpresa, d.Periodo)
	if err != nil {
		return nil, err
	}
	for _, f := range filas {
		if f.op == Venta {
			d.BasePPM += f.neto + f.exento
			switch {
			case TiposNotaCredito[f.tipo]:
				d.NCEmitidasCant++
				d.NCEmitidasDebito += f.iva
			case boletas[f.tipo]:
				d.BoletasCant++
				d.BoletasDebito += f.iva
			case notaDebito[f.tipo]:
				d.NDEmitidasCant++
				d.NDEmitidasDebito += f.iva
			default:
				d.FactEmitidasCant++
				d.FactEmitidasDebito += f.iva
			}
			if f.exento != 0 {
				d.VentasExentas += f.exento
				d.ExentasCant++
			}
		} else {
			ivaRec := f.iva - f.ivaNoRec
			d.IVANoRecuperable += f.ivaNoRec
			if TiposNotaCredito[f.tipo] {
				d.NCRecibidasCant++
				d.NCRecibidasCredito += ivaRec
			} else {
				d.FactRecibidasCant++
				d.FactRecibidasCredito += ivaRec
			}
		}
	}
	d.TotalDebitos = d.FactEmitidasDebito + d.BoletasDebito + d.NDEmitidasDebito - d.NCEmitidasDebito
	d.TotalCreditos = d.FactRecibidasCredito - d.NCRecibidasCredito
	return d, nil
}

// MapearAF29 es mapear_a_f29: casilleros en el orden del formulario, omitiendo los en cero.
func MapearAF29(d *Desglose) []Linea {
	iva := d.IVADeterminado()
	if iva < 0 {
		iva = 0
	}
	cand := []struct {
		codigo string
		valor  int64
	}{
		{"503", int64(d.FactEmitidasCant)}, {"502", d.FactEmitidasDebito}, {"110", int64(d.BoletasCant)}, {"111", d.BoletasDebito},
		{"512", int64(d.NDEmitidasCant)}, {"513", d.NDEmitidasDebito}, {"509", int64(d.NCEmitidasCant)}, {"510", d.NCEmitidasDebito},
		{"586", int64(d.ExentasCant)}, {"142", d.VentasExentas}, {"538", d.TotalDebitos},
		{"519", int64(d.FactRecibidasCant)}, {"520", d.FactRecibidasCredito}, {"527", int64(d.NCRecibidasCant)}, {"528", d.NCRecibidasCredito},
		{"504", d.RemanenteAnterior}, {"537", d.TotalCreditos},
		{"89", iva}, {"77", d.RemanenteSiguiente()}, {"563", d.BasePPM}, {"62", d.PPM}, {"91", d.TotalAPagar()},
	}
	out := []Linea{}
	for _, c := range cand {
		if c.valor == 0 {
			continue
		}
		g, ok := CodigosF29[c.codigo]
		if !ok {
			g = [2]string{c.codigo, "CONF"}
		}
		out = append(out, Linea{Codigo: c.codigo, Glosa: g[0], Valor: c.valor, Confianza: g[1]})
	}
	return out
}
