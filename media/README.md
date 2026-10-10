# media/

Carpeta con **todas las imágenes publicables** (stories o feed) del catálogo.
`playlist.json` define el **orden de rotación** (cada entrada: `{"file": "….jpg", "caption": "opcional"}`).

## Cómo añadir una imagen (flujo recomendado)

```bash
python add_image.py ruta/foto.jpg \
  --product olivo \
  --caption "Texto opcional" \
  --tags "sala, mediterraneo, sin mantenimiento"
```

`add_image.py`:
1. **Recorta/centra a 1080×1350 (4:5)** — el ratio válido para stories y feed.
2. Le da un **nombre único** y la guarda aquí.
3. Añade la entrada a `playlist.json`, los **tags** a `images.json` y valida/crea el **producto** en `products.json`.
4. Hace `git add` y te imprime la **URL pública**.

Solo falta `git push`.

## Reglas de formato
- **JPG** (o PNG), **1080×1350 (4:5)**, <8 MB.
- Los nombres únicos evitan cachés caducas en jsDelivr.

## Modelo de datos
| Archivo | Qué describe |
|---|---|
| `playlist.json` | orden de rotación (file + caption estático opcional) |
| `images.json` | por foto: `product` + `desc` + `tags` (para la IA) |
| `products.json` | por producto: nombre, beneficios, CTAs (solo hay `olivo` por ahora)