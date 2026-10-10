# Instagram Story Cron — Manual de Implementación y Guía Futura

> Documento vivo. Describe cómo montar, configurar y extender el pipeline
> **publicación de Stories/Feed en Instagram por API oficial** desde cero, con
> todo lo aprendido durante el setup real (incluidos los escollos y sus
> soluciones). Cualquier implementación futura debería empezar leyendo esto.

---

## 0. Resumen técnico (30 segundos)

- **Qué hace:** toma imágenes predefinidas, las publica como **Stories** (o
  **feed posts**) en una cuenta de **Instagram Business** usando el **Graph API
  oficial de Meta** (Content Publishing API, `media_type=STORIES` / `IMAGE`).
- **Cómo corre:** un cron cada N horas (GitHub Actions o local).
- **Credenciales:** token de usuario de Facebook con permisos de Instagram,
  refrescado a **long-lived (60 días)** en cada ejecución.
- **Estado:** ✅ stories, ✅ feed, ✅ leer comentarios. 🚧 auto-respuesta IA (diseño en §6).

---

## 1. Arquitectura

```
[cron cada 3h]
     │
     ▼
publish_story.py ──► tokens: refresh fb_exchange_token (long-lived 60d)
     │
     ├── pick_image(): rotación determinista por slot de 3h
     │        (media/playlist.json → filename → PUBLIC_BASE_URL/…/file.jpg)
     │
     └── publicación (2 pasos siempre):
          1) POST /{ig-id}/media            (crea contenedor)
          2) GET  /{container-id}?status_code  (espera FINISHED)
          3) POST /{ig-id}/media_publish    (publica)
```

### Estado del proyecto
```
instagram-story-cron/
├── publish_story.py          # pipeline: publica stories/feed, refresca token, lee comentarios
├── get_token.py              # genera token de usuario con permisos (OAuth localhost)
├── .env                      # credenciales (NO versionar)
├── .env.example              # plantilla documentada
├── media/                    # imágenes + playlist.json (orden de rotación)
├── add_image.py              # añadir una foto: recorte 4:5 + playlist + tags (1 comando)
├── products.json             # catálogo: beneficios/CTAs para la IA + links.mercadolibre
│                             # (links = datos intencionales para "share" futuro:
│                             #  auto-respuesta por DM, multi-link en bio, sticker stories)
├── prompts/                  # prompts editables (caption.md, reply.md) — obligatorios
├── .github/workflows/publish-stories.yml   # cron GitHub Actions
└── IMPLEMENTATION_GUIDE.md   # este archivo
```

---

## 2. Setup de cuentas (orden exacto y por qué)

> El orden importa: cada elemento "nace" desde el anterior.

1. **Facebook personal** (el admin de todo). 2FA activado.
2. **Email de marca** (para IG + contacto del app).
3. **Facebook Page** → créala dentro de **Meta Business Suite** usando la opción
   *"Ahorra tiempo con Meta Business Suite"*. Esto crea además el
   **Business Portfolio** del negocio. *(Sino, la Página queda "colgada" y luego
   el API no la ve: síntoma `me/accounts` vacío.)*
4. **Instagram Business** desde la app móvil → tipo de cuenta: **EMPRESA
   (Business)**, NUNCA "Creador" (el API de Stories **solo funciona en
   cuentas Business**). Vincula IG a la **Página** (no al perfil):
   IG app → Centro de cuentas → Cuentas vinculadas → **Página**.
5. **Meta developer app** (`developers.facebook.com`) → **TIPO: EMPRESA
   (Business)** ❗ — ver §3.1 (el tipo equivocado rompe los permisos).

**Credenciales reales de esta implementación (referencia):**
| Entidad | Valor |
|---|---|
| Usuario IG | `lopcprospa` |
| ID Instagram Business | `17841427333927757` |
| ID Página FB | `1397568803431045` |
| ID "Instagram app" (`lopcprospa - IG`) | `1434434268817542` ← NO se usa para publicar |
| App developers | `Brand Story Publisher` |

---

## 3. El app de desarrollador — reglas de oro aprendidas

### 3.1 El tipo de app es LA clave
- App tipo **Consumidor** ❌ → al pedir permisos de negocio te sale
  `Invalid Scopes: instagram_business_*`. **No sirve.**
- App tipo **Empresa (Business)** ✅ → el login acepta los scopes de Instagram.
- En el asistente nuevo de creación hay 4 pestañas; el tipo se fija eligiendo un
  **caso de uso empresarial** + **vinculando el app al Business Portfolio**
  (pestaña "Negocio", elegir el portfolio de la marca). Evita el caso de uso
  "Administrar mensajes y contenido de Instagram".

### 3.2 Producto Instagram — usar el setup de *login con Facebook*
- Añadir el producto se hace por **caso de uso**: `Administrar mensajes y
  contenido de Instagram`.
- **CRÍTICO:** dentro del producto hay que **Personalizar caso de uso** y elegir
  **"Configuración de la API con inicio de sesión Facebook"** (no el modo
  "login con Instagram"). Solo así los tokens de publicación son válidos contra
  `graph.facebook.com`. *(El otro modo genera token tipo `IGAA…` que NO vale.)*
- Añade también el producto **Facebook Login** (Configurar, sin rellenar).
- **Roles → Añadir cuenta de Instagram** (añadir `lopcprospa` y aceptar la
  invitación en la app). Es el "evaluador de Instagram".

### 3.3 Permisos que funcionan (modo login Facebook)
- `instagram_basic`
- `instagram_content_publish` ← ojo: el asistente lo muestra como
  *"instagram_content_publishing"*, pero el **scope real** lleva `_publish`.
- `pages_read_engagement`
- `pages_show_list`
- (`business_management` opcional)

Estos salen como **"Listo para la prueba"** → acceso estándar en modo
**Desarrollo**, **sin App Review**.

### 3.4 Token — por qué el método rápido no sirve (resumen de batallas)
| Camino probado | Resultado |
|---|---|
| Graph API Explorer con selector de permisos | ❌ el selector solo ofrece 3 permisos |
| URL manual `dialog/oauth` → redirect a `developers.facebook.com/tools/explorer/` | ❌ "dominio no incluido" (App Domains rechaza URLs de Facebook) |
| Token del producto IG ("Generar tokens") | ❌ produce token `IGAA…`, inválido en `graph.facebook.com` |
| **OAuth con redirect a `localhost`** + canje de código | ✅ **FUNCIONA** (ver §4) |

---

## 4. Generación del token — método que funciona (`get_token.py`)

Flujo estándar **Authorization Code** con redirect a `http://localhost:9876/callback`
(los redirects `localhost` están **auto-permitidos en modo desarrollo**, no hay
que registrarlos).

```bash
cd instagram-story-cron
source .venv/bin/activate
python get_token.py                      # abre URL → aceptas permisos → guarda token
python publish_story.py --refresh-only   # convierte a long-lived (60 días)
```

- Scopes por defecto en `get_token.py`; si cambian, override en `.env`:
  ```
  IG_SCOPES=instagram_basic,instagram_content_publish,pages_read_engagement,pages_show_list
  ```
- El token se guarda en `.env` como `IG_USER_TOKEN`. **Tipos de token:**
  `EAAG…` = token Facebook Graph válido ✅ · `IGAA…` = token de la "Instagram
  app" que **NO** sirve ❌ · `IGQVJ…` = token legacy IG ❌.

---

## 5. Configuración del entorno (`.env`)

```ini
APP_ID=                  # Identificador de la aplicación (app de developers)
APP_SECRET=              # Secret de la aplicación (Config → Básica → Mostrar)
PAGE_ID=1397568803431045 # ID numérico de la Página FB
IG_USER_TOKEN=           # EAAG… (lo genera get_token.py)
IG_BUSINESS_ACCOUNT_ID=17841427333927757  # se autodetecta, pero conviene fijarlo
PUBLIC_BASE_URL=         # URL pública base de las imágenes (ver §7)
PUBLISH_INTERVAL_H=3     # ritmo de publicación
# Opcionales:
# IG_SCOPES=...          # override de scopes para get_token.py
# PAUSED=true            # futuro kill-switch del cron
# MAX_PUBLISHES_PER_DAY= # futuro límite diario
```

### Scripts y uso
```bash
python publish_story.py                              # publica story del slot actual
python publish_story.py --feed --caption "Hola"      # publica en el feed
python publish_story.py --url https://…/imagen.jpg   # publica esa imagen concreta
python publish_story.py --dry-run                    # simula sin publicar
python publish_story.py --refresh-only               # solo refresca el token
python publish_story.py --comments                   # lee comentarios recientes
python publish_story.py --ai-caption --feed          # caption generado por opencode (AI writer)
python publish_story.py --ai-caption --ai-gen-only   # solo generar el caption, sin publicar
```

### Cron
- **GitHub Actions** (`publish-stories.yml`): `cron: "0 */3 * * *"`;
  credenciales en repo Settings → Secrets (`APP_ID`, `APP_SECRET`,
  `IG_USER_TOKEN`, `IG_BUSINESS_ACCOUNT_ID`, `PAGE_ID`, `PUBLIC_BASE_URL`).
  ⚠️ GitHub guarda el token original en el secret: el refresco se pierde en el
  runner efímero. Toca **actualizar el secret ~cada 50 días** (o usar VPS local,
  donde `.env` sí persiste).
- **Local (macOS)**: `crontab -e` → `0 */3 * * * cd …/instagram-story-cron && .venv/bin/python publish_story.py` (requiere el Mac encendido).

---

## 6. Roadmap de implementaciones futuras

### ✅ Hecho
- Stories cada N horas. · Feed posts (`--feed` + `--caption`).
- Lectura de comentarios (`--comments`).
- **Imagen ↔ texto**: cada entrada de `media/playlist.json` puede llevar su
  propio `caption` (se usa en feed; las stories no muestran captions).
- **AI writer (`--ai-caption`)** ✅: genera el caption con opencode a partir de
  los tags de la foto (`images.json`), con memoria (`last_captions.json` vía
  cache) para no repetir frases, y fallback si opencode falla.
- **AI replies (`--reply-new`)** ✅: borrador (FASE 1) de respuesta a comentarios
  con opencode (guardados en `drafts/`, sin publicar); `--publish-reply` activa
  la FASE 2. Un comentario se marca procesado SOLO tras gestionarse bien.
- **Guarda de cuota diaria** ✅: consulta `content_publishing_limit` antes de
  publicar y cancela el post si se llegó al tope (25/día; baja el techo con
  `MAX_PUBLISHES_PER_DAY`).

### 🚧 AI writer — cómo corre en GitHub Actions
Los prompts viven en **`prompts/caption.md`** y **`prompts/reply.md`**
(editables como archivos de texto; el script los lee SIEMPRE — **no hay
fallbacks en código**: si falta el archivo, el script falla a propósito).
Placeholders: `{voice} {filename} {desc} {tags} {last_captions}` (captions) y
`{voice} {username} {text}` (replies).

Workflow **`ai-publish.yml`** (disparo manual, cron comentado):
1. Checkout del repo (con `images.json` + fotos).
2. **Cache** para `last_captions.json` (persistencia sin commits).
3. Instala **opencode** en el runner (`npm install -g opencode-ai`).
4. Corre `python publish_story.py --ai-caption [--dry-run]` con:
   - `AI_MODEL` → variable del repo: **`opencode/mimo-v2.6-flash-free`**
     (modelo **gratis** integrado; NO requiere ninguna key para arrancar).
   - Secreto `OPENCODE_API_KEY` (OpenCode Go) o `DEEPSEEK_API_KEY` (BYOK):
     **opcionales**, solo si quieres un modelo de pago más potente.
   - `IG_POST_MODE=feed`, `IG_POST_IMAGE` (input opcional del workflow).

> 💡 Modelos gratis verificados (`opencode ... -free`, $0, sin key):
> `opencode/mimo-v2.6-flash-free`, `opencode/ling-3.1-flash-free`.
> Si no deja generar, rescata con `AI_MODEL=opencode-go/mimo-v2.6-flash`
> (Go, ~$0.14/$0.28) + secret `OPENCODE_API_KEY`.

### 🚧 Diseño: auto-respuesta con IA (`--reply-new`)
Responder comentarios usando opencode + modelo económico:

```
IG comenta → --reply-new lee comentarios nuevos (GET /{ig-id}/comments)
              → ¿ya respondido? (replied.json) → sí: skip
              → no: opencode run --model <económico> "<prompt con el comentario>"
              → respuesta → POST /{comment-id}/replies
              → guarda id en replied.json
```

- **Modelo económico:** tipo **DeepSeek V4 Flash** (esp. `--model provider/ds-v4-flash`).
- **Guardarrails obligatorios:**
  1. Prompt con la **voz de la marca** (idioma/tono) + comentario + contexto del post.
  2. Marcador `SKIP` si es spam/insulto/irrelevante → no responder, no publicar.
  3. `--reply-draft`: modo borrador (guarda propuestas en `drafts/` sin publicar)
     antes de activarlo en producción.
  4. Límite de longitud ~480 caracteres.
  5. Deduplicación con `replied.json` (nunca responder 2 veces).
- En GitHub Actions habría que **instalar opencode + API key** del proveedor en
  el runner (o ejecutar el modo IA solo en local/VPS).

### Ideas extra
- Notificación de "comentario nuevo" (sin responder, solo avisar).
- Filtro de comentarios (responder solo a preguntas reales, detectar SPAM).
- Métricas: `GET /{ig-id}/insights` (alcance, interacciones).

---

## 7. Hosting de las imágenes (`PUBLIC_BASE_URL`)

El API **descarga** la imagen de una URL pública; no lee tu disco.

- **Recomendado (gratis):** repo GitHub **público** + jsDelivr CDN:
  `PUBLIC_BASE_URL=https://cdn.jsdelivr.net/gh/USER/REPO@main/media`
- **Formato único ganador: 1080×1350 (4:5)** → válido para **stories Y feed**
  (verificado con el API: stories aceptan 9:16 y 4:5; feed acepta 4:5 y 1:1, NO
  más alargado). Añadir fotos: `python add_image.py foto.jpg --product olivo`
  (recorta, nombra, playlist, tags y git add en un solo paso).
- Formato por imagen: **JPG, 1080×1920 (9:16)** para stories puras, **1:1 o 4:5**
  para feed, <8 MB. Imágenes tipo 1:2 o más alargadas → error 36003
  ("aspect ratio is not supported").
- Para tests rápidos: `https://picsum.photos/1080/1920` (aleatoria; añade
  `/seed/algo` para imagen fija).

---

## 8. Límites y cumplimiento (léelo antes de automatizar fuerte)

- **25 publicaciones/día** por cuenta (feed+stories+reels+carruseles **comparten**
  ese tope). Consultable: `GET /{ig-id}/content_publishing_limit`.
- **Logs seguros (GitHub Actions):** `publish_story.py` nunca imprime URLs que
  contengan el `access_token` (helper `api()` con errores "sanitizados"). En el
  runner **no se refresca** el token: se usa el secret tal cual, para que
  GitHub lo enmasque en los logs; el secret se actualiza a mano ~cada 50 días.
- **Si un token se filtra** (p.ej. error crudo de requests en un log público):
  revócalo en Instagram → **Ajustes → Apps y sitios web** → eliminar el acceso,
  y regenera con `get_token.py` + actualiza el secret.
- `GET /me/permissions` → verifica qué permisos tiene el token.
- **Cuenta nueva:** calentar 1–3 semanas con 1–2 posts/día antes del cron a 8/día.
- **2FA con app de autenticador**, no SMS.
- **No usar** API privada/scraping/autenticación de app (ban).
- Contenido propio original, sin spam; las stories a horas muy regulares pueden
  reducir alcance si no hay interacción (no es infracción).
- Mantener el app en **modo Desarrollo** (suficiente para tu propia cuenta; la
  App Review es solo para cuentas de terceros).

---

## 9. Diagnóstico rápido (comandos que resuelven el 90%)

```bash
TOKEN=$(grep '^IG_USER_TOKEN=' .env | cut -d= -f2-)

# 1. ¿El token está vivo?
curl -s "https://graph.facebook.com/v26.0/me?fields=id,name&access_token=$TOKEN"

# 2. ¿Qué permisos tiene?
curl -s "https://graph.facebook.com/v26.0/me/permissions?access_token=$TOKEN"

# 3. ¿La página existe y tiene IG vinculado?
curl -s "https://graph.facebook.com/v26.0/PAGE_ID?fields=id,name,instagram_business_account&access_token=$TOKEN"

# 4. ¿La cuenta IG responde?
curl -s "https://graph.facebook.com/v26.0/IG_BUSINESS_ACCOUNT_ID?fields=id,username&access_token=$TOKEN"
```

### Errores típicos
| Error | Causa → solución |
|---|---|
| `code 190 – Cannot parse access token` | token es `IGAA…`/mal copiado → regenerar con `get_token.py` |
| `Invalid Scopes: instagram_business_*` | app tipo Consumidor → usar app **Empresa** o scopes `instagram_*` |
| `Invalid Scope: instagram_content_publishing` | nombre real es `instagram_content_publish` (override `IG_SCOPES`) |
| `me/accounts → data:[]` | Página dentro del portfolio → usar `PAGE_ID` directo |
| `instagram_business_account` no aparece | falta `instagram_basic`/`instagram_business_basic` en el token |
| "No puede ser una URL de Facebook" (App Domains) | campos confundidos → usar redirect localhost |

---

## 10. Endpoints clave usados

| Endpoint | Uso |
|---|---|
| `POST /{ig-id}/media` | crea contenedor (media_type=STORIES o IMAGE, image_url, caption) |
| `GET /{container-id}?fields=status_code` | esperar FINISHED |
| `POST /{ig-id}/media_publish` | publicar (creation_id) |
| `POST /{comment-id}/replies` | responder un comentario |
| `GET /{ig-id}/comments` · `GET /{media-id}/comments` | leer comentarios |
| `GET /oauth/access_token?grant_type=fb_exchange_token` | refrescar a long-lived (60 d) |
| `GET /{ig-id}/content_publishing_limit` | cuota restante del día |