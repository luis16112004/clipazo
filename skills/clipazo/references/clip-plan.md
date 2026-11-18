# clips.json: the render plan

`render.py` reads `W/clips.json`. Times are on the work folder's video timeline, the same numbers
`analyze.py` and `peek.py` print. They can be seconds (`3725.4`) or `"H:MM:SS.s"` strings
(`"1:02:05.4"`).

## Full example

```json
{
  "defaults": {
    "layout": "facecam",
    "facecam": {"x": 0.0, "y": 0.62, "w": 0.26, "h": 0.38},
    "formats": ["vertical"],
    "captions": true
  },
  "clips": [
    {
      "id": 1,
      "slug": "avioneta-al-mar",
      "start": "1:02:05.4",
      "end": "1:02:38.0",
      "hook": "NUNCA LE DEN UNA AVIONETA",
      "cover_at": "1:02:31",
      "notes": "Chat explodes at the crash. In-game radio is OFF here, so it's safe for Content ID.",
      "youtube": {
        "title": "Le di una avioneta a mi amigo y pasó esto 💀 #gta6",
        "description": "Primer día en GTA 6 y ya estamos así 😂\nStream completo en el canal.\n\n#gta6 #gtavi #shorts",
        "tags": ["gta 6", "gta vi", "gta 6 gameplay", "gta 6 funny moments"]
      },
      "instagram": {
        "caption": "Nunca le den una avioneta a este hombre 💀✈️ ¿Quién más ya está jugando GTA 6?",
        "hashtags": ["#gta6", "#gtavi", "#gaming", "#humor"]
      },
      "tiktok": {"caption": "Nunca le den una avioneta 💀 #gta6 #gtavi #fyp"}
    },
    {
      "id": 2,
      "slug": "persecucion-policia",
      "start": 5012.3,
      "end": 5051.0,
      "hook": "5 ESTRELLAS EN EL MINUTO 1",
      "layout": "blur",
      "zoom": 1.3,
      "formats": ["vertical", "horizontal"],
      "youtube": {"title": "...", "description": "...", "tags": []},
      "instagram": {"caption": "...", "hashtags": []}
    }
  ],
  "compilation": {
    "slug": "mejores-momentos-gta6-dia-1",
    "title": "GTA 6 DÍA 1: los mejores momentos del stream",
    "description": "Lo mejor del primer stream de GTA 6...",
    "order": "chronological",
    "captions": false
  }
}
```

## Clip fields

| field | required | meaning |
|---|---|---|
| `start`, `end` | yes | clip boundaries |
| `id` | no | number used in file names (defaults to the position in the list) |
| `slug` | no | file-name part, ASCII-fied automatically |
| `hook` | no | burned-in title text. Keep it under about 7 words and leave out emoji. Use `null` for none |
| `cover_at` | no | time for the cover frame (default: 40 % into the clip) |
| `notes` | no | your reasoning or warnings, copied into posts.md for the user |
| `youtube` | no | `{title, description, tags[]}` |
| `instagram` | no | `{caption, hashtags[]}` |
| `tiktok` | no | `{caption}` |
| any of the defaults below | no | overrides for this clip only |

## Defaults and per-clip overrides

Put them in `defaults`, or on a single clip. Nested objects such as `caption` merge key by key.

| key | default | notes |
|---|---|---|
| `layout` | `"blur"` | `blur`, `crop` or `facecam` (vertical only) |
| `formats` | `["vertical"]` | add `"horizontal"` for a 16:9 version (main YouTube channel, X, Facebook) |
| `captions` | `true` | word-by-word captions from the transcript |
| `zoom` | `1.2` | blur layout: gameplay width factor (1.0 = full frame, 1.3 = cut sides) |
| `crop_x` | `0.5` | crop layout: 0 = left edge, 1 = right edge |
| `facecam` | `null` | `{"x","y","w","h"}` fractions of the source frame (top-left origin) |
| `cam_height` | `"auto"` | facecam layout: camera band height as a share of 1920 px. `"auto"` fits it to the box's shape (0.25–0.45) |
| `game_x` | `0.5` | facecam layout: horizontal center of the gameplay crop |
| `caption.font` | Arial Black (Win/Mac) / DejaVu Sans | any installed font name |
| `caption.size` | `86` | px on a 1080×1920 canvas |
| `caption.color` / `caption.highlight` | `FFFFFF` / `FFE81F` | RRGGBB. The highlight marks the word being spoken |
| `caption.y` | `0.73` | vertical center of the captions (fraction of height); with the default zoom the blur layout's gameplay ends near 0.69 |
| `caption.uppercase` | `true` | |
| `caption.max_words` / `caption.max_chars` | `3` / `16` | words shown at once |
| `hook_style.size` / `hook_style.color` / `hook_style.y` | `74` / `FFFFFF` / `0.12` | in facecam layout the hook sits on the camera/gameplay seam |
| `hook_style.duration` | `null` (whole clip) | seconds to show the hook |
| `horizontal.captions` / `horizontal.hook` | `true` / `false` | for the 16:9 version |

## Choosing the facecam box

Run `frames.py --workdir W --full <time> --grid`. The grid lines are 10 % apart. For a camera in the
bottom-left corner that covers roughly the first quarter of the width and the bottom third, use
`{"x": 0.0, "y": 0.66, "w": 0.25, "h": 0.34}`. A box slightly inside the camera border looks cleaner
than one that catches gameplay pixels. Check the render with `frames.py --video <clip> --full 2`.

The camera band is wider than it is tall, so the box gets cropped to fill it. Frame the box around
the head and shoulders, not the whole body or avatar. With a tall box (a full-body avatar or a
vertical camera), only the middle of it stays visible. VTuber or PNG avatars work too: treat them
like a camera.

## Output (W/clips/)

- `NN-slug-vertical.mp4`: 1080×1920, H.264 and AAC, loudness-normalized to −14 LUFS, at the source
  fps (capped at 60).
- `NN-slug-horizontal.mp4`: 1920×1080, when requested.
- `NN-slug-cover.jpg`: a cover/thumbnail frame.
- `posts.md`: all titles, descriptions and hashtags, ready to copy.
- `<compilation-slug>.mp4`: with `--compilation`.

## Clipazo PRO keys

The paid add-on adds more keys: `caption.style` (`bounce`, `hormozi`, `box`, `neon`), `punch_ins`,
`sfx`, `progress_bar`, `brand`, `end_card`, `thumbnail`, `hook_variants` and `copy_en`. When PRO is
installed, they're documented in its `PRO.md` (doctor.py prints the path). Without PRO, render.py
ignores them and lists what it skipped.
