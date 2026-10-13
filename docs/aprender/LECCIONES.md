# Mini academia: las lecciones

> Generado desde `app/frontend/dist/academia.js` con `tools/revisar_academia.py --md`. No se edita a mano:
> se edita `tools/academia_datos.py` y se vuelve a generar. Mismo texto que ve el alumno en la app.

## 1. Lo básico

Qué es un impuesto, quién es el SII y por qué una boleta dice 1.190 y no 1.000.

### ¿Qué es un impuesto?

*Plata que todos aportan para pagar lo que es de todos.*

Un impuesto es una parte de lo que ganas o gastas que va al Estado. Con esa plata se pagan colegios, hospitales, calles, carabineros, pensiones. No es un castigo ni una multa: es la cuota de cada uno para lo que usamos en común.

Hay impuestos de muchos tipos. En este curso importan dos: el IVA, que se paga cada vez que se compra algo, y el impuesto a la renta, que se paga una vez al año sobre lo que se ganó.

Quien tiene un negocio no solo paga impuestos: también recauda, es decir, cobra el IVA a sus clientes y se lo entrega al Estado. Por eso existen las boletas y las facturas: son la prueba de cuánto se cobró.

**Un ejemplo.** Compras un cuaderno a $1.190. De esos pesos, $1.000 son del negocio y $190 son IVA: la librería los cobra, pero no son suyos; a fin de mes se los pasa al Estado.

**Pregunta.** ¿Para qué sirven los impuestos?

- Para castigar a quien gana mucho
- **Para pagar lo que usamos todos: colegios, hospitales, calles**
- Para que el SII tenga trabajo
- Para que los negocios ganen más

*Con los impuestos se financia lo que es de todos. Quien vende los cobra y los entrega; no se los queda.*

### El SII y el RUT

*El SII es la oficina de los impuestos; el RUT es tu número.*

El SII (Servicio de Impuestos Internos) es la oficina del Estado que lleva la cuenta de los impuestos: sabe qué vendiste, qué compraste y cuánto debes. Todo lo que emites se lo informa a él.

El RUT (Rol Único Tributario) es el número con que el SII te reconoce. Las personas tienen uno (es el mismo del carnet) y las empresas tienen otro, propio, que empieza con 76 o 77. En cada boleta y factura va el RUT de quien vende, y en la factura también el de quien compra.

Para entrar al SII por internet se usa la clave tributaria, una contraseña que te da el propio SII. Con ella se declara, se piden folios y se ven los documentos.

**Un ejemplo.** Un RUT se escribe con puntos y un guion: 12.345.678-5. El último carácter es el dígito verificador, que puede ser un número o una K; sirve para detectar errores de tipeo. La app lo revisa sola.

**Hazlo en la app:** Escribe un RUT en la app y mira cómo lo valida (`#cobrar`).

**Pregunta.** ¿Qué es el RUT de una empresa?

- El RUT del dueño
- **Un número propio de la empresa, distinto al de las personas**
- El número de la boleta
- La clave para entrar al SII

*La empresa es otra persona ante la ley y tiene su propio RUT. El dueño sigue teniendo el suyo.*

### El IVA

*El 19 % que va al Estado cada vez que se vende algo.*

El IVA es el Impuesto al Valor Agregado. En Chile es el 19 % y se suma al precio de casi todo lo que se compra: comida, ropa, servicios, entradas.

Lo paga quien compra. El negocio solo lo recauda: lo cobra en la boleta y a fin de mes se lo entrega al SII. Por eso un negocio nunca debe pensar que el IVA es ganancia suya.

Para calcularlo: el precio sin IVA se llama neto; el IVA es el 19 % del neto; la suma es el total. Si solo conoces el total, el neto se obtiene dividiendo por 1,19.

**Un ejemplo.** Un café cuesta $1.000 neto. IVA: 1.000 × 0,19 = $190. Total: $1.190. Al revés: si la boleta dice $2.380, el neto es 2.380 ÷ 1,19 = $2.000 y el IVA $380.

**Hazlo en la app:** Emite una boleta de práctica y mira cómo la app separa neto e IVA (`#cobrar`).

**Pregunta.** Un producto vale $5.000 neto. ¿Cuánto dice el total de la boleta?

- $5.000
- $5.190
- **$5.950**
- $6.900

*IVA: 5.000 × 0,19 = 950. Total: 5.000 + 950 = 5.950. El error común es sumar 19 pesos en vez del 19 %.*

### Boleta o factura

*La boleta es para personas; la factura, para empresas.*

Una boleta se le da a una persona que compra para sí misma. No lleva su nombre ni su RUT. Es el documento del almacén, el café, la peluquería.

Una factura se le da a otra empresa (o a alguien que compra para su negocio). Lleva el RUT y el nombre del cliente y detalla el IVA, porque a él le sirve para descontarlo de lo que debe pagar.

Los dos documentos informan la venta al SII. La diferencia es para quién son y qué puede hacer el cliente con ellos.

**Un ejemplo.** Un restaurante le compra café a una tostaduría por $100.000 + IVA. Pide factura: así los $19.000 de IVA que pagó se descuentan de los que él cobró a sus clientes ese mes. Si fuera una persona comprando café para su casa, sería boleta.

**Hazlo en la app:** Emite una factura de práctica a CLIENTE DEMO SPA (`#cobrar`).

**Pregunta.** ¿Quién puede descontar el IVA de una compra?

- Cualquiera que guarde la boleta
- **Solo quien recibió una factura a su RUT de empresa**
- Nadie: el IVA no se descuenta
- Solo el SII

*La factura va a nombre de la empresa que compra, y ese IVA se resta del IVA que ella cobró. Con boleta no se puede.*

### Con IVA o sin IVA

*Algunas cosas no llevan IVA: son exentas.*

No todo lleva IVA. Son exentos, entre otros, la educación, la salud, los arriendos de casas sin muebles, el transporte de pasajeros y algunos servicios profesionales. Para eso existen la factura exenta y la boleta exenta.

Lo que sí lleva IVA se llama afecto. Si vendes algo afecto y lo emites como exento, estás cobrando de menos al Estado; si vendes algo exento con IVA, estás cobrando de más a tu cliente. Las dos cosas traen problemas.

Qué es afecto y qué es exento depende de la actividad que declaraste al SII (el giro). Si tienes dudas, el SII lo responde por escrito.

**Un ejemplo.** Un profesor particular cobra $20.000 por una clase. Como la educación es exenta, la boleta dice $20.000, IVA $0, total $20.000. Un vendedor de cuadernos, en cambio, cobra $20.000 + $3.800 de IVA.

**Pregunta.** Una clase de guitarra cuesta $15.000. ¿Cuánto IVA lleva la boleta?

- $2.850
- $1.500
- **$0, porque la educación es exenta**
- Depende del profesor

*La educación es exenta de IVA: la boleta va por $15.000 sin impuesto. No es una decisión del vendedor, es la ley.*

### Neto, IVA y total

*Los tres números que aparecen en todo documento.*

Cualquier boleta o factura tiene tres números al final: el neto (lo que vale lo vendido), el IVA (el 19 % del neto) y el total (lo que paga el cliente). Si el documento es exento, el IVA es cero y el neto se llama exento.

Cuando pones un precio al público, normalmente lo piensas con IVA incluido: el cliente ve $1.190. La app te deja escribir ese precio y calcula sola el neto y el IVA hacia atrás.

Para una factura entre empresas, lo normal es hablar en neto ("$100.000 más IVA"), porque a la otra empresa el IVA le da lo mismo: lo descuenta.

**Un ejemplo.** Vendes tres poleras a $9.990 cada una, IVA incluido. Total: $29.970. Neto: 29.970 ÷ 1,19 = $25.185. IVA: $4.785. Los centavos se redondean, y la app lo hace igual que el SII.

**Hazlo en la app:** Escribe 11900 con IVA incluido en Emitir y mira los tres números (`#cobrar`).

**Pregunta.** Una boleta dice total $11.900. ¿Cuál es el neto?

- $9.639
- **$10.000**
- $11.900
- $14.161

*Neto = total ÷ 1,19 = 11.900 ÷ 1,19 = 10.000. El IVA es la diferencia: 1.900.*

## 2. Los números del mes

UF, UTM, lo que cobras y lo que pagas de IVA, el F29 y el impuesto a la renta.

### UF y UTM

*Dos "monedas" que suben con la inflación, para que los montos no pierdan valor.*

Los precios suben con el tiempo (eso es la inflación). Para que un contrato de hoy valga lo mismo en dos años, Chile usa unidades que se reajustan solas.

La UF (Unidad de Fomento) cambia todos los días siguiendo la inflación. Se usa en arriendos, créditos, seguros y planes de salud. Hoy una UF vale alrededor de $41.000, y mañana unos pesos más.

La UTM (Unidad Tributaria Mensual) cambia una vez al mes. La usa el SII para multas, tramos de impuestos y topes: por ejemplo, "una multa de 1 UTM". Vale alrededor de $70.000.

**Un ejemplo.** Un arriendo de 10 UF se paga en pesos al valor de la UF del día de pago: si la UF está a $41.152,13, son $411.521. El año que viene serán más pesos, pero las mismas 10 UF.

**Hazlo en la app:** Mira la UF y la UTM de hoy en Valores (`#valores`).

**Pregunta.** ¿Cuál cambia todos los días?

- La UTM
- **La UF**
- Las dos
- Ninguna: cambian una vez al año

*La UF se reajusta a diario; la UTM, una vez al mes. Las dos siguen la inflación.*

### Lo que cobras y lo que pagas

*El IVA de tus ventas menos el IVA de tus compras.*

Todo el IVA que cobraste en tus boletas y facturas del mes se llama débito fiscal: es lo que le debes al Estado.

Todo el IVA que pagaste en las facturas de tus compras para el negocio se llama crédito fiscal: es lo que el Estado te reconoce a favor. Solo cuenta si tienes factura a tu RUT; con boletas no.

A fin de mes se restan: débito − crédito = lo que pagas. Si el crédito es mayor (compraste más de lo que vendiste), el saldo queda a tu favor para el mes siguiente; se llama remanente.

**Un ejemplo.** En octubre vendiste $500.000 neto (cobraste $95.000 de IVA) y compraste mercadería con factura por $300.000 neto (pagaste $57.000 de IVA). Pagas 95.000 − 57.000 = $38.000.

**Hazlo en la app:** Mira el mes de la empresa de práctica: débito, crédito y diferencia (`#documentos?tab=mes`).

**Pregunta.** Cobraste $19.000 de IVA y pagaste $10.000 en facturas de compras. ¿Cuánto declaras?

- $29.000
- $19.000
- **$9.000**
- $10.000

*Débito 19.000 menos crédito 10.000 = 9.000. Solo se paga la diferencia.*

### El F29, la declaración del mes

*Una vez al mes le cuentas al SII cuánto vendiste y pagas el IVA.*

El Formulario 29 (F29) es la declaración mensual. Se llena en sii.cl con lo vendido, lo comprado y el IVA de cada lado, y se paga la diferencia. El SII ya tiene casi todo (lo sabe por tus documentos electrónicos), así que te muestra una propuesta para revisar.

Se declara aunque no hayas vendido nada: en ese caso se presenta "sin movimiento", en cero. Olvidarlo tiene multa.

El plazo es el día 12 del mes siguiente. Quien emite documentos electrónicos y declara por internet con pago tiene hasta el día 20.

**Un ejemplo.** Las ventas de octubre se declaran en el F29 de noviembre: hasta el 12 (o el 20 por internet). Ahí va el IVA cobrado en octubre menos el IVA pagado en octubre.

**Hazlo en la app:** Mira lo que la app prepara para el F29 en "Mi mes" (`#documentos?tab=mes`).

**Pregunta.** No vendiste nada este mes. ¿Qué haces con el F29?

- Nada: sin ventas no hay declaración
- **Lo presento igual, sin movimiento**
- Espero a juntar varios meses
- Lo presenta el SII por mí

*El F29 se presenta todos los meses, aunque sea en cero. Si no lo haces, hay multa.*

### El PPM, un adelanto

*Cada mes pagas un poquito a cuenta del impuesto del año.*

El impuesto a la renta se paga una vez al año, en abril. Para no llegar a esa fecha con una cuenta gigante, cada mes se adelanta una parte: el PPM (Pago Provisional Mensual).

Es un porcentaje pequeño de las ventas netas del mes (al empezar, por ejemplo, un 0,25 %), y va en el mismo F29 junto con el IVA.

En abril, al calcular el impuesto real del año, los PPM que ya pagaste se descuentan. Si pagaste de más, el SII te devuelve la diferencia.

**Un ejemplo.** Vendiste $1.000.000 neto en el mes y tu PPM es 0,25 %: adelantas $2.500. En abril, si tu impuesto anual fue $20.000 y adelantaste $30.000 en el año, te devuelven $10.000.

**Pregunta.** ¿Qué es el PPM?

- Un impuesto nuevo, aparte de los otros
- **Un adelanto mensual del impuesto a la renta anual**
- Una multa por atraso
- El IVA de las compras

*El PPM no es un impuesto extra: es el mismo impuesto a la renta, pagado de a poco durante el año.*

### El impuesto a la renta y el F22

*Una vez al año, sobre lo que ganaste de verdad.*

Además del IVA, existe el impuesto a la renta: se calcula sobre la ganancia (lo vendido menos los gastos del negocio), no sobre las ventas. Si no ganaste, no pagas.

Se declara una vez al año, en abril, con el Formulario 22 (F22). Es lo que se conoce como Operación Renta. Se declara el año anterior completo: en abril de 2027 se declara lo ganado en 2026.

Las empresas pagan el impuesto de primera categoría; las personas, el global complementario, que sube por tramos: quien gana poco paga cero. El porcentaje de la empresa depende de su régimen y cambia con las leyes; el SII lo publica cada año.

**Un ejemplo.** Una tienda vendió $12.000.000 en el año y gastó $10.000.000 en mercadería, arriendo y sueldos. Su ganancia fue $2.000.000: sobre eso se calcula el impuesto, no sobre los 12 millones.

**Pregunta.** ¿Sobre qué se calcula el impuesto a la renta de una empresa?

- Sobre todas las ventas
- **Sobre la ganancia: ventas menos gastos**
- Sobre el IVA cobrado
- Sobre la UF

*La renta es la ganancia. Una empresa que vende mucho pero gasta casi lo mismo paga poco impuesto a la renta.*

## 3. Tu empresa

Persona natural o empresa, SpA, EIRL, los regímenes y el inicio de actividades.

### ¿Persona natural o empresa?

*Puedes emitir con tu propio RUT o crear uno nuevo.*

Para vender con boleta no necesitas crear una empresa: una persona natural puede hacer inicio de actividades con su propio RUT y emitir boletas y facturas. Es lo más simple para empezar.

Una empresa (persona jurídica) es un RUT nuevo, separado del tuyo. Lo que gana y lo que debe es de la empresa, no tuyo: si al negocio le va mal, tu casa y tus ahorros quedan aparte (con límites). Sirve también para tener socios y para vender la empresa algún día.

Crearla toma un día y es gratis en Empresa en un Día (registroempresasysociedades.cl). Pero después hay que llevar contabilidad y declarar por la empresa, que es más trabajo.

**Un ejemplo.** Una estudiante que hace tortas por encargo puede empezar como persona natural con giro de pastelería. Si el negocio crece y se junta con una amiga, crean una SpA con RUT propio y las dos como socias.

**Hazlo en la app:** Mira en Mi empresa cómo se agrega una empresa con su RUT (`#empresa`).

**Pregunta.** ¿Qué ventaja principal tiene crear una empresa en vez de usar tu RUT?

- Paga menos IVA
- No hay que declarar
- **Separa lo del negocio de lo tuyo y permite tener socios**
- Es obligatorio para emitir boletas

*La empresa es otra persona ante la ley: sus deudas y ganancias son suyas. Para emitir boletas basta ser persona natural con inicio de actividades.*

### SpA, EIRL, Ltda. y S.A.

*Las siglas que van después del nombre de una empresa.*

EIRL (Empresa Individual de Responsabilidad Limitada): una sola persona, sin socios. Simple, pero no se pueden sumar socios después.

SpA (Sociedad por Acciones): la más usada hoy para emprender. Puede tener uno o varios dueños (accionistas), es fácil sumar o cambiar socios y se crea en Empresa en un Día.

Ltda. (Sociedad de Responsabilidad Limitada): dos o más socios, cada uno responde solo por lo que aportó. Cambiar un socio exige modificar la sociedad, por eso hoy se prefiere la SpA.

S.A. (Sociedad Anónima): para empresas grandes, con directorio y muchas reglas. No es para empezar.

**Un ejemplo.** Dos amigos abren una cafetería: crean CAFÉ EJEMPLO SpA, 50 % cada uno. Si más adelante entra un tercer socio, se le venden acciones y listo. Con una Ltda. habrían tenido que ir al notario a modificar la sociedad.

**Pregunta.** Quieres empezar sola, pero quizás sumar un socio el próximo año. ¿Qué te conviene?

- Una S.A.
- Una EIRL
- **Una SpA**
- No se puede empezar sola

*La SpA puede tener un solo accionista y sumar más después. La EIRL no admite socios, y la S.A. es para empresas grandes.*

### Pro-PYME y los regímenes

*El "plan" de impuestos que tiene tu empresa.*

Cada empresa está en un régimen tributario: el conjunto de reglas con que calcula su impuesto a la renta. Se elige al iniciar actividades y se puede cambiar.

Para empresas chicas existe el régimen Pro-PYME, con reglas simplificadas. Tiene dos versiones: Pro-PYME General (la empresa paga su impuesto y los dueños pagan después por lo que retiran) y Pro-PYME Transparente (la empresa no paga impuesto propio: la ganancia se reparte y cada dueño la declara como suya).

Las empresas grandes están en el régimen general, con contabilidad completa. Qué régimen conviene depende de cuánto se gana y cuánto se retira; es una buena pregunta para un contador.

**Un ejemplo.** Una SpA de una sola dueña que retira toda la ganancia suele estar cómoda en Pro-PYME Transparente: declara una vez, como persona. Si quiere dejar la ganancia dentro de la empresa para reinvertir, le conviene más Pro-PYME General.

**Pregunta.** ¿Qué es un régimen tributario?

- El nombre del contador
- **Las reglas con que una empresa calcula su impuesto a la renta**
- El porcentaje del IVA
- Una multa del SII

*El régimen define cómo se calcula el impuesto a la renta. Pro-PYME es el de las empresas chicas; el IVA es igual para todos.*

### Inicio de actividades y giro

*Avisarle al SII que empiezas, y a qué te vas a dedicar.*

El inicio de actividades es el trámite con que le dices al SII "empecé a trabajar". Se hace en sii.cl y es gratis. Desde ese momento puedes emitir documentos y tienes la obligación de declarar.

Hay que hacerlo dentro de los dos meses siguientes a la primera venta. Antes de eso, no deberías estar vendiendo.

Al hacerlo eliges tu giro: a qué te dedicas. Cada giro tiene un código de actividad de seis cifras. El código define si tus ventas son afectas o exentas de IVA y si puedes emitir boletas, facturas o ambas. Se pueden tener varios giros.

**Un ejemplo.** "Venta al por menor de alimentos en almacenes" es un giro afecto a IVA: emites boletas con IVA. "Enseñanza de idiomas" es un giro exento: emites boletas exentas. La app pide ese código en Mi empresa porque va impreso en cada documento.

**Hazlo en la app:** Escribe el código de actividad en los datos de tu empresa (`#empresa`).

**Pregunta.** ¿Cuándo debes hacer el inicio de actividades?

- Cuando la empresa gane su primer millón
- **Dentro de los dos meses desde que empiezas a vender**
- Solo si tienes empleados
- Nunca, si eres persona natural

*El plazo es de dos meses desde que empiezas. Vale para personas naturales y para empresas.*

### Clave tributaria y certificado digital

*Dos llaves distintas, para dos cosas distintas.*

La clave tributaria es la contraseña para entrar a sii.cl. Con ella se declara, se ven documentos y se usa el sistema gratuito del SII. La da el SII y es de la persona (o de la empresa). Si alguien la tiene, puede hacer todo lo anterior en tu nombre: cuídala como una clave del banco.

El certificado digital es otra cosa: un archivo (.p12 o .pfx) que firma documentos electrónicos, como una firma de puño y letra pero imposible de imitar. Se compra a una empresa autorizada, dura uno a tres años y tiene su propia contraseña. Es de una persona, no de la empresa; la empresa autoriza a esa persona.

En Faro, el certificado se guarda cifrado y se abre con tu PIN. La clave tributaria solo se pide cuando hace falta.

**Un ejemplo.** Para emitir una factura con tu propio sistema, la app firma el documento con el certificado. Para pedir folios al SII o usar su sistema gratuito, entra con la clave tributaria. Son dos llaves y las dos se cuidan.

**Hazlo en la app:** Carga tu certificado en Mi empresa (o mira cómo se hace) (`#empresa`).

**Pregunta.** ¿Para qué sirve el certificado digital?

- Para entrar a sii.cl
- **Para firmar documentos electrónicos**
- Para pagar el IVA
- Para crear la empresa

*El certificado firma. Para entrar a sii.cl se usa la clave tributaria. Son llaves distintas con contraseñas distintas.*

## 4. Las fechas

El calendario tributario: qué se declara cada mes, cada año, y qué pasa si te atrasas.

### El calendario tributario

*Qué se hace cada mes y qué se hace cada año.*

Cada día: emites tus boletas y facturas. Si emites boletas electrónicas, al final del día el SII recibe un resumen de ventas diarias; la app lo manda sola.

Cada mes: el F29 con el IVA y el PPM, hasta el día 12 del mes siguiente (día 20 por internet con pago, para quien emite electrónicamente).

Cada año: en abril, el F22 con el impuesto a la renta del año anterior (Operación Renta). Las empresas además presentan en marzo declaraciones juradas con información de sueldos, retiros y otros datos.

Una vez: el inicio de actividades al empezar, y el término de giro si cierras.

**Un ejemplo.** Octubre: vendes todos los días y la app envía los resúmenes. 12 (o 20) de noviembre: F29 de octubre. Abril del año siguiente: F22 con todo el año. Si te lo anotas en el calendario del teléfono, no se te pasa.

**Pregunta.** ¿Cuándo se declara el impuesto a la renta del año?

- Cada mes, en el F29
- **En abril del año siguiente, en el F22**
- El 31 de diciembre
- Cuando el SII te llama

*La renta se declara una vez al año, en abril, por el año anterior completo. Lo mensual es el F29.*

### Boletas de honorarios y la retención

*Para quien trabaja por su cuenta sin vender productos.*

Un profesional independiente (diseñador, profesor, fotógrafo) no emite boletas de venta: emite boletas de honorarios, en sii.cl, sin IVA.

De cada boleta se retiene un porcentaje como adelanto del impuesto a la renta: si el cliente es empresa, la empresa lo retiene y lo paga al SII; si es una persona, lo pagas tú en el F29. Ese porcentaje sube un poco cada año; en 2026 ronda el 15 %. Parte de esa retención financia tus cotizaciones de salud y pensión.

En abril, en el F22, se calcula tu impuesto real del año y se descuenta lo retenido. Muchas personas reciben devolución.

**Un ejemplo.** Haces un diseño por $100.000 para una empresa. Emites boleta de honorarios por $100.000; la empresa te paga unos $85.000 y le entrega el resto al SII como retención a tu nombre. En abril se ajusta.

**Pregunta.** ¿Qué diferencia tiene una boleta de honorarios con una boleta de venta?

- Ninguna
- **No lleva IVA y se le retiene un porcentaje para el impuesto a la renta**
- Lleva el doble de IVA
- Solo la emiten empresas

*Los honorarios no llevan IVA, pero sí retención: un adelanto del impuesto anual que después se ajusta en abril.*

### Si te atrasas

*Qué pasa cuando una declaración llega tarde.*

Declarar fuera de plazo tiene multa (un porcentaje del impuesto, con un mínimo en UTM) e intereses por cada mes de atraso. Si el F29 era sin movimiento, igual hay multa por no presentarlo, aunque más baja.

Lo peor no es atrasarse, es no hacer nada: el SII manda avisos, y si nadie responde puede bloquear la emisión de documentos. Un F29 atrasado se presenta igual, cuanto antes, y el propio sitio calcula la multa.

También hay multas por emitir mal: vender sin boleta, o usar folios que no te pertenecen. Por eso la app te hace revisar antes de emitir y cuida los folios.

**Un ejemplo.** Se te pasó el F29 de octubre y lo presentas el 5 de diciembre: pagas el IVA de octubre más una multa pequeña e intereses de un mes. Molesto, pero se arregla. Dejarlo seis meses sin presentar es un problema mucho mayor.

**Pregunta.** Se te pasó la fecha del F29. ¿Qué conviene hacer?

- Esperar a que el SII avise
- **Presentarlo igual lo antes posible, aunque tenga multa**
- Saltarse ese mes y seguir con el siguiente
- Cerrar la empresa

*Un atraso corto cuesta poco; un F29 que nunca se presenta cuesta mucho más. Se presenta igual, cuanto antes.*

## 5. Los documentos

Folio, timbre, notas de crédito y débito, el registro del SII y las dos formas de emitir.

### El folio y el timbre

*Cada documento tiene un número único que el SII autorizó antes.*

El folio es el número del documento: Boleta N° 1, N° 2, N° 3… Nunca se repite y nunca se salta. Por él, el SII sabe cuántos documentos emitiste.

Los folios no los inventas tú: los pide al SII tu sistema, en rangos (por ejemplo, del 1 al 50). Ese permiso es un archivo llamado CAF. Con él, tu sistema le pone a cada documento un timbre electrónico (el código de barras cuadrado que ves en las boletas).

Un folio usado no vuelve: si te equivocas, no se borra, se corrige con otro documento. Y pedir folios que no vas a usar hace que el SII te frene: se piden de a poco.

**Un ejemplo.** Pides 5 folios de boleta: el SII te autoriza del 1 al 5. Emites tres boletas (1, 2 y 3). Te quedan dos. Cuando se acaban, pides más; el siguiente rango empieza en 6.

**Hazlo en la app:** Mira los folios de la empresa en Mi empresa (`#empresa`).

**Pregunta.** Te equivocaste en la boleta N° 7. ¿Qué pasa con ese folio?

- Se borra y la siguiente vuelve a ser la 7
- **Se corrige con una nota de crédito; la 7 ya está usada**
- Se le pide al SII que lo devuelva
- Se repite la 7 con los datos correctos

*Los folios no se borran ni se reutilizan. El error se corrige con una nota de crédito, que es otro documento con su propio folio.*

### Nota de crédito y nota de débito

*Cómo se corrige un documento sin borrarlo.*

Nada emitido se borra. Si una boleta o factura salió mal, se emite otro documento que la corrige:

La nota de crédito resta: anula un documento completo o rebaja parte del monto (un descuento, una devolución). Deja el IVA cobrado de más a tu favor.

La nota de débito suma: agrega un cobro que faltó (un flete que no pusiste) o deja sin efecto una nota de crédito que se emitió por error.

Cada nota dice a qué documento se refiere (tipo, folio y fecha). Así el SII entiende la historia completa.

**Un ejemplo.** Emitiste la factura N° 12 por $100.000 + IVA y el cliente devolvió la mitad. Emites una nota de crédito por $50.000 + IVA que refiere a la factura 12. Si después descubres que faltó cobrar $5.000 de despacho, emites una nota de débito por ese monto.

**Hazlo en la app:** Anula una boleta de práctica desde Documentos y mira la nota de crédito (`#documentos`).

**Pregunta.** Cobraste de menos en una boleta. ¿Con qué documento lo arreglas?

- Con una nota de crédito
- **Con una nota de débito**
- Borrando la boleta
- Con otra boleta por la diferencia

*La nota de débito suma lo que faltó y refiere a la boleta original. La nota de crédito es para restar.*

### El Registro de Compras y Ventas

*La libreta del SII donde queda todo lo que emitiste y recibiste.*

Cada documento electrónico que emites y cada factura que te emiten a ti llegan al SII. Él los ordena en el Registro de Compras y Ventas (RCV): tu libreta oficial del mes.

De ahí sale la propuesta de F29: el SII suma el IVA de tus ventas y el de tus compras y te lo muestra listo. Tu trabajo es revisar que esté todo y que no falte ni sobre nada.

Si recibiste una factura que no corresponde (alguien te facturó por error), tienes ocho días para reclamarla en el SII; si no, se da por aceptada y entra a tu registro.

**Un ejemplo.** En "Mi mes" la app te muestra el mismo cálculo que hace el SII con tus documentos: ventas, compras, débito, crédito y la diferencia. Si los números no coinciden con la propuesta del SII, es que falta o sobra un documento.

**Hazlo en la app:** Compara tu mes con lo que el SII propone (`#documentos?tab=mes`).

**Pregunta.** ¿De dónde saca el SII la propuesta de tu F29?

- De lo que tú le escribes cada mes
- **Del Registro de Compras y Ventas, armado con tus documentos electrónicos**
- De tu cuenta bancaria
- De la UF

*El SII ya tiene tus documentos electrónicos. Con ellos arma el registro y la propuesta; tú la revisas.*

### Sistema gratuito o motor propio

*Dos formas de emitir; cuál conviene a cada uno.*

El SII tiene un sistema gratuito para emitir facturas y boletas desde su sitio, con la clave tributaria. Sirve para empezar y para quien emite pocos documentos. Faro puede operarlo por ti y guardarte los PDF.

Un motor propio (como el de Faro) emite desde tu computador: pide folios, firma con tu certificado y envía al SII. Es para quien emite mucho, quiere integrarlo con su caja o su sistema, o quiere ser dueño de sus documentos. Antes de usarlo en serio hay que pasar la certificación: un set de pruebas que el SII revisa.

Las dos formas son válidas y una empresa puede partir con el gratuito y pasar al propio después. Lo que no cambia es lo que aprendiste: IVA, folios, F29.

**Un ejemplo.** Una pastelería que vende por encargo diez veces al mes está bien con el sistema gratuito. Un minimarket que emite doscientas boletas al día necesita un motor propio conectado a su caja.

**Hazlo en la app:** Recorre las etapas 4 y 5 del camino, más abajo en Aprender (`#aprender`).

**Pregunta.** ¿Qué hace falta antes de emitir documentos reales con un motor propio?

- Nada: se instala y se emite
- **Pasar la certificación del SII en su ambiente de pruebas**
- Pagar una licencia al SII
- Tener más de 10 empleados

*El SII exige certificar el software antes de usarlo en producción. Por eso la app tiene un ambiente de pruebas (amarillo) separado del real (rojo).*
