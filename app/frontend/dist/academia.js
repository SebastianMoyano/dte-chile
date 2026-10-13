// Mini academia: las lecciones como datos. Generado por tools/academia_datos.py (desde la raíz del repo); se valida con
// tools/revisar_academia.py. Para alumnos de colegio: concepto, ejemplo con números, acción en la app y una pregunta.
window.ACADEMIA = {
 "version": 1,
 "modulos": [
  {
   "id": "basico",
   "titulo": "Lo básico",
   "resumen": "Qué es un impuesto, quién es el SII y por qué una boleta dice 1.190 y no 1.000."
  },
  {
   "id": "numeros",
   "titulo": "Los números del mes",
   "resumen": "UF, UTM, lo que cobras y lo que pagas de IVA, el F29 y el impuesto a la renta."
  },
  {
   "id": "empresa",
   "titulo": "Tu empresa",
   "resumen": "Persona natural o empresa, SpA, EIRL, los regímenes y el inicio de actividades."
  },
  {
   "id": "fechas",
   "titulo": "Las fechas",
   "resumen": "El calendario tributario: qué se declara cada mes, cada año, y qué pasa si te atrasas."
  },
  {
   "id": "documentos",
   "titulo": "Los documentos",
   "resumen": "Folio, timbre, notas de crédito y débito, el registro del SII y las dos formas de emitir."
  }
 ],
 "lecciones": [
  {
   "modulo": "basico",
   "id": "impuesto",
   "titulo": "¿Qué es un impuesto?",
   "resumen": "Plata que todos aportan para pagar lo que es de todos.",
   "concepto": "<p>Un <b>impuesto</b> es una parte de lo que ganas o gastas que va al Estado. Con esa plata se pagan colegios, hospitales, calles, carabineros, pensiones. No es un castigo ni una multa: es la cuota de cada uno para lo que usamos en común.</p><p>Hay impuestos de muchos tipos. En este curso importan dos: el <b>IVA</b>, que se paga cada vez que se compra algo, y el <b>impuesto a la renta</b>, que se paga una vez al año sobre lo que se ganó.</p><p>Quien tiene un negocio no solo paga impuestos: también <b>recauda</b>, es decir, cobra el IVA a sus clientes y se lo entrega al Estado. Por eso existen las boletas y las facturas: son la prueba de cuánto se cobró.</p>",
   "ejemplo": "<p>Compras un cuaderno a $1.190. De esos pesos, $1.000 son del negocio y <b>$190 son IVA</b>: la librería los cobra, pero no son suyos; a fin de mes se los pasa al Estado.</p>",
   "accion": null,
   "pregunta": {
    "t": "¿Para qué sirven los impuestos?",
    "o": [
     "Para castigar a quien gana mucho",
     "Para pagar lo que usamos todos: colegios, hospitales, calles",
     "Para que el SII tenga trabajo",
     "Para que los negocios ganen más"
    ],
    "c": 1,
    "x": "Con los impuestos se financia lo que es de todos. Quien vende los cobra y los entrega; no se los queda."
   }
  },
  {
   "modulo": "basico",
   "id": "sii",
   "titulo": "El SII y el RUT",
   "resumen": "El SII es la oficina de los impuestos; el RUT es tu número.",
   "concepto": "<p>El <b>SII</b> (Servicio de Impuestos Internos) es la oficina del Estado que lleva la cuenta de los impuestos: sabe qué vendiste, qué compraste y cuánto debes. Todo lo que emites se lo informa a él.</p><p>El <b>RUT</b> (Rol Único Tributario) es el número con que el SII te reconoce. Las personas tienen uno (es el mismo del carnet) y las empresas tienen otro, propio, que empieza con 76 o 77. En cada boleta y factura va el RUT de quien vende, y en la factura también el de quien compra.</p><p>Para entrar al SII por internet se usa la <b>clave tributaria</b>, una contraseña que te da el propio SII. Con ella se declara, se piden folios y se ven los documentos.</p>",
   "ejemplo": "<p>Un RUT se escribe con puntos y un guion: <b>12.345.678-5</b>. El último carácter es el <b>dígito verificador</b>, que puede ser un número o una K; sirve para detectar errores de tipeo. La app lo revisa sola.</p>",
   "accion": {
    "t": "Escribe un RUT en la app y mira cómo lo valida",
    "v": "cobrar"
   },
   "pregunta": {
    "t": "¿Qué es el RUT de una empresa?",
    "o": [
     "El RUT del dueño",
     "Un número propio de la empresa, distinto al de las personas",
     "El número de la boleta",
     "La clave para entrar al SII"
    ],
    "c": 1,
    "x": "La empresa es otra persona ante la ley y tiene su propio RUT. El dueño sigue teniendo el suyo."
   }
  },
  {
   "modulo": "basico",
   "id": "iva",
   "titulo": "El IVA",
   "resumen": "El 19 % que va al Estado cada vez que se vende algo.",
   "concepto": "<p>El <b>IVA</b> es el Impuesto al Valor Agregado. En Chile es el <b>19 %</b> y se suma al precio de casi todo lo que se compra: comida, ropa, servicios, entradas.</p><p>Lo paga quien compra. El negocio solo lo <b>recauda</b>: lo cobra en la boleta y a fin de mes se lo entrega al SII. Por eso un negocio nunca debe pensar que el IVA es ganancia suya.</p><p>Para calcularlo: el precio sin IVA se llama <b>neto</b>; el IVA es el 19 % del neto; la suma es el <b>total</b>. Si solo conoces el total, el neto se obtiene dividiendo por 1,19.</p>",
   "ejemplo": "<p>Un café cuesta $1.000 neto. IVA: 1.000 × 0,19 = <b>$190</b>. Total: <b>$1.190</b>. Al revés: si la boleta dice $2.380, el neto es 2.380 ÷ 1,19 = $2.000 y el IVA $380.</p>",
   "accion": {
    "t": "Emite una boleta de práctica y mira cómo la app separa neto e IVA",
    "v": "cobrar"
   },
   "pregunta": {
    "t": "Un producto vale $5.000 neto. ¿Cuánto dice el total de la boleta?",
    "o": [
     "$5.000",
     "$5.190",
     "$5.950",
     "$6.900"
    ],
    "c": 2,
    "x": "IVA: 5.000 × 0,19 = 950. Total: 5.000 + 950 = 5.950. El error común es sumar 19 pesos en vez del 19 %."
   }
  },
  {
   "modulo": "basico",
   "id": "boleta-factura",
   "titulo": "Boleta o factura",
   "resumen": "La boleta es para personas; la factura, para empresas.",
   "concepto": "<p>Una <b>boleta</b> se le da a una persona que compra para sí misma. No lleva su nombre ni su RUT. Es el documento del almacén, el café, la peluquería.</p><p>Una <b>factura</b> se le da a otra empresa (o a alguien que compra para su negocio). Lleva el RUT y el nombre del cliente y detalla el IVA, porque <b>a él le sirve para descontarlo</b> de lo que debe pagar.</p><p>Los dos documentos informan la venta al SII. La diferencia es para quién son y qué puede hacer el cliente con ellos.</p>",
   "ejemplo": "<p>Un restaurante le compra café a una tostaduría por $100.000 + IVA. Pide <b>factura</b>: así los $19.000 de IVA que pagó se descuentan de los que él cobró a sus clientes ese mes. Si fuera una persona comprando café para su casa, sería <b>boleta</b>.</p>",
   "accion": {
    "t": "Emite una factura de práctica a CLIENTE DEMO SPA",
    "v": "cobrar"
   },
   "pregunta": {
    "t": "¿Quién puede descontar el IVA de una compra?",
    "o": [
     "Cualquiera que guarde la boleta",
     "Solo quien recibió una factura a su RUT de empresa",
     "Nadie: el IVA no se descuenta",
     "Solo el SII"
    ],
    "c": 1,
    "x": "La factura va a nombre de la empresa que compra, y ese IVA se resta del IVA que ella cobró. Con boleta no se puede."
   }
  },
  {
   "modulo": "basico",
   "id": "exento",
   "titulo": "Con IVA o sin IVA",
   "resumen": "Algunas cosas no llevan IVA: son exentas.",
   "concepto": "<p>No todo lleva IVA. Son <b>exentos</b>, entre otros, la educación, la salud, los arriendos de casas sin muebles, el transporte de pasajeros y algunos servicios profesionales. Para eso existen la <b>factura exenta</b> y la <b>boleta exenta</b>.</p><p>Lo que sí lleva IVA se llama <b>afecto</b>. Si vendes algo afecto y lo emites como exento, estás cobrando de menos al Estado; si vendes algo exento con IVA, estás cobrando de más a tu cliente. Las dos cosas traen problemas.</p><p>Qué es afecto y qué es exento depende de la actividad que declaraste al SII (el <b>giro</b>). Si tienes dudas, el SII lo responde por escrito.</p>",
   "ejemplo": "<p>Un profesor particular cobra $20.000 por una clase. Como la educación es exenta, la boleta dice <b>$20.000, IVA $0, total $20.000</b>. Un vendedor de cuadernos, en cambio, cobra $20.000 + $3.800 de IVA.</p>",
   "accion": null,
   "pregunta": {
    "t": "Una clase de guitarra cuesta $15.000. ¿Cuánto IVA lleva la boleta?",
    "o": [
     "$2.850",
     "$1.500",
     "$0, porque la educación es exenta",
     "Depende del profesor"
    ],
    "c": 2,
    "x": "La educación es exenta de IVA: la boleta va por $15.000 sin impuesto. No es una decisión del vendedor, es la ley."
   }
  },
  {
   "modulo": "basico",
   "id": "neto-total",
   "titulo": "Neto, IVA y total",
   "resumen": "Los tres números que aparecen en todo documento.",
   "concepto": "<p>Cualquier boleta o factura tiene tres números al final: el <b>neto</b> (lo que vale lo vendido), el <b>IVA</b> (el 19 % del neto) y el <b>total</b> (lo que paga el cliente). Si el documento es exento, el IVA es cero y el neto se llama <b>exento</b>.</p><p>Cuando pones un precio al público, normalmente lo piensas <b>con IVA incluido</b>: el cliente ve $1.190. La app te deja escribir ese precio y calcula sola el neto y el IVA hacia atrás.</p><p>Para una factura entre empresas, lo normal es hablar en neto (\"$100.000 más IVA\"), porque a la otra empresa el IVA le da lo mismo: lo descuenta.</p>",
   "ejemplo": "<p>Vendes tres poleras a $9.990 cada una, IVA incluido. Total: $29.970. Neto: 29.970 ÷ 1,19 = <b>$25.185</b>. IVA: <b>$4.785</b>. Los centavos se redondean, y la app lo hace igual que el SII.</p>",
   "accion": {
    "t": "Escribe 11900 con IVA incluido en Emitir y mira los tres números",
    "v": "cobrar"
   },
   "pregunta": {
    "t": "Una boleta dice total $11.900. ¿Cuál es el neto?",
    "o": [
     "$9.639",
     "$10.000",
     "$11.900",
     "$14.161"
    ],
    "c": 1,
    "x": "Neto = total ÷ 1,19 = 11.900 ÷ 1,19 = 10.000. El IVA es la diferencia: 1.900."
   }
  },
  {
   "modulo": "numeros",
   "id": "uf-utm",
   "titulo": "UF y UTM",
   "resumen": "Dos \"monedas\" que suben con la inflación, para que los montos no pierdan valor.",
   "concepto": "<p>Los precios suben con el tiempo (eso es la <b>inflación</b>). Para que un contrato de hoy valga lo mismo en dos años, Chile usa unidades que se reajustan solas.</p><p>La <b>UF</b> (Unidad de Fomento) cambia <b>todos los días</b> siguiendo la inflación. Se usa en arriendos, créditos, seguros y planes de salud. Hoy una UF vale alrededor de $41.000, y mañana unos pesos más.</p><p>La <b>UTM</b> (Unidad Tributaria Mensual) cambia <b>una vez al mes</b>. La usa el SII para multas, tramos de impuestos y topes: por ejemplo, \"una multa de 1 UTM\". Vale alrededor de $70.000.</p>",
   "ejemplo": "<p>Un arriendo de <b>10 UF</b> se paga en pesos al valor de la UF del día de pago: si la UF está a $41.152,13, son $411.521. El año que viene serán más pesos, pero las mismas 10 UF.</p>",
   "accion": {
    "t": "Mira la UF y la UTM de hoy en Valores",
    "v": "valores"
   },
   "pregunta": {
    "t": "¿Cuál cambia todos los días?",
    "o": [
     "La UTM",
     "La UF",
     "Las dos",
     "Ninguna: cambian una vez al año"
    ],
    "c": 1,
    "x": "La UF se reajusta a diario; la UTM, una vez al mes. Las dos siguen la inflación."
   }
  },
  {
   "modulo": "numeros",
   "id": "debito-credito",
   "titulo": "Lo que cobras y lo que pagas",
   "resumen": "El IVA de tus ventas menos el IVA de tus compras.",
   "concepto": "<p>Todo el IVA que cobraste en tus boletas y facturas del mes se llama <b>débito fiscal</b>: es lo que le debes al Estado.</p><p>Todo el IVA que pagaste en las facturas de tus compras para el negocio se llama <b>crédito fiscal</b>: es lo que el Estado te reconoce a favor. Solo cuenta si tienes <b>factura a tu RUT</b>; con boletas no.</p><p>A fin de mes se restan: <b>débito − crédito = lo que pagas</b>. Si el crédito es mayor (compraste más de lo que vendiste), el saldo queda a tu favor para el mes siguiente; se llama <b>remanente</b>.</p>",
   "ejemplo": "<p>En octubre vendiste $500.000 neto (cobraste $95.000 de IVA) y compraste mercadería con factura por $300.000 neto (pagaste $57.000 de IVA). Pagas <b>95.000 − 57.000 = $38.000</b>.</p>",
   "accion": {
    "t": "Mira el mes de la empresa de práctica: débito, crédito y diferencia",
    "v": "documentos?tab=mes"
   },
   "pregunta": {
    "t": "Cobraste $19.000 de IVA y pagaste $10.000 en facturas de compras. ¿Cuánto declaras?",
    "o": [
     "$29.000",
     "$19.000",
     "$9.000",
     "$10.000"
    ],
    "c": 2,
    "x": "Débito 19.000 menos crédito 10.000 = 9.000. Solo se paga la diferencia."
   }
  },
  {
   "modulo": "numeros",
   "id": "f29",
   "titulo": "El F29, la declaración del mes",
   "resumen": "Una vez al mes le cuentas al SII cuánto vendiste y pagas el IVA.",
   "concepto": "<p>El <b>Formulario 29</b> (F29) es la declaración mensual. Se llena en sii.cl con lo vendido, lo comprado y el IVA de cada lado, y se paga la diferencia. El SII ya tiene casi todo (lo sabe por tus documentos electrónicos), así que te muestra una <b>propuesta</b> para revisar.</p><p>Se declara <b>aunque no hayas vendido nada</b>: en ese caso se presenta \"sin movimiento\", en cero. Olvidarlo tiene multa.</p><p>El plazo es el <b>día 12 del mes siguiente</b>. Quien emite documentos electrónicos y declara por internet con pago tiene hasta el <b>día 20</b>.</p>",
   "ejemplo": "<p>Las ventas de octubre se declaran en el F29 de noviembre: hasta el 12 (o el 20 por internet). Ahí va el IVA cobrado en octubre menos el IVA pagado en octubre.</p>",
   "accion": {
    "t": "Mira lo que la app prepara para el F29 en \"Mi mes\"",
    "v": "documentos?tab=mes"
   },
   "pregunta": {
    "t": "No vendiste nada este mes. ¿Qué haces con el F29?",
    "o": [
     "Nada: sin ventas no hay declaración",
     "Lo presento igual, sin movimiento",
     "Espero a juntar varios meses",
     "Lo presenta el SII por mí"
    ],
    "c": 1,
    "x": "El F29 se presenta todos los meses, aunque sea en cero. Si no lo haces, hay multa."
   }
  },
  {
   "modulo": "numeros",
   "id": "ppm",
   "titulo": "El PPM, un adelanto",
   "resumen": "Cada mes pagas un poquito a cuenta del impuesto del año.",
   "concepto": "<p>El impuesto a la renta se paga una vez al año, en abril. Para no llegar a esa fecha con una cuenta gigante, cada mes se adelanta una parte: el <b>PPM</b> (Pago Provisional Mensual).</p><p>Es un porcentaje pequeño de las <b>ventas netas</b> del mes (al empezar, por ejemplo, un 0,25 %), y va en el mismo F29 junto con el IVA.</p><p>En abril, al calcular el impuesto real del año, los PPM que ya pagaste se descuentan. Si pagaste de más, el SII te <b>devuelve</b> la diferencia.</p>",
   "ejemplo": "<p>Vendiste $1.000.000 neto en el mes y tu PPM es 0,25 %: adelantas <b>$2.500</b>. En abril, si tu impuesto anual fue $20.000 y adelantaste $30.000 en el año, te devuelven $10.000.</p>",
   "accion": null,
   "pregunta": {
    "t": "¿Qué es el PPM?",
    "o": [
     "Un impuesto nuevo, aparte de los otros",
     "Un adelanto mensual del impuesto a la renta anual",
     "Una multa por atraso",
     "El IVA de las compras"
    ],
    "c": 1,
    "x": "El PPM no es un impuesto extra: es el mismo impuesto a la renta, pagado de a poco durante el año."
   }
  },
  {
   "modulo": "numeros",
   "id": "renta",
   "titulo": "El impuesto a la renta y el F22",
   "resumen": "Una vez al año, sobre lo que ganaste de verdad.",
   "concepto": "<p>Además del IVA, existe el <b>impuesto a la renta</b>: se calcula sobre la <b>ganancia</b> (lo vendido menos los gastos del negocio), no sobre las ventas. Si no ganaste, no pagas.</p><p>Se declara una vez al año, en <b>abril</b>, con el <b>Formulario 22</b> (F22). Es lo que se conoce como <b>Operación Renta</b>. Se declara el año anterior completo: en abril de 2027 se declara lo ganado en 2026.</p><p>Las empresas pagan el impuesto de <b>primera categoría</b>; las personas, el <b>global complementario</b>, que sube por tramos: quien gana poco paga cero. El porcentaje de la empresa depende de su régimen y cambia con las leyes; el SII lo publica cada año.</p>",
   "ejemplo": "<p>Una tienda vendió $12.000.000 en el año y gastó $10.000.000 en mercadería, arriendo y sueldos. Su ganancia fue <b>$2.000.000</b>: sobre eso se calcula el impuesto, no sobre los 12 millones.</p>",
   "accion": null,
   "pregunta": {
    "t": "¿Sobre qué se calcula el impuesto a la renta de una empresa?",
    "o": [
     "Sobre todas las ventas",
     "Sobre la ganancia: ventas menos gastos",
     "Sobre el IVA cobrado",
     "Sobre la UF"
    ],
    "c": 1,
    "x": "La renta es la ganancia. Una empresa que vende mucho pero gasta casi lo mismo paga poco impuesto a la renta."
   }
  },
  {
   "modulo": "empresa",
   "id": "persona-o-empresa",
   "titulo": "¿Persona natural o empresa?",
   "resumen": "Puedes emitir con tu propio RUT o crear uno nuevo.",
   "concepto": "<p>Para vender con boleta no necesitas crear una empresa: una <b>persona natural</b> puede hacer <b>inicio de actividades</b> con su propio RUT y emitir boletas y facturas. Es lo más simple para empezar.</p><p>Una <b>empresa</b> (persona jurídica) es un RUT nuevo, separado del tuyo. Lo que gana y lo que debe es de la empresa, no tuyo: si al negocio le va mal, tu casa y tus ahorros quedan aparte (con límites). Sirve también para tener socios y para vender la empresa algún día.</p><p>Crearla toma un día y es gratis en <b>Empresa en un Día</b> (registroempresasysociedades.cl). Pero después hay que llevar contabilidad y declarar por la empresa, que es más trabajo.</p>",
   "ejemplo": "<p>Una estudiante que hace tortas por encargo puede empezar como <b>persona natural</b> con giro de pastelería. Si el negocio crece y se junta con una amiga, crean una <b>SpA</b> con RUT propio y las dos como socias.</p>",
   "accion": {
    "t": "Mira en Mi empresa cómo se agrega una empresa con su RUT",
    "v": "empresa"
   },
   "pregunta": {
    "t": "¿Qué ventaja principal tiene crear una empresa en vez de usar tu RUT?",
    "o": [
     "Paga menos IVA",
     "No hay que declarar",
     "Separa lo del negocio de lo tuyo y permite tener socios",
     "Es obligatorio para emitir boletas"
    ],
    "c": 2,
    "x": "La empresa es otra persona ante la ley: sus deudas y ganancias son suyas. Para emitir boletas basta ser persona natural con inicio de actividades."
   }
  },
  {
   "modulo": "empresa",
   "id": "tipos-empresa",
   "titulo": "SpA, EIRL, Ltda. y S.A.",
   "resumen": "Las siglas que van después del nombre de una empresa.",
   "concepto": "<p><b>EIRL</b> (Empresa Individual de Responsabilidad Limitada): una sola persona, sin socios. Simple, pero no se pueden sumar socios después.</p><p><b>SpA</b> (Sociedad por Acciones): la más usada hoy para emprender. Puede tener uno o varios dueños (accionistas), es fácil sumar o cambiar socios y se crea en Empresa en un Día.</p><p><b>Ltda.</b> (Sociedad de Responsabilidad Limitada): dos o más socios, cada uno responde solo por lo que aportó. Cambiar un socio exige modificar la sociedad, por eso hoy se prefiere la SpA.</p><p><b>S.A.</b> (Sociedad Anónima): para empresas grandes, con directorio y muchas reglas. No es para empezar.</p>",
   "ejemplo": "<p>Dos amigos abren una cafetería: crean <b>CAFÉ EJEMPLO SpA</b>, 50 % cada uno. Si más adelante entra un tercer socio, se le venden acciones y listo. Con una Ltda. habrían tenido que ir al notario a modificar la sociedad.</p>",
   "accion": null,
   "pregunta": {
    "t": "Quieres empezar sola, pero quizás sumar un socio el próximo año. ¿Qué te conviene?",
    "o": [
     "Una S.A.",
     "Una EIRL",
     "Una SpA",
     "No se puede empezar sola"
    ],
    "c": 2,
    "x": "La SpA puede tener un solo accionista y sumar más después. La EIRL no admite socios, y la S.A. es para empresas grandes."
   }
  },
  {
   "modulo": "empresa",
   "id": "regimenes",
   "titulo": "Pro-PYME y los regímenes",
   "resumen": "El \"plan\" de impuestos que tiene tu empresa.",
   "concepto": "<p>Cada empresa está en un <b>régimen tributario</b>: el conjunto de reglas con que calcula su impuesto a la renta. Se elige al iniciar actividades y se puede cambiar.</p><p>Para empresas chicas existe el <b>régimen Pro-PYME</b>, con reglas simplificadas. Tiene dos versiones: <b>Pro-PYME General</b> (la empresa paga su impuesto y los dueños pagan después por lo que retiran) y <b>Pro-PYME Transparente</b> (la empresa no paga impuesto propio: la ganancia se reparte y cada dueño la declara como suya).</p><p>Las empresas grandes están en el <b>régimen general</b>, con contabilidad completa. Qué régimen conviene depende de cuánto se gana y cuánto se retira; es una buena pregunta para un contador.</p>",
   "ejemplo": "<p>Una SpA de una sola dueña que retira toda la ganancia suele estar cómoda en <b>Pro-PYME Transparente</b>: declara una vez, como persona. Si quiere dejar la ganancia dentro de la empresa para reinvertir, le conviene más <b>Pro-PYME General</b>.</p>",
   "accion": null,
   "pregunta": {
    "t": "¿Qué es un régimen tributario?",
    "o": [
     "El nombre del contador",
     "Las reglas con que una empresa calcula su impuesto a la renta",
     "El porcentaje del IVA",
     "Una multa del SII"
    ],
    "c": 1,
    "x": "El régimen define cómo se calcula el impuesto a la renta. Pro-PYME es el de las empresas chicas; el IVA es igual para todos."
   }
  },
  {
   "modulo": "empresa",
   "id": "inicio-actividades",
   "titulo": "Inicio de actividades y giro",
   "resumen": "Avisarle al SII que empiezas, y a qué te vas a dedicar.",
   "concepto": "<p>El <b>inicio de actividades</b> es el trámite con que le dices al SII \"empecé a trabajar\". Se hace en sii.cl y es gratis. Desde ese momento puedes emitir documentos y tienes la obligación de declarar.</p><p>Hay que hacerlo dentro de los <b>dos meses</b> siguientes a la primera venta. Antes de eso, no deberías estar vendiendo.</p><p>Al hacerlo eliges tu <b>giro</b>: a qué te dedicas. Cada giro tiene un <b>código de actividad</b> de seis cifras. El código define si tus ventas son afectas o exentas de IVA y si puedes emitir boletas, facturas o ambas. Se pueden tener varios giros.</p>",
   "ejemplo": "<p>\"Venta al por menor de alimentos en almacenes\" es un giro afecto a IVA: emites boletas con IVA. \"Enseñanza de idiomas\" es un giro exento: emites boletas exentas. La app pide ese código en Mi empresa porque va impreso en cada documento.</p>",
   "accion": {
    "t": "Escribe el código de actividad en los datos de tu empresa",
    "v": "empresa"
   },
   "pregunta": {
    "t": "¿Cuándo debes hacer el inicio de actividades?",
    "o": [
     "Cuando la empresa gane su primer millón",
     "Dentro de los dos meses desde que empiezas a vender",
     "Solo si tienes empleados",
     "Nunca, si eres persona natural"
    ],
    "c": 1,
    "x": "El plazo es de dos meses desde que empiezas. Vale para personas naturales y para empresas."
   }
  },
  {
   "modulo": "empresa",
   "id": "claves",
   "titulo": "Clave tributaria y certificado digital",
   "resumen": "Dos llaves distintas, para dos cosas distintas.",
   "concepto": "<p>La <b>clave tributaria</b> es la contraseña para entrar a sii.cl. Con ella se declara, se ven documentos y se usa el sistema gratuito del SII. La da el SII y es de la persona (o de la empresa). Si alguien la tiene, puede hacer todo lo anterior en tu nombre: cuídala como una clave del banco.</p><p>El <b>certificado digital</b> es otra cosa: un archivo (.p12 o .pfx) que <b>firma</b> documentos electrónicos, como una firma de puño y letra pero imposible de imitar. Se compra a una empresa autorizada, dura uno a tres años y tiene su propia contraseña. Es de una persona, no de la empresa; la empresa autoriza a esa persona.</p><p>En Faro, el certificado se guarda cifrado y se abre con tu <b>PIN</b>. La clave tributaria solo se pide cuando hace falta.</p>",
   "ejemplo": "<p>Para emitir una factura con tu propio sistema, la app <b>firma</b> el documento con el certificado. Para pedir folios al SII o usar su sistema gratuito, entra con la <b>clave tributaria</b>. Son dos llaves y las dos se cuidan.</p>",
   "accion": {
    "t": "Carga tu certificado en Mi empresa (o mira cómo se hace)",
    "v": "empresa"
   },
   "pregunta": {
    "t": "¿Para qué sirve el certificado digital?",
    "o": [
     "Para entrar a sii.cl",
     "Para firmar documentos electrónicos",
     "Para pagar el IVA",
     "Para crear la empresa"
    ],
    "c": 1,
    "x": "El certificado firma. Para entrar a sii.cl se usa la clave tributaria. Son llaves distintas con contraseñas distintas."
   }
  },
  {
   "modulo": "fechas",
   "id": "calendario",
   "titulo": "El calendario tributario",
   "resumen": "Qué se hace cada mes y qué se hace cada año.",
   "concepto": "<p><b>Cada día</b>: emites tus boletas y facturas. Si emites boletas electrónicas, al final del día el SII recibe un <b>resumen de ventas diarias</b>; la app lo manda sola.</p><p><b>Cada mes</b>: el <b>F29</b> con el IVA y el PPM, hasta el día 12 del mes siguiente (día 20 por internet con pago, para quien emite electrónicamente).</p><p><b>Cada año</b>: en <b>abril</b>, el <b>F22</b> con el impuesto a la renta del año anterior (Operación Renta). Las empresas además presentan en marzo <b>declaraciones juradas</b> con información de sueldos, retiros y otros datos.</p><p><b>Una vez</b>: el inicio de actividades al empezar, y el <b>término de giro</b> si cierras.</p>",
   "ejemplo": "<p>Octubre: vendes todos los días y la app envía los resúmenes. 12 (o 20) de noviembre: F29 de octubre. Abril del año siguiente: F22 con todo el año. Si te lo anotas en el calendario del teléfono, no se te pasa.</p>",
   "accion": null,
   "pregunta": {
    "t": "¿Cuándo se declara el impuesto a la renta del año?",
    "o": [
     "Cada mes, en el F29",
     "En abril del año siguiente, en el F22",
     "El 31 de diciembre",
     "Cuando el SII te llama"
    ],
    "c": 1,
    "x": "La renta se declara una vez al año, en abril, por el año anterior completo. Lo mensual es el F29."
   }
  },
  {
   "modulo": "fechas",
   "id": "honorarios",
   "titulo": "Boletas de honorarios y la retención",
   "resumen": "Para quien trabaja por su cuenta sin vender productos.",
   "concepto": "<p>Un profesional independiente (diseñador, profesor, fotógrafo) no emite boletas de venta: emite <b>boletas de honorarios</b>, en sii.cl, sin IVA.</p><p>De cada boleta se <b>retiene</b> un porcentaje como adelanto del impuesto a la renta: si el cliente es empresa, la empresa lo retiene y lo paga al SII; si es una persona, lo pagas tú en el F29. Ese porcentaje sube un poco cada año; en 2026 ronda el <b>15 %</b>. Parte de esa retención financia tus cotizaciones de salud y pensión.</p><p>En abril, en el F22, se calcula tu impuesto real del año y se descuenta lo retenido. Muchas personas reciben <b>devolución</b>.</p>",
   "ejemplo": "<p>Haces un diseño por $100.000 para una empresa. Emites boleta de honorarios por $100.000; la empresa te paga unos $85.000 y le entrega el resto al SII como retención a tu nombre. En abril se ajusta.</p>",
   "accion": null,
   "pregunta": {
    "t": "¿Qué diferencia tiene una boleta de honorarios con una boleta de venta?",
    "o": [
     "Ninguna",
     "No lleva IVA y se le retiene un porcentaje para el impuesto a la renta",
     "Lleva el doble de IVA",
     "Solo la emiten empresas"
    ],
    "c": 1,
    "x": "Los honorarios no llevan IVA, pero sí retención: un adelanto del impuesto anual que después se ajusta en abril."
   }
  },
  {
   "modulo": "fechas",
   "id": "multas",
   "titulo": "Si te atrasas",
   "resumen": "Qué pasa cuando una declaración llega tarde.",
   "concepto": "<p>Declarar fuera de plazo tiene <b>multa</b> (un porcentaje del impuesto, con un mínimo en UTM) e <b>intereses</b> por cada mes de atraso. Si el F29 era sin movimiento, igual hay multa por no presentarlo, aunque más baja.</p><p>Lo peor no es atrasarse, es <b>no hacer nada</b>: el SII manda avisos, y si nadie responde puede bloquear la emisión de documentos. Un F29 atrasado se presenta igual, cuanto antes, y el propio sitio calcula la multa.</p><p>También hay multas por emitir mal: vender sin boleta, o usar folios que no te pertenecen. Por eso la app te hace revisar antes de emitir y cuida los folios.</p>",
   "ejemplo": "<p>Se te pasó el F29 de octubre y lo presentas el 5 de diciembre: pagas el IVA de octubre más una multa pequeña e intereses de un mes. Molesto, pero se arregla. Dejarlo seis meses sin presentar es un problema mucho mayor.</p>",
   "accion": null,
   "pregunta": {
    "t": "Se te pasó la fecha del F29. ¿Qué conviene hacer?",
    "o": [
     "Esperar a que el SII avise",
     "Presentarlo igual lo antes posible, aunque tenga multa",
     "Saltarse ese mes y seguir con el siguiente",
     "Cerrar la empresa"
    ],
    "c": 1,
    "x": "Un atraso corto cuesta poco; un F29 que nunca se presenta cuesta mucho más. Se presenta igual, cuanto antes."
   }
  },
  {
   "modulo": "documentos",
   "id": "folio",
   "titulo": "El folio y el timbre",
   "resumen": "Cada documento tiene un número único que el SII autorizó antes.",
   "concepto": "<p>El <b>folio</b> es el número del documento: Boleta N° 1, N° 2, N° 3… Nunca se repite y nunca se salta. Por él, el SII sabe cuántos documentos emitiste.</p><p>Los folios no los inventas tú: los <b>pide al SII</b> tu sistema, en rangos (por ejemplo, del 1 al 50). Ese permiso es un archivo llamado <b>CAF</b>. Con él, tu sistema le pone a cada documento un <b>timbre electrónico</b> (el código de barras cuadrado que ves en las boletas).</p><p>Un folio usado no vuelve: si te equivocas, no se borra, se corrige con otro documento. Y pedir folios que no vas a usar hace que el SII te frene: se piden de a poco.</p>",
   "ejemplo": "<p>Pides 5 folios de boleta: el SII te autoriza del 1 al 5. Emites tres boletas (1, 2 y 3). Te quedan dos. Cuando se acaban, pides más; el siguiente rango empieza en 6.</p>",
   "accion": {
    "t": "Mira los folios de la empresa en Mi empresa",
    "v": "empresa"
   },
   "pregunta": {
    "t": "Te equivocaste en la boleta N° 7. ¿Qué pasa con ese folio?",
    "o": [
     "Se borra y la siguiente vuelve a ser la 7",
     "Se corrige con una nota de crédito; la 7 ya está usada",
     "Se le pide al SII que lo devuelva",
     "Se repite la 7 con los datos correctos"
    ],
    "c": 1,
    "x": "Los folios no se borran ni se reutilizan. El error se corrige con una nota de crédito, que es otro documento con su propio folio."
   }
  },
  {
   "modulo": "documentos",
   "id": "notas",
   "titulo": "Nota de crédito y nota de débito",
   "resumen": "Cómo se corrige un documento sin borrarlo.",
   "concepto": "<p>Nada emitido se borra. Si una boleta o factura salió mal, se emite otro documento que la corrige:</p><p>La <b>nota de crédito</b> <b>resta</b>: anula un documento completo o rebaja parte del monto (un descuento, una devolución). Deja el IVA cobrado de más a tu favor.</p><p>La <b>nota de débito</b> <b>suma</b>: agrega un cobro que faltó (un flete que no pusiste) o deja sin efecto una nota de crédito que se emitió por error.</p><p>Cada nota dice a qué documento se refiere (tipo, folio y fecha). Así el SII entiende la historia completa.</p>",
   "ejemplo": "<p>Emitiste la factura N° 12 por $100.000 + IVA y el cliente devolvió la mitad. Emites una <b>nota de crédito</b> por $50.000 + IVA que refiere a la factura 12. Si después descubres que faltó cobrar $5.000 de despacho, emites una <b>nota de débito</b> por ese monto.</p>",
   "accion": {
    "t": "Anula una boleta de práctica desde Documentos y mira la nota de crédito",
    "v": "documentos"
   },
   "pregunta": {
    "t": "Cobraste de menos en una boleta. ¿Con qué documento lo arreglas?",
    "o": [
     "Con una nota de crédito",
     "Con una nota de débito",
     "Borrando la boleta",
     "Con otra boleta por la diferencia"
    ],
    "c": 1,
    "x": "La nota de débito suma lo que faltó y refiere a la boleta original. La nota de crédito es para restar."
   }
  },
  {
   "modulo": "documentos",
   "id": "rcv",
   "titulo": "El Registro de Compras y Ventas",
   "resumen": "La libreta del SII donde queda todo lo que emitiste y recibiste.",
   "concepto": "<p>Cada documento electrónico que emites y cada factura que te emiten a ti llegan al SII. Él los ordena en el <b>Registro de Compras y Ventas</b> (RCV): tu libreta oficial del mes.</p><p>De ahí sale la <b>propuesta de F29</b>: el SII suma el IVA de tus ventas y el de tus compras y te lo muestra listo. Tu trabajo es revisar que esté todo y que no falte ni sobre nada.</p><p>Si recibiste una factura que no corresponde (alguien te facturó por error), tienes ocho días para <b>reclamarla</b> en el SII; si no, se da por aceptada y entra a tu registro.</p>",
   "ejemplo": "<p>En \"Mi mes\" la app te muestra el mismo cálculo que hace el SII con tus documentos: ventas, compras, débito, crédito y la diferencia. Si los números no coinciden con la propuesta del SII, es que falta o sobra un documento.</p>",
   "accion": {
    "t": "Compara tu mes con lo que el SII propone",
    "v": "documentos?tab=mes"
   },
   "pregunta": {
    "t": "¿De dónde saca el SII la propuesta de tu F29?",
    "o": [
     "De lo que tú le escribes cada mes",
     "Del Registro de Compras y Ventas, armado con tus documentos electrónicos",
     "De tu cuenta bancaria",
     "De la UF"
    ],
    "c": 1,
    "x": "El SII ya tiene tus documentos electrónicos. Con ellos arma el registro y la propuesta; tú la revisas."
   }
  },
  {
   "modulo": "documentos",
   "id": "gratuito-propio",
   "titulo": "Sistema gratuito o motor propio",
   "resumen": "Dos formas de emitir; cuál conviene a cada uno.",
   "concepto": "<p>El SII tiene un <b>sistema gratuito</b> para emitir facturas y boletas desde su sitio, con la clave tributaria. Sirve para empezar y para quien emite pocos documentos. Faro puede operarlo por ti y guardarte los PDF.</p><p>Un <b>motor propio</b> (como el de Faro) emite desde tu computador: pide folios, firma con tu certificado y envía al SII. Es para quien emite mucho, quiere integrarlo con su caja o su sistema, o quiere ser dueño de sus documentos. Antes de usarlo en serio hay que pasar la <b>certificación</b>: un set de pruebas que el SII revisa.</p><p>Las dos formas son válidas y una empresa puede partir con el gratuito y pasar al propio después. Lo que no cambia es lo que aprendiste: IVA, folios, F29.</p>",
   "ejemplo": "<p>Una pastelería que vende por encargo diez veces al mes está bien con el sistema gratuito. Un minimarket que emite doscientas boletas al día necesita un motor propio conectado a su caja.</p>",
   "accion": {
    "t": "Recorre las etapas 4 y 5 del camino, más abajo en Aprender",
    "v": "aprender"
   },
   "pregunta": {
    "t": "¿Qué hace falta antes de emitir documentos reales con un motor propio?",
    "o": [
     "Nada: se instala y se emite",
     "Pasar la certificación del SII en su ambiente de pruebas",
     "Pagar una licencia al SII",
     "Tener más de 10 empleados"
    ],
    "c": 1,
    "x": "El SII exige certificar el software antes de usarlo en producción. Por eso la app tiene un ambiente de pruebas (amarillo) separado del real (rojo)."
   }
  }
 ]
};
