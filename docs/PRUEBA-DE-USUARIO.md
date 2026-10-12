# Prueba de usuario de la app (interfaz universal, 2026-10-12)

Objetivo fijado en sesión: la app tiene que sentirse moderna y amable, nada corporativa, y la
interfaz no debe ser el obstáculo: "un alumno o un abuelo la usa sin que nadie le explique".

## Lo que ya se validó sin personas (agentes sin contexto mirando capturas)

Método: un agente recibe solo las capturas de pantalla, una persona definida y una tarea, y
responde en primera persona qué pulsaría, qué no entiende y dos notas de 1 a 5. Cada hallazgo
concreto se corrigió y se volvió a pasar.

| persona simulada | ¿lo hace sola? | ¿cómoda, no "de oficina"? | qué se corrigió a partir de ella |
|---|---|---|---|
| alumno de 16 años | 4/5 | 4/5 | "Salir" pausa las pistas, "Mis documentos" en el visor, "Anular este documento", acciones de la fila con aire, línea de UF fuera del dock |
| persona de 72 años, pasada 1 (tema oscuro) | 3/5 | 2/5 | tema claro, "El IVA no es tuyo" bajo los totales, ejemplos "Ej.:", bienvenida sin género |
| pasada 2 | 3/5 | 4/5 | botón "Revisar y emitir" quedaba bajo el dock |
| pasada 3 | 3/5 | 4/5 | seguía asomando por una esquina: botón fijo a la derecha, por encima del dock |
| pasada 4 | 4/5 | 4/5 | la frase del IVA tapada: va antes del botón |

Lo que queda por debajo de 5 en ambos perfiles es vocabulario tributario ("neto", "IVA", "nota
de crédito"), que enseña la etapa 1 de la guía, no un obstáculo de interfaz.

## La prueba que falta: con una persona real

1. Abrir la app (`app-rs/target/release/bundle/macos/Faro.app` o `app/build/bin/Faro.app`;
   las dos llevan la misma interfaz). Si hay datos de práctica anteriores, en Inicio pulsar
   "Empezar de nuevo".
2. Sentar enfrente a alguien que nunca la haya visto (idealmente un alumno de colegio o una
   persona mayor) y decirle solo esto, sin explicar nada más:

   > "Cóbrale 1.190 pesos a alguien por un café, mira cómo quedó el documento, y después anúlalo
   > porque te equivocaste."

3. No ayudar. Anotar: dónde se detiene, qué pregunta en voz alta, qué pulsa por error, cuánto
   tarda en total. Al final preguntar las dos notas de 1 a 5: "¿podrías hacerlo sola o solo, sin
   que nadie te explique?" y "¿te sentiste cómoda o cómodo, o como en un programa de oficina?".
4. Pegar las notas en el chat. Cada traba real se convierte en una corrección concreta, como se
   hizo con las simuladas.

Umbral razonable para dar por cumplido el objetivo: 4/5 en las dos preguntas con al menos una
persona de cada perfil, y la tarea completa sin ayuda.
