# Doka Story Scheduler

Programa historias de Instagram en la **nube de GitHub Actions** — sin depender de tu computadora.

## Cómo funciona

1. Corrés `schedule_stories.py` local apuntando a una carpeta con imágenes y una lista de horarios.
2. El script copia las imágenes al repo y agrega entries a `schedules/<marca>.json`.
3. Hacés `git push`.
4. GitHub Actions corre cada 15 min: lee los schedules, publica las historias cuya hora ya llegó via Meta Graph API, y commitea el estado actualizado.

Tu máquina solo se usa para el paso 1 y 3. El resto vive en los servidores de GitHub.

## Estructura

```
.github/workflows/publish-stories.yml   # cron cada 15 min
scripts/publish_stories.py               # corre en GitHub Actions
scripts/schedule_stories.py              # helper local para agregar al schedule
scripts/requirements.txt
schedules/<marca>.json                   # ig_user_id + lista de entries
images/<marca>/<YYYY-MM-DD>/*.jpg        # imágenes a publicar
```

## Setup inicial (una sola vez)

### 1. Crear repo público en GitHub

Tiene que ser **público** porque Meta Graph API necesita URLs accesibles para las imágenes. Alternativa: hospedar imágenes en S3/Drive y poner URLs http en el campo `image` del schedule — en ese caso el repo puede ser privado.

```bash
cd doka-story-scheduler
git init
git add .
git commit -m "initial"
gh repo create doka-story-scheduler --public --source=. --push
```

### 2. System User Token (permanente) de Meta

El token short-lived del Graph API Explorer expira en ~1h — no sirve. Necesitás un **System User Token** que no expira:

1. Business Manager → Settings → Users → System Users → Add
2. Nombre: `doka-story-scheduler`, rol Admin
3. Assign Assets: tu app Doka Studio, páginas de FB de Aromia/Papitas/etc.
4. Generate Token con permisos: `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`
5. Copiá el token

### 3. Obtener `ig_user_id` de cada marca

Cada cuenta IG Business tiene un ID diferente. Con el token:

```bash
curl "https://graph.facebook.com/v21.0/me/accounts?access_token=TOKEN"
# Por cada página → tomá el page_id
curl "https://graph.facebook.com/v21.0/PAGE_ID?fields=instagram_business_account&access_token=TOKEN"
# Devuelve { "instagram_business_account": { "id": "17841401234567890" } }
```

Pegá ese ID en `schedules/<marca>.json` en el campo `ig_user_id`.

### 4. Guardar token como secret en GitHub

```bash
gh secret set META_ACCESS_TOKEN
# pegá el token cuando lo pida
```

### 5. (Opcional) Verificar que el workflow corre

```bash
gh workflow run "Publish scheduled stories"
gh run watch
```

## Uso diario

Para programar historias de Aromia con las imágenes que tengas en una carpeta:

```bash
python scripts/schedule_stories.py \
  --brand aromia \
  --folder "C:/Users/Jasonleiton/Downloads/stories-aromia-abril" \
  --times "2026-04-22 08:00,2026-04-22 14:00,2026-04-23 09:00,2026-04-23 18:00"

git add -A
git commit -m "schedule aromia abril 22-23"
git push
```

Las imágenes se ordenan alfabéticamente, así que nombralas `01-frase.jpg`, `02-promo.jpg`, etc. para controlar el orden.

### Programación recurrente

```bash
python scripts/schedule_stories.py \
  --brand aromia \
  --folder "./lote-abril" \
  --every "09:00,18:00 starting 2026-04-22 count 14"
# 7 días × 2 horarios diarios = 14 historias
```

## Atajo "desde Claude"

Tenés dos opciones para que sea aún más rápido:

**A) Decile a Claude:**
> "Programa historias de Aromia con las imágenes de C:/Downloads/stories-abril, lunes 8am y 2pm, martes 9am y 6pm"

Claude te genera el comando `schedule_stories.py` correcto y lo corre.

**B) Skill dedicada:** armamos una skill `doka-historias-programadas-cloud` que hace los pasos A→push automáticamente. (Ya existe `doka-historias-programadas` local — este sería su primo cloud.)

## Límites y notas

- **GitHub cron no es exacto** — puede disparar hasta ~15 min tarde en horas pico. No programes historias críticas en el minuto exacto.
- **Meta API stories** solo acepta imágenes JPEG/PNG, max 8 MB, ratio 9:16 recomendado.
- **Rate limit** de IG Graph API: 25 posts/24h por cuenta. Más que suficiente para historias.
- **Publicación fallida** queda con `status: "error"` y el mensaje en `error`. Revisá el log del run en GitHub.
- **Imágenes consumen git** — cada push sube los JPG al repo. Si se vuelve pesado, migramos a Cloudflare R2 o Drive.
