# Troubleshooting

## yt-dlp

- **"Sign in to confirm you're not a bot"**, or HTTP 403: add `--cookies-from-browser chrome` (or
  `firefox` or `edge`). This uses the browser's YouTube login. On Windows, Chrome must be fully
  closed for its cookies to be readable. If that still fails, export a cookies.txt with a browser
  extension and use `--cookies cookies.txt`.
- **"No supported JavaScript runtime"**, or formats missing: install Deno (`winget install
  DenoLand.Deno` / `brew install deno`) or Node.js. fetch.py passes `--js-runtimes node` automatically
  when only Node is present.
- **Anything else odd**: update first with `python -m pip install -U "yt-dlp[default]"`. YouTube
  changes often, and old yt-dlp versions break.
- **HTTP 429 on captions**: YouTube is rate-limiting. Wait a bit and re-run fetch.py. Files that are
  already downloaded are skipped.
- **The stream just ended**: `live_status: post_live` means YouTube is still processing. Captions,
  full quality and sometimes the whole VOD appear a few hours later. Streams longer than 12 h may only
  keep the last 12 h.
- **Members-only or private videos**: they need cookies from an account with access. Unlisted links work
  as-is.

## Twitch

Twitch VOD links work with yt-dlp (`https://www.twitch.tv/videos/<id>`), but there is no chat replay or
heatmap, and no captions. Use whisper for the transcript, or better: if the stream was also on YouTube,
use the YouTube VOD.

## Local files

- OBS recordings in `.mkv` work directly. With several audio tracks, the first one is used.
- Recording from YouTube Studio ("Download") is often 720p. That's fine for the blur and facecam
  layouts. The `crop` layout upscales a lot, so prefer `--max-height 1080` or higher downloads for it.

## Rendering

- **Captions render as boxes or in the wrong font**: the font isn't installed. Set `caption.font` and
  `hook_style.font` in clips.json to an installed font (Windows: "Arial Black", "Impact", "Segoe UI
  Black"; macOS: "Arial Black", "Impact"; Linux: "DejaVu Sans", "Liberation Sans").
- **Emoji show as boxes in the video**: expected. libass can't draw color emoji. Keep them in the post
  text only.
- **"No such filter: subtitles"**: the ffmpeg build lacks libass. On Windows use the full build from
  `winget install Gyan.FFmpeg`. On macOS, `brew install ffmpeg`.
- **Rendering is slow**: use `--fast` for drafts. The final encode uses x264 `fast` and takes roughly
  0.5–2× the clip length on a laptop.
- **Audio is out of sync** in a VFR (variable frame rate) OBS recording: remux or convert to CFR first:
  `ffmpeg -i in.mkv -c:a copy -c:v libx264 -crf 18 -r 60 -vsync cfr out.mp4`.

## Analysis

- **Every candidate is a loud explosion** (game audio dominating): signals with chat are better. Without
  chat, lean on the transcript and voice reactions, and look at `frames.py` sheets.
- **Times look shifted by a few seconds** with `--section`: yt-dlp cuts at keyframes, so captions and
  chat can drift 1–3 s. Check the cut points with `peek.py --words` and the frames.
- **A huge chat (100k+ messages)**: the first analyze.py run parses it into `chat_messages.json` (cached),
  so later runs are fast.

## Disk space

A 1080p60 stream is roughly 2–4 GB per hour, and 720p roughly 1–1.5 GB per hour. When the clips are
done, the big `video.*` file in the work folder can be deleted. Everything else is small.
