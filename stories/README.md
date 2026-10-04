# stories/

Put your preset story images in this folder, then list them (in rotation order)
in `playlist.json`.

## Associating each image with publication text

Each entry can carry its own caption (used when posting to the **feed**):

```json
[
  { "file": "story1.jpg", "caption": "Nuevo producto — enlace en bio!" },
  { "file": "story2.jpg", "caption": "Oferta de verano 🔥" },
  "story3.jpg"
]
```

- `caption` is ignored when publishing **Stories** (Instagram doesn't show
  captions on stories).
- If you want text ON a story image, it must be baked into the picture itself
  (compose image + text before upload).

**Requirements per image**
- Format: **JPG** (JPEG) recommended. PNG works but can look pixelated.
- Aspect ratio **9:16** (vertical, like a phone screen), e.g. 1080x1920 px.
- Max size: under **8 MB**.

## Public hosting

The Instagram API downloads each image from a **public URL** — it cannot read
your disk. Two free options:

1. **GitHub + jsDelivr (recommended, free, automatic):**
   - Put this whole project in a **public** GitHub repo (images included).
   - Set `PUBLIC_BASE_URL=https://cdn.jsdelivr.net/gh/YOUR_GH_USER/YOUR_REPO@main/stories`
   - Then `story1.jpg` is reachable at
     `https://cdn.jsdelivr.net/gh/YOUR_GH_USER/YOUR_REPO@main/stories/story1.jpg`.
   - The CDN part means Instagram's fetch doesn't count against GitHub raw limits.

2. **Any public URL you already own** (bucket, your website...)
   - Just set `PUBLIC_BASE_URL` to that base and keep filenames matching.

> Test an URL in your browser before trusting it: it must load the image
> directly (no login, no redirect to an HTML page).