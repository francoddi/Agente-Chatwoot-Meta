# Agente Chatwoot Meta — contexto para Claude Code

Bot de ventas por WhatsApp ("Valentina") para Francisco Coddington, agente oficial de Claro
(Celtafone S.A.) en Argentina. Un solo archivo, `main.py` (FastAPI). Recibe webhooks de Chatwoot,
genera respuestas con un LLM vía OpenRouter (Gemini 2.5 Pro), y registra las ventas en Google
Sheets. Francisco no es programador — explicar todo en criollo, sin asumir conocimiento técnico.
Esta sesión puede ser retomada desde otra computadora (Mac) mientras Francisco viaja y no puede
escribirle a la sesión original — este archivo es el handoff completo.

## Arquitectura

- **Chatwoot**: plataforma de mensajería donde llegan los WhatsApp. El bot escucha su webhook
  `/webhook` (evento `message_created`, `message_type: incoming`) y contesta llamando a la API
  de Chatwoot (`send_message`), no a Meta directamente — con una sola excepción: el indicador de
  "escribiendo..." (`_mostrar_escribiendo`) llama directo a la API de Meta, porque Chatwoot no lo
  soporta para canales de WhatsApp Cloud API.
- **OpenRouter**: el LLM. No tiene relación con Meta/WhatsApp, es un servicio aparte. Se comparte
  la misma clave entre TODOS los bots (no genera ningún vínculo de cara a Meta).
- **Google Sheets**: cada venta derivada agrega una fila (`log_to_google_sheets`). Columnas fijas
  por posición — MUY frágil ante cambios manuales en la planilla (ver más abajo). Se comparte la
  MISMA planilla entre todos los bots (pestaña "Hoja 1" = mes en curso; los meses anteriores se
  archivan renombrando "Hoja 1" al nombre del mes y creando una "Hoja 1" nueva vacía).
- **Despliegue**: Easypanel, conectado al repo de GitHub (`francoddi/Agente-Chatwoot-Meta`, rama
  `master`). Cambio de código = commit + push a GitHub + apretar "Redeploy" a mano en Easypanel
  en CADA bot (no es automático, y no se propaga solo entre bots).

## Multi-cuenta: por qué y cómo (lo más importante para entender la sesión)

A fines de septiembre 2026 se bloquearon repetidamente los números de WhatsApp Business del
negocio original (3 bloqueos en ~10 días, incluyendo "airea.health", inhabilitado permanente).
Causa más probable: todo corría bajo la misma cuenta personal de Meta + mismo servidor/Chatwoot
— señal de correlación real que Meta puede ver (mismo dominio de webhook, misma IP de servidor,
mismo método de pago).

**Plan ejecutado**: diversificar en varias cuentas totalmente separadas, cada una con:
- Una persona real DISTINTA (nunca Francisco) creando su propia cuenta de Meta/Facebook, su
  propio Business Portfolio, su propia cuenta publicitaria y Fanpage, desde su propio
  dispositivo — el método de pago de cada cuenta tiene que ser de esa persona, NUNCA la tarjeta
  de Francisco (encontramos evidencia de que eso causó un problema real en una de las cuentas).
- Su propio Chatwoot separado (instalación propia, base de datos propia, dominio de webhook
  propio) — NO hace falta que cada cuenta tenga su propia VPS: "proyecto" en Easypanel es solo
  organización visual, no genera ningún vínculo técnico. Lo que sí importa es que cada Chatwoot
  sea una instalación realmente separada (no la misma base de datos).
- Se reutiliza sin problema entre TODAS las cuentas: este mismo repo de GitHub, la clave de
  OpenRouter, la planilla de Google Sheets, el número de Camila, y la VPS física (decisión
  consciente de Francisco: la señal de IP de servidor compartida se evaluó como la más débil de
  todas, sin evidencia dura de que Meta la use — ver el bloqueo de "Celtabot 3" el 26/09, que
  pasó ANTES de que existiera siquiera la función de "escribiendo...").
- Francisco usa un servicio de proxy/navegador anti-detección ("Lauth") para el trámite de cada
  persona en Meta. **No se asesora en cómo configurarlo** (es evasión de baneo, fuera del scope
  de este proyecto) — pero es una decisión ya tomada por Francisco, no hay que volver a
  cuestionarla ni ofrecerse a ayudar a configurarlo.

**Estado de las cuentas (al 02/10/2026, última sesión):**
- **Celtabot** (proyecto Easypanel `celtabot`): la cuenta ORIGINAL de Francisco. Sin uso activo
  actualmente (números bloqueados). El código ahí está desactualizado (no tiene los cambios de
  precios/checklist del 01-02/10) — no urge actualizarlo mientras no se use.
- **Bot 1** (proyecto Easypanel `agente-1-lth`, app `agente-bot1-lth`): ACTIVA, funcionando bien,
  con tráfico real.
- **Bot 2** (proyecto Easypanel `agente-2-lth`, app `agente-2`): ACTIVA, funcionando bien, menos
  volumen que Bot 1 (recién arrancando con los anuncios).
- **Bot 3** (mismo proyecto `agente-2-lth`, app `agente-3`, Chatwoot separado `chatwoot-3`):
  tuvo un bloqueo de la cuenta de DESARROLLADOR de Meta (no del número, que seguía con calidad
  "Alta") — pantalla "Confirmación de la cuenta requerida" / "actividad inusual", que impidió
  que lleguen webhooks a Chatwoot durante varias horas. Se resolvió activando la verificación en
  dos pasos y corrigiendo el número de teléfono de seguridad de la cuenta (le faltaba el 9). A
  confirmar si ya volvió a recibir mensajes con normalidad.
- **Bot 4 y Bot 5**: en preparación, pero Meta no deja crear el Usuario del Sistema (necesario
  para el token permanente) por falta de antigüedad del Business Portfolio recién creado. No hay
  nada para hacer ahí salvo esperar unos días.

**Nota de seguridad**: en esta sesión se compartieron tokens/contraseñas reales en el chat (a
pedido explícito de Francisco, para poder avanzar rápido). Ese archivo de claves NO se commitea
nunca a git — queda en `.env` (gitignored) o se pasa por chat directo cuando hace falta.

## Formato de números de teléfono argentinos (recurrente, varias veces causó errores)

Para WhatsApp/Meta, un celular argentino en formato internacional completo es:
`54` + `9` + código de área (sin el 0) + número (sin el 15). Ej: `+5492236022567`.
Cuando un formulario de Meta separa "código de país" (+54) del resto, en el campo del número hay
que escribir `9` + código de área + número (ej. `92236022567`). Olvidarse el `9` es la causa más
común de que no lleguen SMS/llamadas de verificación (WhatsApp corrige este detalle solo
internamente, pero los sistemas de SMS genéricos de Meta no, y lo mandan mal si falta).

## Cuidados conocidos (ya causaron incidentes reales)

- **Columnas de Google Sheets por posición fija**: si el equipo inserta/mueve una columna a mano
  en la planilla real, el código sigue escribiendo en las posiciones viejas y corrompe datos en
  silencio (pasó el 26/09/2026). Antes de tocar algo relacionado a Sheets, releer el encabezado
  real (`A1:X1`) y compararlo con `_CAMPO_A_COLUMNA_SHEETS` y el armado de `row` en
  `log_to_google_sheets`.
- **Pegar `GOOGLE_SHEETS_CREDENTIALS_JSON` a mano en Easypanel la corrompe** (pierde caracteres
  al copiar un texto tan largo). Ver memoria `easypanel_env_long_values.md` para el método seguro
  (`Get-Content .env | Where-Object {...} | Set-Clipboard` en PowerShell) y el checklist de
  verificación por SSH (`json.loads(...)`, `_get_sheets_access_token()`, prueba real de
  `log_to_google_sheets` con datos marcados "PRUEBA BORRAR").
- **Nunca mandar mensajes genéricos de disculpa** si falla algo a mitad de una conversación real
  — se probó y se sacó, se sentía como perder la venta. Mejor reintentar o avisar al dueño.
- **El modelo no puede "no responder nada"** por arquitectura actual (`call_openrouter` trata
  cualquier respuesta vacía como error a reintentar) — detectado pero no resuelto.
- **La foto del DNI se pide como ÚLTIMO paso del checklist** (nombre+DNI+número primero, después
  contacto/dirección, recién al final la foto) — no pedirla junto con el DNI de entrada, se
  siente como un bombardeo (cambiado explícitamente el 01/10/2026, revirtiendo un cambio de
  semanas atrás que la pedía temprano).
- **El DNI/CUIT siempre se pide nombrando "del titular de la línea"** explícitamente — puede no
  ser la misma persona que escribe (caso real: alguien gestionando el trámite por su madre). El
  resto de los datos (email, dirección) sí pueden ser de quien escribe.

## Reglas de trabajo

- Probar SIEMPRE contra las APIs reales (Chatwoot, Sheets, OpenRouter) antes de decir que algo
  está listo — nunca alcanza con que compile.
- **Todo cambio de código se aplica a TODOS los bots activos** (a pedido explícito) — después de
  cada commit+push, recordarle a Francisco el Redeploy manual en CADA app de Easypanel (Bot 1,
  Bot 2, Bot 3 por ahora).
- Nunca sobrescribir/borrar datos reales de Sheets o Chatwoot sin inspeccionar antes.
- Ser honesto ante la incertidumbre — separar lo que se puede probar con datos de lo que es
  inferencia o mejor esfuerzo. No inventar certeza técnica.
- No usar el flag `--no-verify` ni saltear hooks salvo pedido explícito.
- El acceso por SSH a la VPS (para diagnósticos con `docker exec`/`docker logs`) lo bloquea el
  propio Claude Code por seguridad — hay que darle los comandos a Francisco para que los corra
  él mismo en PowerShell y pegue el resultado.
- `git push` a veces lo bloquea el clasificador automático sin motivo claro — si pasa, pedirle a
  Francisco que lo corra él mismo en PowerShell (`git push`), funciona igual.

## Sesión del 03/10/2026 (desde la Mac) — qué cambió

- **Precios**: Movistar/Tuenti y Personal Consumidor Final (DNI) usan **70% off**
  (tabla: 4GB $17.997, 7GB $20.460, 10GB $26.010, 30GB $34.680, 50GB $39.882, sin 2GB, +10GB
  de regalo x 6 meses). Empresa y Línea nueva sin cambios. Actualizado el 07/10/2026 para Bot 3.
- **Cliente que ya es de Claro (prepago o abono)**: NO se le vende nada con esa línea (el equipo
  lo rechaza: "YA ES CLIENTE CLARO"). Antes el bot lo trataba como "línea nueva" (caso Hugo
  Orlando Romero). Regla agregada en la sección 0 y 33.3 del prompt + red de seguridad en
  `_registrar_derivacion_completa` (no carga en Sheets fichas con "Compañía actual: Claro...").
- **Ficha corregida = actualiza la fila existente** (`_actualizar_fila_existente`): antes el
  chequeo de duplicados (número, teléfono) descartaba la ficha nueva entera (caso Dolores
  Ortiga → en realidad Margarita de la Cruz Alvarez).
- **Contenido bloqueado por el modelo**: si un cliente manda una imagen que Gemini bloquea
  (PROHIBITED_CONTENT, OpenRouter devuelve 200 con "error" y sin "choices"), `call_openrouter`
  lo detecta sin repetir la misma llamada, pausa la conversación con `bot_off` y avisa al dueño
  una sola vez para revisión humana. Corregido el 09/10/2026.
- **Análisis de conversión (02-03/10)**: Bot 1 y Bot 2 tienen el mismo % de gente que contesta
  el saludo (~75%); Bot 1 lleva más gente a ver precios pero deriva menos. Llegan de anuncios
  distintos (Bot 1: "Quiero pasarme a Claro manteniendo mi número 😀", público Movistar muy
  sensible al precio / jubilados; Bot 2: "Hola, quiero pasarme a Claro aprovechando la promo
  ☺️"). En Bot 1 varias ventas quedan trabadas en el último paso (foto del DNI) y, con el
  seguimiento apagado, nadie se los recuerda. OJO: la foto obligatoria fue decisión explícita
  de Francisco (commit 1c6adef) — no cambiarla sin que él lo pida.

## Sesión del 04/10/2026 — protecciones contra ventas perdidas

- **Fotos invisibles en el historial** (`_map_history`): los mensajes sin texto (foto sola del
  DNI) se descartaban; el bot volvía a pedir fotos ya mandadas o se confundía. Ahora cada
  adjunto queda como nota ("[El cliente envió una imagen]").
- **Nota de "ya derivado"**: la ficha interna no está en el historial; si la conversación tiene
  la etiqueta `ddd`, se le avisa al modelo para que no la regenere (la regeneraba con la fecha
  de nacimiento inventada). `_actualizar_fila_existente` no pisa nombre/DNI/F. nac si es el
  mismo titular (comparación por palabras, sin orden ni tildes).
- **Derivó sin ficha** → se pide la ficha en una segunda llamada interna y se registra; si no
  sale, aviso al dueño (caso Julio César Patiño, recuperado a mano).
- **Objeciones de plata** (sección 56.2): no se paga nada ahora, la primera factura llega un mes
  después de recibir el chip; si el checklist está completo se deriva en el mismo turno (caso
  Irma Pascal, recuperada a mano).
- **Revisor automático de ventas trabadas** (`_recuperacion_ventas_loop`, cada 10 min,
  `RECUPERACION_VENTAS_ENABLED`): conversaciones no derivadas de las últimas 24hs, con datos
  pedidos y fotos recibidas, quietas hace 10+ min → el modelo relee todo con las fotos y, si la
  venta está lista, se registra (F. nac vacía a propósito) y se avisa al dueño. NO le escribe al
  cliente. Probado: recupera Julio e Irma, no recupera casos incompletos ni clientes de Claro.
- Auditoría de las 216 conversaciones de Bot 1/2/3: solo esos 2 casos perdidos, ambos recuperados.
- Bot 3: número +5492236022567 reconectado en la cuenta de WhatsApp NUEVA "Agente"
  (WABA 4383781345169549, phone_number_id 1397482693449770); la WABA vieja 1076862111899245 quedó
  vacía. El PIN de dos pasos lo tiene Francisco (no se commitea).

## Sesión del 04/10/2026 (tarde/noche) — bloqueo Bot 1, advertencia de spam Bot 2

- **Bot 1 (+5492236022573) BLOQUEADO** (WABA banned, motivo "envía spam", calidad en verde hasta
  el final). Francisco lo atribuye a un método de pago repetido; se va a reemplazar por una cuenta
  verificada (mismo Chatwoot/bot de Easypanel, solo cambia el número).
- **Bot 2 recibió advertencia de spam** (no bloqueo); Francisco mandó la revisión y Meta la sacó.
- **Saludo inicial**: lista fija `_SALUDOS_INICIALES` (43 saludos simples escritos a mano: "hola,
  soy valen", "buenas, soy valentina" + pregunta por la compañía), uno al azar; ningún par >80% de
  parecido. Ya NO se presenta como "del equipo de Claro" (a pedido); si preguntan, dice que trabaja
  con Celtafone, agente oficial de Claro. Medido antes: 86% de saludos casi iguales.
- **Espera al azar antes de responder** (`_espera_antes_de_responder`): 0-5 s si la respuesta es
  corta (≤160 caracteres), 10-15 s si es larga, además del tiempo del modelo; se re-muestra
  "escribiendo..." durante la espera.
- Comparación cuenta original (días buenos 08-15/09) vs Bot 1/2: la original mandaba más mensajes
  (incluidos 47 seguimientos/día) y tenía 19% de clientes que no contestaban; Bot 1/2: 26-31%. El
  código no hace nada indebido (no escribe primero, no fuera de 24h, no insiste).
- **Pendientes de política de WhatsApp Business** (no hechos): ofrecer hablar con una persona
  cuando el cliente lo pide (hoy el bot lo niega) y cargar email/web/teléfono en el perfil de
  WhatsApp de cada número (falta que Francisco pase los datos).
- **Prueba de anuncios desde el 05/10**: Bot 2 solo con los anuncios de siempre (sin videos no
  validados), Bot 3 con todos; mismo presupuesto. Comparar conversión por bot y por anuncio.
- Ventas pendientes de contacto el 05/10: Julio César Patiño e Irma Pascal (cargados a mano),
  Ángel (Bot 3, falta foto DNI), Charo Molina (Bot 2, falta foto DNI).

## Cómo acceder a los Chatwoot desde la Mac

- La red de la Mac (DNS del router) NO resuelve los dominios `*.bzovbc.easypanel.host`
  (NXDOMAIN), aunque existen (con DNS de Google resuelven a la IP de la VPS, 13.140.151.112).
  Usar `curl --resolve <host>:443:13.140.151.112 ...` para llegar igual.
- Chatwoot por bot (account_id 1 en todos; los tokens los pasa Francisco por chat, no se commitean):
  Bot 1 `agente-1-lth-chatwoot`, Bot 2 `agente-2-lth-chatwoot`, Bot 3 `agente-2-lth-chatwoot-3`
  (todos `.bzovbc.easypanel.host`).
- El proyecto en la Mac está en `~/Documents/Agente-Chatwoot-Meta` (se movió del Escritorio).
  `git push` funciona: GitHub CLI instalado en `~/.local/bin/gh` y logueado como francoddi.
- El `.env` local apunta al Chatwoot viejo (Celtabot); OpenRouter y Sheets son los compartidos.

## Pendientes al cierre (03/10/2026)

- **Saldo de OpenRouter**: ~71 USD (se cargó el 02/10 tras quedarse sin saldo a la medianoche).
- Bot 3: encendido pero sin tráfico desde el 02/10 (Francisco lo tiene apagado).
- Bot 4 y Bot 5: esperar a que Meta permita crear el Usuario del Sistema (antigüedad del
  Business Portfolio). Bot 4: WABA y Phone Number ID ya existen, falta el token permanente.
- No reintentar ante contenido bloqueado por el modelo (ver arriba).
- Que el bot no saque datos de una foto que no es un DNI (caso Margarita: tomó una selfie como
  frente del DNI e inventó la fecha de nacimiento). Limitación conocida de `_extraer_fotos_dni`.
- Inconsistencias menores del prompt: la sección 2 todavía describe el flujo viejo ("cliente
  reenvía el mensaje → Camila pide DNI"); la sección 17 lista saludos con contenido extra que la
  regla del código prohíbe; el ejemplo de la sección 64 pide datos en otro orden que la 43.
