# Valentina — Asesora comercial de Claro por WhatsApp (Chatwoot + Meta Cloud + OpenRouter)

Agente en Python/FastAPI que conecta **Chatwoot** con un modelo LLM multimodal vía
**OpenRouter**. El canal de WhatsApp de Chatwoot es la API oficial de Meta (WhatsApp Cloud),
pero es transparente para el bot: este **solo** habla con la API de Chatwoot (recibe webhooks
y responde creando mensajes salientes). Nunca toca la Graph API de Meta ni maneja sus
credenciales — esas viven en el inbox de WhatsApp Cloud dentro de Chatwoot.

Valentina asesora sobre portabilidad a Claro (o línea nueva), muestra precios Particular/Empresa
según corresponda, cierra la venta comercialmente y arma la ficha de datos para que el cliente
la reenvíe a **Camila**, quien pide el DNI y hace el alta/traspaso.

## Qué hace

- Responde mensajes de **texto**, **imágenes** (ej. DNI, facturas, capturas) y **notas de voz**.
- Mantiene **memoria de conversación** trayendo el historial desde la API de Chatwoot.
- Se puede **pausar** por conversación con la etiqueta `bot_off` (atención humana).
- Convierte las notas de voz de WhatsApp (Opus/OGG) a **MP3 con ffmpeg** antes de mandarlas al
  modelo — sin esto, OpenRouter responde 200 OK pero descarta el audio.
- Sigue el guion comercial completo (tablas de precios Particular/Empresa, checklist de datos
  antes del handoff, mensaje sin precio para reenviar a Camila) definido en el `SYSTEM_PROMPT`
  de `main.py`.

## 1. Configura tus credenciales

```powershell
Copy-Item .env.example .env
```

Rellena `CHATWOOT_URL`, `CHATWOOT_API_TOKEN`, `CHATWOOT_ACCOUNT_ID` y `OPENROUTER_API_KEY`.
**No** pongas ahí variables de Meta (token de WhatsApp, Phone Number ID): esas van en el inbox
de Chatwoot.

## 2. Pruébalo en local

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Abre `http://localhost:8000/` → debe responder `{"status":"ok", ...}`.

> Para probar audio en local necesitas **ffmpeg** instalado (en el servidor lo instala el
> Dockerfile). Windows: `winget install Gyan.FFmpeg`.

## 3. Súbelo a GitHub

```powershell
git init
git add .
git commit -m "Agente de IA para WhatsApp (Chatwoot + API oficial de Meta)"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

Verifica con `git status` que `.env` no aparezca antes de commitear.

## 4. Despliega en Easypanel (o cualquier host con Docker)

1. **+ Service → App** → Source **GitHub** → tu repo, rama `main`.
2. Build: **Dockerfile** (se detecta automáticamente; incluye ffmpeg).
3. **Environment:** pega las variables del `.env` (Chatwoot + OpenRouter).
4. **Domains:** dominio con puerto interno **8000**.
5. **Deploy**.

## 5. Conecta el webhook Chatwoot → bot

En Chatwoot → *Configuración → Integraciones → Webhooks*, apunta a:

```
https://tu-dominio.easypanel.host/webhook
```

Suscríbete al evento **Message Created**. (El webhook Meta→Chatwoot ya se configuró al conectar
el inbox de WhatsApp Cloud; son dos webhooks distintos.)

## 6. Pausar el bot manualmente

Crea la etiqueta `bot_off` en Chatwoot y ponla en una conversación para que el bot deje de
responder (atención humana). Quítala para reactivarlo.

## Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| El bot se responde a sí mismo en bucle | No se filtró `message_type` | Solo se procesa `incoming` en `message_created` (ya implementado) |
| El bot saluda en cada mensaje | Sin historial | Ya se trae el historial vía la API de mensajes de Chatwoot |
| Adjuntos no se descargan (302) | `httpx` sin redirects | Ya se usa `follow_redirects=True` |
| Ante un audio dice "veo una imagen" | No se reveló el tipo de medio | Ya se antepone texto explícito ("El cliente envió una NOTA DE VOZ...") |
| El bot dice "no puedo escuchar notas de voz" | Audio sin convertir a mp3, o prompt con salida de emergencia | Ya se convierte con ffmpeg y el prompt no ofrece rendirse |
| `ffmpeg no disponible` en logs | No instalado | Ya está en el `Dockerfile` (`apt-get install ffmpeg`) |
| No llega el mensaje de WhatsApp a Chatwoot | Webhook Meta→Chatwoot mal configurado | Revisar Callback URL / Verify Token / campo `messages` en la app de Meta |
| Dejó de enviar tras 24 h | Token temporal de Meta caducado | Usar token permanente de System User en el inbox de Chatwoot |
| Logs no aparecen en el host | Buffer de salida | Ya está `PYTHONUNBUFFERED=1` en el Dockerfile |

## Cómo depurar audio si algo falla

1. Busca en logs `Audio recibido: content_type=...` y luego `Audio convertido a mp3: ... bytes
   -> ... bytes`. Si la segunda línea no aparece, ffmpeg no corrió.
2. Si el modelo sigue "sin oír", el problema normalmente está en el **prompt** (una salida de
   emergencia tipo "si no puedes oír, pide texto"), no en el modelo.

## Checklist

- [ ] `GET /` responde `{"status":"ok"}`.
- [ ] Responde a **texto** sin re-saludar.
- [ ] Describe **imágenes**.
- [ ] Responde al contenido de **notas de voz**.
- [ ] La etiqueta `bot_off` pausa al bot.
- [ ] `.env` no está en el repo.
- [ ] `PYTHONUNBUFFERED=1` y `ffmpeg` están en el Dockerfile.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
