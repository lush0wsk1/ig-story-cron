# AGENTS.md — instagram-story-cron

Contexto de proyecto para OpenCode. Léelo antes de tocar código.
Documentación detallada: `IMPLEMENTATION_GUIDE.md`. Uso rápido: `README.md`.

## 1. Qué es
Publicador automático en la cuenta **Instagram Business** de la marca (`lopcprospa`) vía **Graph API oficial** (Content Publishing), en feed. Cron diario que genera el caption con IA y publica una foto del catálogo. Repo público: `lush0wsk1/ig-story-cron`.

Ruta local: `~/Desktop/Development/Opencode/instagram-story-cron`

## 2. Identidades (no secretas)
- IG Business: `lopcprospa`, ID `17841427333927757`
- Página FB: "Lopc pro spa", ID `1397568803431045`
- App de developers: "Brand Story Publisher" (tipo Empresa)
- Cuenta FB admin: Luis Ponce

## 3. Secretos (NUNCA en el repo ni en logs)
- Local: `.env` (gitignored).
- GitHub Secrets: `APP_ID`, `APP_SECRET`, `IG_USER_TOKEN`, `IG_BUSINESS_ACCOUNT_ID`, `PAGE_ID`, `PUBLIC_BASE_URL`.
- GitHub Variable: `AI_MODEL` = `opencode/mimo-v2.6-flash-free` (gratis, sin key).
- No hay secret `OPENCODE_API_KEY` ni `DEEPSEEK_API_KEY`: no son necesarios con el modelo free.
- Token: tipo **EAAG** (usuario Facebook). Los tokens **IGAA** (flujo "Instagram API") NO sirven aquí.
- Renovación: en el runner no se refresca (se usa el secret tal cual). Renovar el secret cada ~50 días. Última regeneración: alrededor del 10/10/2026.
- Logs: el helper `api()` solo imprime mensajes de error, nunca URLs (contienen el token). No añadir `print` de tokens, URLs con `access_token` ni `raise_for_status()` sobre llamadas a la API.

## 4. Estructura
```
publish_story.py   publicación (story/feed), caption IA, cuota, comentarios, borradores de respuesta
add_image.py       añadir foto: recorte 4:5 1080x1350, nombre único, playlist, images.json, products.json, git add
get_token.py       genera token de usuario (OAuth con localhost:9876, IG_SCOPES)
prepare.py         legado: recorte por lote desde media/originals (preferir add_image.py)
prompts/caption.md prompt de captions (OBLIGATORIO, sin fallback en código)
prompts/reply.md   prompt de respuestas a comentarios (OBLIGATORIO)
products.json      catálogo: olivo y arbol-interior
images.json        por foto: product, desc, tags
media/             fotos publicables + playlist.json (orden de rotación)
.github/workflows/ai-publish.yml        cron diario + manual (IA)
.github/workflows/publish-stories.yml   manual (story/feed sin IA)
```

## 5. Reglas de contenido
- Imágenes: 1080x1350 (4:5). Válido para story y feed. Ratios más alargados dan error 36003.
- Captions: en **español**, máximo 500 caracteres, 4-6 hashtags (tags de la foto + marca del producto + audiencia), 1-2 emojis, sin precios ni medidas inventadas.
- Los datos de producto vienen de `products.json` (`benefits`, `specs`). Son la fuente de verdad: no inventar.
- La voz de marca es genérica (árboles artificiales), no solo olivo.
- Los captions estáticos de `playlist.json` solo se usan en modo sin IA. El cron usa IA.

## 6. Productos
- **olivo**: olivo artificial 160 cm. 4 fotos (`olivo_*`). Link ML: `links.mercadolibre` (anuncio MLC-2242117631).
- **arbol-interior**: árbol artificial SenBo (fabricante Guangdong Senbo, modelo XYS). Alturas 170/190/210 cm. Tronco PE + acero galvanizado, hojas textil técnico, 3-10 años, empaque 160x30x30 cm, 5 kg, 4 pzas/CTN. 3 fotos. Las fotos del árbol completo son de **170 cm**. Sin link ML todavía (`links: {}`).
- Esquema de producto (igual para todos): `name`, `benefits`, `cta[]`, `hashtags[]`, `links{}`, `specs{}`.

## 7. Pipeline
1. `add_image.py foto.jpg --product <slug> --tags "…" [--caption "…"] [--ml-url "…"]` → media + playlist + images.json + git add.
2. `git push`.
3. Cron diario (`0 15 * * *` UTC): `PUBLISH_INTERVAL_H=24` → una imagen distinta por día (rotación por slot mod N). Genera caption con IA y publica feed.
4. Manual: Actions → "Publicar con IA (opencode)" → Run workflow. `dry_run` por defecto **true**. Cron fuerza `dry_run=false`.
5. Cuota: `content_publishing_limit`. Límite de la cuenta: 100/día (`MAX_PUBLISHES_PER_DAY` baja el techo).

## 8. Comandos clave
```bash
source .venv/bin/activate
python publish_story.py --dry-run --feed --image <archivo>
python publish_story.py --ai-caption --feed --image <archivo>      # publica de verdad
python publish_story.py --ai-caption --ai-gen-only --feed --image <archivo>   # solo caption
python publish_story.py --refresh-only                              # chequeo de token
python publish_story.py --comments
```
Probar el runner: `gh workflow run "Publicar con IA (opencode)" --repo lush0wsk1/ig-story-cron -f dry_run=true`

## 9. Decisiones tomadas (no revertir sin motivo)
- Sin link en primer comentario (descartado por el usuario).
- Sin sync automático de bio: `instagram_business_manage_profile` no existe en el flujo Facebook Login. Código revertido.
- Sin modelo de visión por ahora: la key de OpenCode Go no se encontró. Las fotos se describen a mano (tags + desc) y los captions salen de esas descripciones.
- Respuestas a comentarios: solo borradores locales (`--reply-new`). Publicar (`--publish-reply`) no está activado.
- Links de ML en `products.json` se guardan como dato de catálogo para uso futuro (no se usan en código).
- Nombre de carpeta: `media/` (antes `stories/`).

## 10. Errores ya resueltos (no repetir)
- `Invalid Scope: instagram_content_publishing` → el scope real es `instagram_content_publish`.
- `Invalid Scopes: instagram_business_*` → app tipo Consumidor. Usar app tipo Empresa.
- Error 190 "Cannot parse access token" → token IGAA o mal copiado.
- `me/accounts` vacío → página dentro de portfolio. Usar `PAGE_ID` directo.
- Secrets con comentarios de `.env` pegados → usar `dotenv_values` al subirlos.
- Warning Node 20 → `checkout@v7`, `setup-python@v7`, `cache@v6`.
- "No puede ser una URL de Facebook" en App Domains → no poner dominios de Facebook ahí.
- Cron de GitHub retrasado o saltado un día → `gh workflow disable`/`enable` y lanzar manual.

## 11. Publicaciones reales hechas (para no perder la pista)
- `18283968733293939` — olivo, IA (local), 10/10
- `17947721799339729` — olivo, IA (runner), 10/10
- `17950655697293236` — olivo, cron, 11/10
- `18092931560698108` — manual runner, 12/10
- `18199993876347013` — arbol-interior 170 cm, IA, 12/10
- Pruebas permanentes (borrar si no interesan): `18136485133632438`, `18215994748359655`
- Story de prueba (expira): `17890090047455712`

## 12. Pendiente
- Link ML del `arbol-interior` (no lo tenemos).
- Fotos de 190 cm y 210 cm del `arbol-interior` (si se quieren).
- Modelo de visión: falta la key de OpenCode Go (`console.opencode.ai` → API Keys) o usar Gemini (AI Studio, gratis).
- Confirmar que el token EAAPnfE2… filtrado en un log antiguo fue revocado (Instagram → Ajustes → Apps y sitios web). Si no, regenerar el token y actualizar el secret.
- Renovar `IG_USER_TOKEN` antes de ~8/12/2026.
- Revisar que el cron diario publique cada día (GitHub puede retrasarlo o saltarlo).
- Warm-up de cuenta nueva: 1 post/día es el ritmo actual, bien.
