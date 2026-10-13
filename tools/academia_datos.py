# Genera app/frontend/dist/academia.js (window.ACADEMIA = JSON). Fuente única de las lecciones.
#
# Cada lección se ve en la app como una secuencia de tarjetas ("pasos"), una idea por pantalla:
#   adivina  → una pregunta antes de explicar (el alumno apuesta, el visual revela)
#   idea     → dos o tres líneas; puede mostrar el visual, enfocarlo en una parte (foco) y traer
#              números vivos: <b data-vivo="iva">$ 190</b> se actualiza cuando el alumno mueve el visual
#   ejemplo  → un caso con números
#   pregunta → la de control, con explicación por opción equivocada (xo) cuando se escribió
#   mision   → opcional: algo para hacer en la app; nunca bloquea (la app acompaña, no obliga)
#   cierre   → "lo que te llevas", tres frases
# Las lecciones escritas con lec2() traen sus pasos a mano; las escritas con lec() se convierten
# solas (cada párrafo del concepto es una tarjeta).
import json
L = []
def lec(mod, id, titulo, resumen, concepto, ejemplo, pregunta, accion=None, claves=None):
    L.append({"modulo": mod, "id": id, "titulo": titulo, "resumen": resumen, "concepto": concepto,
              "ejemplo": ejemplo, "accion": accion, "pregunta": pregunta, "claves": claves})
def lec2(mod, id, titulo, resumen, *, adivina, ideas, ejemplo, pregunta, claves, mision=None):
    """ideas: lista de (html, opciones) con opciones = dict(vis=True/False, foco=str|None, titulo=str|None)."""
    pasos = [dict(tipo="adivina", **adivina)]
    for h, o in ideas:
        pasos.append({"tipo": "idea", "h": h, "vis": o.get("vis", True), "foco": o.get("foco"), "titulo": o.get("titulo")})
    pasos.append({"tipo": "idea", "h": ejemplo, "vis": True, "foco": None, "titulo": "Un ejemplo"})
    pasos.append({"tipo": "pregunta", **pregunta})
    if mision: pasos.append({"tipo": "mision", **mision})
    pasos.append({"tipo": "cierre", "claves": claves})
    L.append({"modulo": mod, "id": id, "titulo": titulo, "resumen": resumen, "concepto": "".join(h for h, _ in ideas),
              "ejemplo": ejemplo, "accion": ({"t": mision["t"], "v": mision["v"]} if mision else None), "pregunta": pregunta,
              "claves": claves, "pasos": pasos})
def q(t, o, c, x, xo=None): return {"t": t, "o": o, "c": c, "x": x, "xo": xo}
V = lambda **k: k  # opciones de una idea

MODULOS = [
 {"id": "basico", "titulo": "Lo básico", "resumen": "Qué es un impuesto, quién es el SII y por qué una boleta dice 1.190 y no 1.000."},
 {"id": "numeros", "titulo": "Los números del mes", "resumen": "UF, UTM, lo que cobras y lo que pagas de IVA, el F29 y el impuesto a la renta."},
 {"id": "empresa", "titulo": "Tu empresa", "resumen": "Persona natural o empresa, SpA, EIRL, los regímenes y el inicio de actividades."},
 {"id": "fechas", "titulo": "Las fechas", "resumen": "El calendario tributario: qué se declara cada mes, cada año, y qué pasa si te atrasas."},
 {"id": "documentos", "titulo": "Los documentos", "resumen": "Folio, timbre, notas de crédito y débito, el registro del SII y las dos formas de emitir."},
]

# ---------------- 1. Lo básico (una sola historia: Sofía y su puesto de jugos) ----------------
lec2("basico", "impuesto", "¿Qué es un impuesto?", "Plata que todos aportan para pagar lo que es de todos.",
 adivina=q("Sofía vende un jugo a $1.190 en la feria del colegio. ¿Cuánto de esa plata es impuesto?",
   ["Nada: todo es de Sofía", "$19", "$190", "$1.190"], 2,
   "De cada jugo, $190 no son de Sofía: son IVA y van al Estado. Ella los cobra y los entrega. Mira cómo se reparte."),
 ideas=[
  ("<p>Un <b>impuesto</b> es una parte de lo que ganas o gastas que va al Estado. Con esa plata se pagan colegios, hospitales, calles, pensiones. No es un castigo ni una multa: es la cuota de cada uno para lo que usamos en común.</p>", V()),
  ("<p>Mueve el precio del jugo. Si cuesta <b data-vivo=\"neto\">$ 1.000</b> sin IVA, el Estado recibe <b data-vivo=\"iva\">$ 190</b> y Sofía se queda con <b data-vivo=\"neto\">$ 1.000</b>. La parte amarilla nunca es de ella.</p>", V(foco="iva")),
  ("<p>Quien tiene un negocio no solo paga impuestos: también <b>recauda</b>. Cobra el IVA a sus clientes y se lo entrega al Estado a fin de mes. Por eso existen las boletas y las facturas: son la prueba de cuánto se cobró.</p>", V(foco="neg")),
  ("<p>En este curso importan dos impuestos: el <b>IVA</b>, que se paga cada vez que se compra algo, y el <b>impuesto a la renta</b>, que se paga una vez al año sobre lo que se ganó. Los dos aparecen más adelante.</p>", V(vis=False, titulo="Dos impuestos para recordar")),
 ],
 ejemplo="<p>Compras un cuaderno a $1.190. De esos pesos, $1.000 son de la librería y <b>$190 son IVA</b>: la librería los cobra, pero no son suyos; a fin de mes se los pasa al Estado.</p>",
 pregunta=q("¿Para qué sirven los impuestos?", ["Para castigar a quien gana mucho", "Para pagar lo que usamos todos: colegios, hospitales, calles", "Para que el SII tenga trabajo", "Para que los negocios ganen más"], 1,
   "Con los impuestos se financia lo que es de todos. Quien vende los cobra y los entrega; no se los queda.",
   ["No es un castigo: lo paga todo el que compra, gane poco o mucho.", None, "El SII solo lleva la cuenta; la plata va a lo que es de todos.", "El negocio no se queda con el impuesto: lo cobra y lo entrega."]),
 claves=["Un impuesto es la cuota de cada uno para lo que es de todos.", "El negocio cobra el IVA, pero no es suyo: lo entrega al Estado.", "La boleta es la prueba de cuánto se cobró."])

lec2("basico", "sii", "El SII y el RUT", "El SII es la oficina de los impuestos; el RUT es tu número.",
 adivina=q("El RUT 12.345.678-5 termina en 5. ¿Para qué sirve ese último número?",
   ["Dice en qué año nació la persona", "Detecta errores al escribir el RUT", "Dice de qué región es", "No sirve para nada"], 1,
   "Es el dígito verificador: se calcula con los otros números. Si escribes uno mal, deja de calzar y la app te avisa. Pruébalo."),
 ideas=[
  ("<p>El <b>SII</b> (Servicio de Impuestos Internos) es la oficina del Estado que lleva la cuenta de los impuestos: sabe qué vendiste, qué compraste y cuánto debes. Todo lo que emites se lo informa a él.</p>", V(vis=False)),
  ("<p>El <b>RUT</b> (Rol Único Tributario) es el número con que el SII te reconoce. Las personas tienen uno (el del carnet) y las empresas tienen otro propio, que empieza con 76 o 77. Si el puesto de Sofía se vuelve empresa, tendrá un RUT nuevo, distinto al de ella.</p>", V(vis=False)),
  ("<p>Cambia un número del RUT de arriba y mira qué pasa con el dígito del final. Así la app sabe si te equivocaste al escribir, antes de mandar nada al SII.</p>", V()),
  ("<p>Para entrar al SII por internet se usa la <b>clave tributaria</b>, una contraseña que te da el propio SII. Con ella se declara, se piden folios y se ven los documentos.</p>", V(vis=False)),
 ],
 ejemplo="<p>Un RUT se escribe con puntos y un guion: <b>12.345.678-5</b>. El último carácter puede ser un número o una K. Si alguien cambia el 5 del final por un 6, el dígito deja de calzar y la app lo dice de inmediato.</p>",
 pregunta=q("¿Qué es el RUT de una empresa?", ["El RUT del dueño", "Un número propio de la empresa, distinto al de las personas", "El número de la boleta", "La clave para entrar al SII"], 1,
   "La empresa es otra persona ante la ley y tiene su propio RUT. El dueño sigue teniendo el suyo.",
   ["El dueño tiene su propio RUT; la empresa, otro.", None, "El número de la boleta es el folio, otra cosa.", "La clave es una contraseña secreta; el RUT es un número público."]),
 claves=["El SII lleva la cuenta de los impuestos de todos.", "Tu RUT es tu número; una empresa tiene el suyo propio.", "El último dígito del RUT detecta errores de tipeo."],
 mision={"t": "Escribe un RUT en Emitir y mira cómo la app lo revisa mientras escribes", "v": "cobrar"})

lec2("basico", "iva", "El IVA", "El 19 % que va al Estado cada vez que se vende algo.",
 adivina=q("Sofía quiere ganar $1.000 por cada jugo. ¿A cuánto lo tiene que vender?",
   ["$1.000", "$1.019", "$1.190", "$1.900"], 2,
   "Al neto se le suma el 19 %: 1.000 + 190 = $1.190. Los $190 no son ganancia: son el IVA que después entrega. Mueve el deslizador y mira cómo cambia."),
 ideas=[
  ("<p>El <b>IVA</b> es el Impuesto al Valor Agregado. En Chile es el <b>19 %</b> y se suma al precio de casi todo: comida, ropa, servicios, entradas. Lo paga quien compra; el negocio solo lo <b>recauda</b>.</p>", V(foco="iva")),
  ("<p>Tres palabras: el precio sin IVA es el <b>neto</b>; el IVA es el 19 % del neto; la suma es el <b>total</b>. Ahora mismo arriba: neto <b data-vivo=\"neto\">$ 10.000</b>, IVA <b data-vivo=\"iva\">$ 1.900</b>, total <b data-vivo=\"total\">$ 11.900</b>.</p>", V()),
  ("<p>Cambia arriba a «Sé el precio con IVA». Si solo conoces el total, el neto sale dividiendo por 1,19. La app hace esa cuenta sola cada vez que escribes un precio.</p>", V()),
  ("<p>Lo importante: el IVA nunca es ganancia del negocio. Sofía lo cobra en cada jugo, lo junta, y a fin de mes se lo entrega al SII. Más adelante verás cómo (se llama F29).</p>", V(vis=False)),
 ],
 ejemplo="<p>Un jugo cuesta $1.000 neto. IVA: 1.000 × 0,19 = <b>$190</b>. Total: <b>$1.190</b>. Al revés: si la boleta dice $2.380, el neto es 2.380 ÷ 1,19 = $2.000 y el IVA $380.</p>",
 pregunta=q("Un producto vale $5.000 neto. ¿Cuánto dice el total de la boleta?", ["$5.000", "$5.190", "$5.950", "$6.900"], 2,
   "IVA: 5.000 × 0,19 = 950. Total: 5.000 + 950 = 5.950. El error común es sumar 19 pesos en vez del 19 %.",
   ["Ese es el neto; falta sumarle el IVA.", "Sumaste 19 pesos; el IVA es el 19 por ciento: 950.", None, "Eso sería un 38 %. El IVA es 19 %."]),
 claves=["IVA = 19 % del neto. Total = neto + IVA.", "Del total al neto: dividir por 1,19.", "El IVA se cobra, se junta y se entrega; no es ganancia."],
 mision={"t": "Si quieres verlo con tus números, emite una boleta de práctica por $1.000 y mira cómo la app separa neto e IVA", "v": "cobrar", "check": {"tipo": 39}})

lec2("basico", "boleta-factura", "Boleta o factura", "La boleta es para personas; la factura, para empresas.",
 adivina=q("El casino del colegio le compra 50 jugos a Sofía para una fiesta. ¿Qué documento le da?",
   ["Una boleta, como a cualquiera", "Una factura, con el RUT del casino", "Ninguno: entre conocidos no hace falta", "Un recibo escrito a mano"], 1,
   "El casino es una empresa y va a querer descontar el IVA de esa compra: necesita factura a su RUT. Cambia arriba a «Compra una empresa» y mira qué aparece."),
 ideas=[
  ("<p>Una <b>boleta</b> se le da a una persona que compra para sí misma. No lleva su nombre ni su RUT. Es el documento del almacén, el café, el puesto de jugos.</p>", V(foco="boleta")),
  ("<p>Una <b>factura</b> se le da a otra empresa. Lleva el RUT y el nombre del cliente y detalla el IVA, porque <b>a él le sirve para descontarlo</b> de lo que debe pagar.</p>", V(foco="factura")),
  ("<p>Los dos documentos informan la venta al SII y el IVA es el mismo. La diferencia es para quién son y qué puede hacer el cliente con ellos. Si no sabes cuál dar, pregunta: ¿compra para su casa o para su negocio?</p>", V()),
 ],
 ejemplo="<p>Un restaurante le compra café a una tostaduría por $100.000 + IVA. Pide <b>factura</b>: así los $19.000 de IVA que pagó se descuentan de los que él cobró a sus clientes ese mes. Si fuera una persona comprando café para su casa, sería <b>boleta</b>.</p>",
 pregunta=q("¿Quién puede descontar el IVA de una compra?", ["Cualquiera que guarde la boleta", "Solo quien recibió una factura a su RUT de empresa", "Nadie: el IVA no se descuenta", "Solo el SII"], 1,
   "La factura va a nombre de la empresa que compra, y ese IVA se resta del IVA que ella cobró. Con boleta no se puede.",
   ["Con boleta no: no lleva el RUT del comprador.", None, "Sí se descuenta, pero solo con factura.", "El SII recibe el IVA; quien lo descuenta es la empresa que compró."]),
 claves=["Boleta: para personas, sin nombre.", "Factura: para empresas, con RUT, y ese IVA se descuenta.", "Los dos informan la venta al SII."],
 mision={"t": "Si quieres, emite una factura de práctica a CLIENTE DEMO SPA y fíjate en que pide el RUT del cliente", "v": "cobrar", "check": {"tipo": 33}})

lec2("basico", "exento", "Con IVA o sin IVA", "Algunas cosas no llevan IVA: son exentas.",
 adivina=q("La prima de Sofía da clases de guitarra a $15.000. ¿Cuánto IVA lleva su boleta?",
   ["$2.850", "$1.500", "$0", "Depende de lo que ella decida"], 2,
   "La educación es exenta de IVA: la boleta va por $15.000, sin impuesto. No lo decide ella: lo dice la ley. Toca cada cosa de arriba y mira cuáles llevan IVA."),
 ideas=[
  ("<p>No todo lleva IVA. Son <b>exentos</b>, entre otros, la educación, la salud, los arriendos de casas sin muebles y el transporte de pasajeros. Para eso existen la <b>factura exenta</b> y la <b>boleta exenta</b>.</p>", V()),
  ("<p>Lo que sí lleva IVA se llama <b>afecto</b>. Si vendes algo afecto como exento, le cobras de menos al Estado; si vendes algo exento con IVA, le cobras de más a tu cliente. Las dos cosas traen problemas.</p>", V()),
  ("<p>Qué es afecto y qué es exento depende de la actividad que declaraste al SII (el <b>giro</b>). Si tienes dudas, el SII lo responde por escrito, y la app te deja elegir el tipo de documento.</p>", V(vis=False)),
 ],
 ejemplo="<p>Un profesor particular cobra $20.000 por una clase. Como la educación es exenta, la boleta dice <b>$20.000, IVA $0, total $20.000</b>. Un vendedor de cuadernos, en cambio, cobra $20.000 + $3.800 de IVA.</p>",
 pregunta=q("¿Cuál de estas cosas lleva IVA?", ["Una consulta médica", "Un cuaderno", "Un pasaje en bus", "El arriendo de una casa sin muebles"], 1,
   "El cuaderno es un producto afecto: lleva el 19 %. Salud, transporte de pasajeros y arriendo de casa sin muebles son exentos.",
   ["La salud es exenta de IVA.", None, "El transporte de pasajeros es exento.", "El arriendo de una casa sin muebles es exento."]),
 claves=["Afecto = lleva IVA. Exento = no lleva.", "Educación, salud, transporte de pasajeros y arriendo de casa: exentos.", "Lo define la ley y tu giro, no el vendedor."])

lec2("basico", "neto-total", "Neto, IVA y total", "Los tres números que aparecen en todo documento.",
 adivina=q("Sofía vendió 10 jugos a $1.190 cada uno. ¿Cuánto IVA juntó para entregar?",
   ["$119", "$1.190", "$1.900", "$2.261"], 2,
   "Total $11.900. Neto = 11.900 ÷ 1,19 = $10.000. IVA = $1.900. Arriba puedes partir del total y ver cómo se desarma."),
 ideas=[
  ("<p>Cualquier boleta o factura termina con tres números: el <b>neto</b> (lo que vale lo vendido), el <b>IVA</b> (el 19 % del neto) y el <b>total</b> (lo que paga el cliente). Si el documento es exento, el IVA es cero y el neto se llama <b>exento</b>.</p>", V()),
  ("<p>Al público le pones el precio <b>con IVA incluido</b>: el cliente ve $1.190. Mueve el total arriba: con <b data-vivo=\"total\">$ 11.900</b>, el neto es <b data-vivo=\"neto\">$ 10.000</b> y el IVA <b data-vivo=\"iva\">$ 1.900</b>. La app hace esa cuenta hacia atrás por ti.</p>", V()),
  ("<p>Entre empresas se habla en neto («$100.000 más IVA»), porque a la otra empresa el IVA le da lo mismo: lo descuenta. Los centavos se redondean, y la app lo hace igual que el SII.</p>", V(vis=False)),
 ],
 ejemplo="<p>Vendes tres poleras a $9.990 cada una, IVA incluido. Total: $29.970. Neto: 29.970 ÷ 1,19 = <b>$25.185</b>. IVA: <b>$4.785</b>.</p>",
 pregunta=q("Una boleta dice total $11.900. ¿Cuál es el neto?", ["$9.639", "$10.000", "$11.900", "$14.161"], 1,
   "Neto = total ÷ 1,19 = 11.900 ÷ 1,19 = 10.000. El IVA es la diferencia: 1.900.",
   ["Restaste el 19 % del total; hay que dividir por 1,19.", None, "Ese es el total; el neto es sin IVA.", "Le sumaste IVA a algo que ya lo tenía."]),
 claves=["Neto, IVA y total: los tres números de todo documento.", "Precio al público = con IVA incluido; la app calcula el neto hacia atrás.", "Entre empresas se habla en neto."],
 mision={"t": "Si quieres, escribe 11900 con IVA incluido en Emitir y mira aparecer los tres números", "v": "cobrar", "check": {"total": 11900}})

# ---------------- 2. Los números del mes ----------------
lec("numeros", "uf-utm", "UF y UTM", "Dos \"monedas\" que suben con la inflación, para que los montos no pierdan valor.",
 "<p>Los precios suben con el tiempo (eso es la <b>inflación</b>). Para que un contrato de hoy valga lo mismo en dos años, Chile usa unidades que se reajustan solas.</p>"
 "<p>La <b>UF</b> (Unidad de Fomento) cambia <b>todos los días</b> siguiendo la inflación. Se usa en arriendos, créditos, seguros y planes de salud. Hoy una UF vale alrededor de $41.000, y mañana unos pesos más.</p>"
 "<p>La <b>UTM</b> (Unidad Tributaria Mensual) cambia <b>una vez al mes</b>. La usa el SII para multas, tramos de impuestos y topes: por ejemplo, \"una multa de 1 UTM\". Vale alrededor de $70.000.</p>",
 "<p>Un arriendo de <b>10 UF</b> se paga en pesos al valor de la UF del día de pago: si la UF está a $41.152,13, son $411.521. El año que viene serán más pesos, pero las mismas 10 UF.</p>",
 q("¿Cuál cambia todos los días?", ["La UTM", "La UF", "Las dos", "Ninguna: cambian una vez al año"], 1,
   "La UF se reajusta a diario; la UTM, una vez al mes. Las dos siguen la inflación."),
 {"t": "Mira la UF y la UTM de hoy en Valores", "v": "valores"})

lec("numeros", "debito-credito", "Lo que cobras y lo que pagas", "El IVA de tus ventas menos el IVA de tus compras.",
 "<p>Todo el IVA que cobraste en tus boletas y facturas del mes se llama <b>débito fiscal</b>: es lo que le debes al Estado.</p>"
 "<p>Todo el IVA que pagaste en las facturas de tus compras para el negocio se llama <b>crédito fiscal</b>: es lo que el Estado te reconoce a favor. Solo cuenta si tienes <b>factura a tu RUT</b>; con boletas no.</p>"
 "<p>A fin de mes se restan: <b>débito − crédito = lo que pagas</b>. Si el crédito es mayor (compraste más de lo que vendiste), el saldo queda a tu favor para el mes siguiente; se llama <b>remanente</b>.</p>",
 "<p>En octubre vendiste $500.000 neto (cobraste $95.000 de IVA) y compraste mercadería con factura por $300.000 neto (pagaste $57.000 de IVA). Pagas <b>95.000 − 57.000 = $38.000</b>.</p>",
 q("Cobraste $19.000 de IVA y pagaste $10.000 en facturas de compras. ¿Cuánto declaras?", ["$29.000", "$19.000", "$9.000", "$10.000"], 2,
   "Débito 19.000 menos crédito 10.000 = 9.000. Solo se paga la diferencia."),
 {"t": "Mira el mes de la empresa de práctica: débito, crédito y diferencia", "v": "documentos?tab=mes"})

lec("numeros", "f29", "El F29, la declaración del mes", "Una vez al mes le cuentas al SII cuánto vendiste y pagas el IVA.",
 "<p>El <b>Formulario 29</b> (F29) es la declaración mensual. Se llena en sii.cl con lo vendido, lo comprado y el IVA de cada lado, y se paga la diferencia. El SII ya tiene casi todo (lo sabe por tus documentos electrónicos), así que te muestra una <b>propuesta</b> para revisar.</p>"
 "<p>Se declara <b>aunque no hayas vendido nada</b>: en ese caso se presenta \"sin movimiento\", en cero. Olvidarlo tiene multa.</p>"
 "<p>El plazo es el <b>día 12 del mes siguiente</b>. Quien emite documentos electrónicos y declara por internet con pago tiene hasta el <b>día 20</b>.</p>",
 "<p>Las ventas de octubre se declaran en el F29 de noviembre: hasta el 12 (o el 20 por internet). Ahí va el IVA cobrado en octubre menos el IVA pagado en octubre.</p>",
 q("No vendiste nada este mes. ¿Qué haces con el F29?", ["Nada: sin ventas no hay declaración", "Lo presento igual, sin movimiento", "Espero a juntar varios meses", "Lo presenta el SII por mí"], 1,
   "El F29 se presenta todos los meses, aunque sea en cero. Si no lo haces, hay multa."),
 {"t": "Mira lo que la app prepara para el F29 en \"Mi mes\"", "v": "documentos?tab=mes"})

lec("numeros", "ppm", "El PPM, un adelanto", "Cada mes pagas un poquito a cuenta del impuesto del año.",
 "<p>El impuesto a la renta se paga una vez al año, en abril. Para no llegar a esa fecha con una cuenta gigante, cada mes se adelanta una parte: el <b>PPM</b> (Pago Provisional Mensual).</p>"
 "<p>Es un porcentaje pequeño de las <b>ventas netas</b> del mes (al empezar, por ejemplo, un 0,25 %), y va en el mismo F29 junto con el IVA.</p>"
 "<p>En abril, al calcular el impuesto real del año, los PPM que ya pagaste se descuentan. Si pagaste de más, el SII te <b>devuelve</b> la diferencia.</p>",
 "<p>Vendiste $1.000.000 neto en el mes y tu PPM es 0,25 %: adelantas <b>$2.500</b>. En abril, si tu impuesto anual fue $20.000 y adelantaste $30.000 en el año, te devuelven $10.000.</p>",
 q("¿Qué es el PPM?", ["Un impuesto nuevo, aparte de los otros", "Un adelanto mensual del impuesto a la renta anual", "Una multa por atraso", "El IVA de las compras"], 1,
   "El PPM no es un impuesto extra: es el mismo impuesto a la renta, pagado de a poco durante el año."))

lec("numeros", "renta", "El impuesto a la renta y el F22", "Una vez al año, sobre lo que ganaste de verdad.",
 "<p>Además del IVA, existe el <b>impuesto a la renta</b>: se calcula sobre la <b>ganancia</b> (lo vendido menos los gastos del negocio), no sobre las ventas. Si no ganaste, no pagas.</p>"
 "<p>Se declara una vez al año, en <b>abril</b>, con el <b>Formulario 22</b> (F22). Es lo que se conoce como <b>Operación Renta</b>. Se declara el año anterior completo: en abril de 2027 se declara lo ganado en 2026.</p>"
 "<p>Las empresas pagan el impuesto de <b>primera categoría</b>; las personas, el <b>global complementario</b>, que sube por tramos: quien gana poco paga cero. El porcentaje de la empresa depende de su régimen y cambia con las leyes; el SII lo publica cada año.</p>",
 "<p>Una tienda vendió $12.000.000 en el año y gastó $10.000.000 en mercadería, arriendo y sueldos. Su ganancia fue <b>$2.000.000</b>: sobre eso se calcula el impuesto, no sobre los 12 millones.</p>",
 q("¿Sobre qué se calcula el impuesto a la renta de una empresa?", ["Sobre todas las ventas", "Sobre la ganancia: ventas menos gastos", "Sobre el IVA cobrado", "Sobre la UF"], 1,
   "La renta es la ganancia. Una empresa que vende mucho pero gasta casi lo mismo paga poco impuesto a la renta."))

# ---------------- 3. Tu empresa ----------------
lec("empresa", "persona-o-empresa", "¿Persona natural o empresa?", "Puedes emitir con tu propio RUT o crear uno nuevo.",
 "<p>Para vender con boleta no necesitas crear una empresa: una <b>persona natural</b> puede hacer <b>inicio de actividades</b> con su propio RUT y emitir boletas y facturas. Es lo más simple para empezar.</p>"
 "<p>Una <b>empresa</b> (persona jurídica) es un RUT nuevo, separado del tuyo. Lo que gana y lo que debe es de la empresa, no tuyo: si al negocio le va mal, tu casa y tus ahorros quedan aparte (con límites). Sirve también para tener socios y para vender la empresa algún día.</p>"
 "<p>Crearla toma un día y es gratis en <b>Empresa en un Día</b> (registroempresasysociedades.cl). Pero después hay que llevar contabilidad y declarar por la empresa, que es más trabajo.</p>",
 "<p>Una estudiante que hace tortas por encargo puede empezar como <b>persona natural</b> con giro de pastelería. Si el negocio crece y se junta con una amiga, crean una <b>SpA</b> con RUT propio y las dos como socias.</p>",
 q("¿Qué ventaja principal tiene crear una empresa en vez de usar tu RUT?", ["Paga menos IVA", "No hay que declarar", "Separa lo del negocio de lo tuyo y permite tener socios", "Es obligatorio para emitir boletas"], 2,
   "La empresa es otra persona ante la ley: sus deudas y ganancias son suyas. Para emitir boletas basta ser persona natural con inicio de actividades."),
 {"t": "Mira en Mi empresa cómo se agrega una empresa con su RUT", "v": "empresa"})

lec("empresa", "tipos-empresa", "SpA, EIRL, Ltda. y S.A.", "Las siglas que van después del nombre de una empresa.",
 "<p><b>EIRL</b> (Empresa Individual de Responsabilidad Limitada): una sola persona, sin socios. Simple, pero no se pueden sumar socios después.</p>"
 "<p><b>SpA</b> (Sociedad por Acciones): la más usada hoy para emprender. Puede tener uno o varios dueños (accionistas), es fácil sumar o cambiar socios y se crea en Empresa en un Día.</p>"
 "<p><b>Ltda.</b> (Sociedad de Responsabilidad Limitada): dos o más socios, cada uno responde solo por lo que aportó. Cambiar un socio exige modificar la sociedad, por eso hoy se prefiere la SpA.</p>"
 "<p><b>S.A.</b> (Sociedad Anónima): para empresas grandes, con directorio y muchas reglas. No es para empezar.</p>",
 "<p>Dos amigos abren una cafetería: crean <b>CAFÉ EJEMPLO SpA</b>, 50 % cada uno. Si más adelante entra un tercer socio, se le venden acciones y listo. Con una Ltda. habrían tenido que ir al notario a modificar la sociedad.</p>",
 q("Quieres empezar sola, pero quizás sumar un socio el próximo año. ¿Qué te conviene?", ["Una S.A.", "Una EIRL", "Una SpA", "No se puede empezar sola"], 2,
   "La SpA puede tener un solo accionista y sumar más después. La EIRL no admite socios, y la S.A. es para empresas grandes."))

lec("empresa", "regimenes", "Pro-PYME y los regímenes", "El \"plan\" de impuestos que tiene tu empresa.",
 "<p>Cada empresa está en un <b>régimen tributario</b>: el conjunto de reglas con que calcula su impuesto a la renta. Se elige al iniciar actividades y se puede cambiar.</p>"
 "<p>Para empresas chicas existe el <b>régimen Pro-PYME</b>, con reglas simplificadas. Tiene dos versiones: <b>Pro-PYME General</b> (la empresa paga su impuesto y los dueños pagan después por lo que retiran) y <b>Pro-PYME Transparente</b> (la empresa no paga impuesto propio: la ganancia se reparte y cada dueño la declara como suya).</p>"
 "<p>Las empresas grandes están en el <b>régimen general</b>, con contabilidad completa. Qué régimen conviene depende de cuánto se gana y cuánto se retira; es una buena pregunta para un contador.</p>",
 "<p>Una SpA de una sola dueña que retira toda la ganancia suele estar cómoda en <b>Pro-PYME Transparente</b>: declara una vez, como persona. Si quiere dejar la ganancia dentro de la empresa para reinvertir, le conviene más <b>Pro-PYME General</b>.</p>",
 q("¿Qué es un régimen tributario?", ["El nombre del contador", "Las reglas con que una empresa calcula su impuesto a la renta", "El porcentaje del IVA", "Una multa del SII"], 1,
   "El régimen define cómo se calcula el impuesto a la renta. Pro-PYME es el de las empresas chicas; el IVA es igual para todos."))

lec("empresa", "inicio-actividades", "Inicio de actividades y giro", "Avisarle al SII que empiezas, y a qué te vas a dedicar.",
 "<p>El <b>inicio de actividades</b> es el trámite con que le dices al SII \"empecé a trabajar\". Se hace en sii.cl y es gratis. Desde ese momento puedes emitir documentos y tienes la obligación de declarar.</p>"
 "<p>Hay que hacerlo dentro de los <b>dos meses</b> siguientes a la primera venta. Antes de eso, no deberías estar vendiendo.</p>"
 "<p>Al hacerlo eliges tu <b>giro</b>: a qué te dedicas. Cada giro tiene un <b>código de actividad</b> de seis cifras. El código define si tus ventas son afectas o exentas de IVA y si puedes emitir boletas, facturas o ambas. Se pueden tener varios giros.</p>",
 "<p>\"Venta al por menor de alimentos en almacenes\" es un giro afecto a IVA: emites boletas con IVA. \"Enseñanza de idiomas\" es un giro exento: emites boletas exentas. La app pide ese código en Mi empresa porque va impreso en cada documento.</p>",
 q("¿Cuándo debes hacer el inicio de actividades?", ["Cuando la empresa gane su primer millón", "Dentro de los dos meses desde que empiezas a vender", "Solo si tienes empleados", "Nunca, si eres persona natural"], 1,
   "El plazo es de dos meses desde que empiezas. Vale para personas naturales y para empresas."),
 {"t": "Escribe el código de actividad en los datos de tu empresa", "v": "empresa"})

lec("empresa", "claves", "Clave tributaria y certificado digital", "Dos llaves distintas, para dos cosas distintas.",
 "<p>La <b>clave tributaria</b> es la contraseña para entrar a sii.cl. Con ella se declara, se ven documentos y se usa el sistema gratuito del SII. La da el SII y es de la persona (o de la empresa). Si alguien la tiene, puede hacer todo lo anterior en tu nombre: cuídala como una clave del banco.</p>"
 "<p>El <b>certificado digital</b> es otra cosa: un archivo (.p12 o .pfx) que <b>firma</b> documentos electrónicos, como una firma de puño y letra pero imposible de imitar. Se compra a una empresa autorizada, dura uno a tres años y tiene su propia contraseña. Es de una persona, no de la empresa; la empresa autoriza a esa persona.</p>"
 "<p>En Faro, el certificado se guarda cifrado y se abre con tu <b>PIN</b>. La clave tributaria solo se pide cuando hace falta.</p>",
 "<p>Para emitir una factura con tu propio sistema, la app <b>firma</b> el documento con el certificado. Para pedir folios al SII o usar su sistema gratuito, entra con la <b>clave tributaria</b>. Son dos llaves y las dos se cuidan.</p>",
 q("¿Para qué sirve el certificado digital?", ["Para entrar a sii.cl", "Para firmar documentos electrónicos", "Para pagar el IVA", "Para crear la empresa"], 1,
   "El certificado firma. Para entrar a sii.cl se usa la clave tributaria. Son llaves distintas con contraseñas distintas."),
 {"t": "Carga tu certificado en Mi empresa (o mira cómo se hace)", "v": "empresa"})

# ---------------- 4. Las fechas ----------------
lec("fechas", "calendario", "El calendario tributario", "Qué se hace cada mes y qué se hace cada año.",
 "<p><b>Cada día</b>: emites tus boletas y facturas. Si emites boletas electrónicas, al final del día el SII recibe un <b>resumen de ventas diarias</b>; la app lo manda sola.</p>"
 "<p><b>Cada mes</b>: el <b>F29</b> con el IVA y el PPM, hasta el día 12 del mes siguiente (día 20 por internet con pago, para quien emite electrónicamente).</p>"
 "<p><b>Cada año</b>: en <b>abril</b>, el <b>F22</b> con el impuesto a la renta del año anterior (Operación Renta). Las empresas además presentan en marzo <b>declaraciones juradas</b> con información de sueldos, retiros y otros datos.</p>"
 "<p><b>Una vez</b>: el inicio de actividades al empezar, y el <b>término de giro</b> si cierras.</p>",
 "<p>Octubre: vendes todos los días y la app envía los resúmenes. 12 (o 20) de noviembre: F29 de octubre. Abril del año siguiente: F22 con todo el año. Si te lo anotas en el calendario del teléfono, no se te pasa.</p>",
 q("¿Cuándo se declara el impuesto a la renta del año?", ["Cada mes, en el F29", "En abril del año siguiente, en el F22", "El 31 de diciembre", "Cuando el SII te llama"], 1,
   "La renta se declara una vez al año, en abril, por el año anterior completo. Lo mensual es el F29."))

lec("fechas", "honorarios", "Boletas de honorarios y la retención", "Para quien trabaja por su cuenta sin vender productos.",
 "<p>Un profesional independiente (diseñador, profesor, fotógrafo) no emite boletas de venta: emite <b>boletas de honorarios</b>, en sii.cl, sin IVA.</p>"
 "<p>De cada boleta se <b>retiene</b> un porcentaje como adelanto del impuesto a la renta: si el cliente es empresa, la empresa lo retiene y lo paga al SII; si es una persona, lo pagas tú en el F29. Ese porcentaje sube un poco cada año; en 2026 ronda el <b>15 %</b>. Parte de esa retención financia tus cotizaciones de salud y pensión.</p>"
 "<p>En abril, en el F22, se calcula tu impuesto real del año y se descuenta lo retenido. Muchas personas reciben <b>devolución</b>.</p>",
 "<p>Haces un diseño por $100.000 para una empresa. Emites boleta de honorarios por $100.000; la empresa te paga unos $85.000 y le entrega el resto al SII como retención a tu nombre. En abril se ajusta.</p>",
 q("¿Qué diferencia tiene una boleta de honorarios con una boleta de venta?", ["Ninguna", "No lleva IVA y se le retiene un porcentaje para el impuesto a la renta", "Lleva el doble de IVA", "Solo la emiten empresas"], 1,
   "Los honorarios no llevan IVA, pero sí retención: un adelanto del impuesto anual que después se ajusta en abril."))

lec("fechas", "multas", "Si te atrasas", "Qué pasa cuando una declaración llega tarde.",
 "<p>Declarar fuera de plazo tiene <b>multa</b> (un porcentaje del impuesto, con un mínimo en UTM) e <b>intereses</b> por cada mes de atraso. Si el F29 era sin movimiento, igual hay multa por no presentarlo, aunque más baja.</p>"
 "<p>Lo peor no es atrasarse, es <b>no hacer nada</b>: el SII manda avisos, y si nadie responde puede bloquear la emisión de documentos. Un F29 atrasado se presenta igual, cuanto antes, y el propio sitio calcula la multa.</p>"
 "<p>También hay multas por emitir mal: vender sin boleta, o usar folios que no te pertenecen. Por eso la app te hace revisar antes de emitir y cuida los folios.</p>",
 "<p>Se te pasó el F29 de octubre y lo presentas el 5 de diciembre: pagas el IVA de octubre más una multa pequeña e intereses de un mes. Molesto, pero se arregla. Dejarlo seis meses sin presentar es un problema mucho mayor.</p>",
 q("Se te pasó la fecha del F29. ¿Qué conviene hacer?", ["Esperar a que el SII avise", "Presentarlo igual lo antes posible, aunque tenga multa", "Saltarse ese mes y seguir con el siguiente", "Cerrar la empresa"], 1,
   "Un atraso corto cuesta poco; un F29 que nunca se presenta cuesta mucho más. Se presenta igual, cuanto antes."))

# ---------------- 5. Los documentos ----------------
lec("documentos", "folio", "El folio y el timbre", "Cada documento tiene un número único que el SII autorizó antes.",
 "<p>El <b>folio</b> es el número del documento: Boleta N° 1, N° 2, N° 3… Nunca se repite y nunca se salta. Por él, el SII sabe cuántos documentos emitiste.</p>"
 "<p>Los folios no los inventas tú: los <b>pide al SII</b> tu sistema, en rangos (por ejemplo, del 1 al 50). Ese permiso es un archivo llamado <b>CAF</b>. Con él, tu sistema le pone a cada documento un <b>timbre electrónico</b> (el código de barras cuadrado que ves en las boletas).</p>"
 "<p>Un folio usado no vuelve: si te equivocas, no se borra, se corrige con otro documento. Y pedir folios que no vas a usar hace que el SII te frene: se piden de a poco.</p>",
 "<p>Pides 5 folios de boleta: el SII te autoriza del 1 al 5. Emites tres boletas (1, 2 y 3). Te quedan dos. Cuando se acaban, pides más; el siguiente rango empieza en 6.</p>",
 q("Te equivocaste en la boleta N° 7. ¿Qué pasa con ese folio?", ["Se borra y la siguiente vuelve a ser la 7", "Se corrige con una nota de crédito; la 7 ya está usada", "Se le pide al SII que lo devuelva", "Se repite la 7 con los datos correctos"], 1,
   "Los folios no se borran ni se reutilizan. El error se corrige con una nota de crédito, que es otro documento con su propio folio."),
 {"t": "Mira los folios de la empresa en Mi empresa", "v": "empresa"})

lec("documentos", "notas", "Nota de crédito y nota de débito", "Cómo se corrige un documento sin borrarlo.",
 "<p>Nada emitido se borra. Si una boleta o factura salió mal, se emite otro documento que la corrige:</p>"
 "<p>La <b>nota de crédito</b> <b>resta</b>: anula un documento completo o rebaja parte del monto (un descuento, una devolución). Deja el IVA cobrado de más a tu favor.</p>"
 "<p>La <b>nota de débito</b> <b>suma</b>: agrega un cobro que faltó (un flete que no pusiste) o deja sin efecto una nota de crédito que se emitió por error.</p>"
 "<p>Cada nota dice a qué documento se refiere (tipo, folio y fecha). Así el SII entiende la historia completa.</p>",
 "<p>Emitiste la factura N° 12 por $100.000 + IVA y el cliente devolvió la mitad. Emites una <b>nota de crédito</b> por $50.000 + IVA que refiere a la factura 12. Si después descubres que faltó cobrar $5.000 de despacho, emites una <b>nota de débito</b> por ese monto.</p>",
 q("Cobraste de menos en una boleta. ¿Con qué documento lo arreglas?", ["Con una nota de crédito", "Con una nota de débito", "Borrando la boleta", "Con otra boleta por la diferencia"], 1,
   "La nota de débito suma lo que faltó y refiere a la boleta original. La nota de crédito es para restar."),
 {"t": "Anula una boleta de práctica desde Documentos y mira la nota de crédito", "v": "documentos"})

lec("documentos", "rcv", "El Registro de Compras y Ventas", "La libreta del SII donde queda todo lo que emitiste y recibiste.",
 "<p>Cada documento electrónico que emites y cada factura que te emiten a ti llegan al SII. Él los ordena en el <b>Registro de Compras y Ventas</b> (RCV): tu libreta oficial del mes.</p>"
 "<p>De ahí sale la <b>propuesta de F29</b>: el SII suma el IVA de tus ventas y el de tus compras y te lo muestra listo. Tu trabajo es revisar que esté todo y que no falte ni sobre nada.</p>"
 "<p>Si recibiste una factura que no corresponde (alguien te facturó por error), tienes ocho días para <b>reclamarla</b> en el SII; si no, se da por aceptada y entra a tu registro.</p>",
 "<p>En \"Mi mes\" la app te muestra el mismo cálculo que hace el SII con tus documentos: ventas, compras, débito, crédito y la diferencia. Si los números no coinciden con la propuesta del SII, es que falta o sobra un documento.</p>",
 q("¿De dónde saca el SII la propuesta de tu F29?", ["De lo que tú le escribes cada mes", "Del Registro de Compras y Ventas, armado con tus documentos electrónicos", "De tu cuenta bancaria", "De la UF"], 1,
   "El SII ya tiene tus documentos electrónicos. Con ellos arma el registro y la propuesta; tú la revisas."),
 {"t": "Compara tu mes con lo que el SII propone", "v": "documentos?tab=mes"})

lec("documentos", "gratuito-propio", "Sistema gratuito o motor propio", "Dos formas de emitir; cuál conviene a cada uno.",
 "<p>El SII tiene un <b>sistema gratuito</b> para emitir facturas y boletas desde su sitio, con la clave tributaria. Sirve para empezar y para quien emite pocos documentos. Faro puede operarlo por ti y guardarte los PDF.</p>"
 "<p>Un <b>motor propio</b> (como el de Faro) emite desde tu computador: pide folios, firma con tu certificado y envía al SII. Es para quien emite mucho, quiere integrarlo con su caja o su sistema, o quiere ser dueño de sus documentos. Antes de usarlo en serio hay que pasar la <b>certificación</b>: un set de pruebas que el SII revisa.</p>"
 "<p>Las dos formas son válidas y una empresa puede partir con el gratuito y pasar al propio después. Lo que no cambia es lo que aprendiste: IVA, folios, F29.</p>",
 "<p>Una pastelería que vende por encargo diez veces al mes está bien con el sistema gratuito. Un minimarket que emite doscientas boletas al día necesita un motor propio conectado a su caja.</p>",
 q("¿Qué hace falta antes de emitir documentos reales con un motor propio?", ["Nada: se instala y se emite", "Pasar la certificación del SII en su ambiente de pruebas", "Pagar una licencia al SII", "Tener más de 10 empleados"], 1,
   "El SII exige certificar el software antes de usarlo en producción. Por eso la app tiene un ambiente de pruebas (amarillo) separado del real (rojo)."),
 {"t": "Recorre las etapas 4 y 5 del camino, más abajo en Aprender", "v": "aprender"})

# Conversión automática para las lecciones escritas con lec(): cada párrafo del concepto es una tarjeta;
# el visual acompaña desde la primera; la acción pasa a misión opcional; el cierre usa las claves o el resumen.
def armar_pasos(l):
    if l.get("pasos"): return l["pasos"]
    import re as _re
    parrafos = _re.findall(r"<p>.*?</p>", l["concepto"], _re.S)
    pasos = [{"tipo": "idea", "h": p, "vis": True, "foco": None, "titulo": None} for p in parrafos]
    pasos.append({"tipo": "idea", "h": l["ejemplo"], "vis": True, "foco": None, "titulo": "Un ejemplo"})
    pasos.append({"tipo": "pregunta", **l["pregunta"]})
    if l.get("accion"): pasos.append({"tipo": "mision", "t": l["accion"]["t"], "v": l["accion"]["v"]})
    pasos.append({"tipo": "cierre", "claves": l.get("claves") or [l["resumen"]]})
    return pasos
for l in L: l["pasos"] = armar_pasos(l)

datos = {"version": 2, "modulos": MODULOS, "lecciones": L}
js = "// Mini academia: las lecciones como datos. Generado por tools/academia_datos.py (desde la raíz del repo); se valida con\n// tools/revisar_academia.py. Para alumnos de colegio: cada lección es una secuencia de pasos (adivina, idea, ejemplo,\n// pregunta, misión opcional, cierre) que la app muestra de a una tarjeta.\nwindow.ACADEMIA = " + json.dumps(datos, ensure_ascii=False, indent=1) + ";\n"
open("app/frontend/dist/academia.js", "w", encoding="utf-8").write(js)
print(len(L), "lecciones,", len(MODULOS), "módulos,", sum(1 for l in L if any(p["tipo"] == "adivina" for p in l["pasos"])), "con adivina,", len(js)//1024, "KB")
