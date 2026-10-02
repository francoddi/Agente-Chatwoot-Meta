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

## Pendientes al cierre de esta sesión (02/10/2026)

- **Saldo de OpenRouter bajo** (~$8 USD la última vez que se chequeó) — cargar más antes de que
  se agote y los bots se queden sin poder responder.
- Confirmar que Bot 3 volvió a recibir mensajes normalmente después de arreglar la verificación.
- Bot 4 y Bot 5: esperar a que Meta permita crear el Usuario del Sistema en cada Business
  Portfolio nuevo (problema de antigüedad de cuenta, no algo que se pueda apurar).
- Precios actualizados el 01-02/10/2026 (Movistar y Personal Consumidor Final ahora comparten
  tabla, 70% off, sin plan de 2GB; Línea Nueva 80% off; Empresa Movistar 70%/Personal 60%) — ya
  probados en vivo y desplegados en Bot 1/2/3.
