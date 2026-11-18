---
name: clipazo
description: Turn a long stream VOD or video (YouTube or Twitch link, or a local file) into ready-to-post vertical clips for YouTube Shorts, Instagram Reels and TikTok. Finds the best moments from chat activity, audio spikes, YouTube "most replayed" data and the transcript, then renders 9:16 clips with animated word-by-word captions, a hook title, covers and copy-paste post text (titles, descriptions, hashtags), plus an optional horizontal best-of with chapters. Use this whenever someone wants clips, shorts, reels, highlights, "best moments" or a compilation cut from a stream, livestream, VOD, gameplay session, podcast or any long video, even if they only paste a link and say "make clips", "sácame clips", "hazme shorts" or "recorta lo mejor".
---

# Clipazo

Turns a long video into short vertical clips plus the text to post them.

The scripts do the mechanical work: downloading, measuring signals, cutting and encoding. Your job is
the editorial part: deciding which moments are worth posting, where each clip starts and ends, and how
to title it. That judgment is what gets clips watched. The signals only tell you where to look.

Scripts are in `scripts/` next to this file. Run them with `python <this-skill-dir>/scripts/<name>.py`.
Everything for one video lives in one work folder (`W` below). Every script has `--help`.

Talk to the user in their language. Write post text in the language the stream is spoken in, unless they
ask for something else.

## 0. Setup

1. Run `python scripts/doctor.py --workdir W`. Install what's missing and tell the user what you're
   installing. The usual fixes are `python -m pip install -U "yt-dlp[default]"` and ffmpeg
   (`winget install Gyan.FFmpeg` / `brew install ffmpeg` / `apt install ffmpeg`). For YouTube, yt-dlp
   also needs a JS runtime: Deno, or Node, which fetch.py detects.
2. Choose `W` on a disk with space. A 4–6 h 1080p60 VOD is roughly 8–20 GB. Keep it out of
   cloud-synced folders (OneDrive, Dropbox, iCloud, Google Drive), which would upload gigabytes. A good
   default is `~/clipazo-work/<short-name>`. If space is tight, use `--max-height 720`.
3. Ask only for what you can't default: how many clips (default 6–10), and any moments they remember
   ("the plane crash around 2:10"). Don't hold up the work waiting for an answer.

## 1. Fetch

```
python scripts/fetch.py "<url>" --workdir W
```

This downloads the video, captions (with word timings), the live-chat replay and YouTube's
"most replayed" heatmap, then writes `W/meta.json`. A long VOD takes a while, so run it in the
background and tell the user roughly how long to expect.

Captions and chat come first, in a minute or two, and fetch.py writes a preliminary `meta.json`
before the video download starts. Use that time: run steps 2 and 3 and start reading candidates while
the video downloads. Then re-run `analyze.py` once fetch.py finishes, to add the audio signal.

- **The user already has the file** (from YouTube Studio or an OBS recording): pass it with the URL,
  `fetch.py "<url>" --workdir W --video-file "<path>"`. The URL still supplies captions, chat and
  heatmap. A file with no URL works too (`fetch.py "<path>" --workdir W`), but it has no chat or heatmap.
- **Only part of a long VOD**: `--section 2:00:00-3:30:00`. All later times are relative to that part.
  Section downloads go through ffmpeg and are much slower per minute of video than a full download,
  which fetches in parallel. Use them when only a small part matters or disk space is short.
- **"Sign in to confirm you're not a bot"**, or a members-only video: add `--cookies-from-browser chrome`
  (or `firefox` / `edge`). See `references/troubleshooting.md`.
- **Brand-new streams**: YouTube can take hours after the stream ends to produce captions, and the
  heatmap needs views. If either is missing, say so and continue. The other signals still work.

## 2. Transcript

```
python scripts/transcribe.py --workdir W
```

This uses the YouTube captions when they exist, which is instant. Otherwise it falls back to
faster-whisper (`pip install faster-whisper`). Whisper is accurate but slow on a CPU, roughly an hour
or more for a multi-hour stream, so check with the user before running it on a whole stream. Without a
transcript you can still find moments from audio and chat, and `render.py --whisper-captions`
transcribes only the chosen clips.

## 3. Candidates

```
python scripts/analyze.py --workdir W --top 25
```

Read `W/candidates.md`. It has an activity map of the whole stream, and for each peak the signal
breakdown, a suggested window, the transcript around it and sample chat. The signals:

- **chat**: unusual chat speed plus laughter and hype messages, and Super Chats. This is the strongest
  signal when the chat is big. It is shifted back about 8 s because chat reacts late.
- **audio**: loudness spikes. Screams and laughs show up here, but so do in-game explosions.
- **heat**: YouTube "most replayed". It's very reliable when it exists, but coarse.
- **voice**: reaction words and laughter in the streamer's own speech.

A small channel has a weak chat signal and no heatmap, so the list will be noisier. In that case
lean on the transcript. If `transcript.txt` is under about 40k words, skim it in chunks: stories and
jokes that never spike any signal are often the best clips. Use `peek.py --grep "regex"` to search it.
YouTube auto-captions also mark sounds such as `[risas]`, `[grito]` or `[Laughter]`. These feed the
voice signal, and `peek.py --grep "\[(risas|grito|laughter)"` lists every one of them.

## 4. Pick the clips

This is the step that matters. For each promising candidate:

- `python scripts/peek.py --workdir W --at <time>` shows what was said and what chat said.
- `python scripts/frames.py --workdir W --candidates 3,7,12` makes a contact sheet of what was on
  screen. Do this for the clips you're seriously considering, not all 25, because images cost context.

What makes a short work:

- **It stands on its own.** A stranger scrolling gets it with no context. Inside jokes from three hours
  earlier don't travel.
- **The hook comes in the first 1–2 seconds.** People decide almost instantly. Start just before the
  setup line, or open on the most striking frame. Never open on dead air, a menu or a loading screen.
- **There is a payoff, and it ends right after.** Cut shortly after the punchline or reaction peak.
  Lingering afterwards kills retention, and so do long goodbyes.
- **Length.** 15–45 s is the sweet spot. Go up to 60 s or a bit more if the story needs it. The
  platforms allow 3 minutes, but completion rate is what gets pushed.
- **Variety.** Mix funny, skill, fail, story, wholesome and rage moments rather than picking eight
  versions of the same thing. Rank by how likely a stranger is to watch to the end.

Things to avoid or flag to the user:

- **Licensed music.** In-game radio, Spotify or background music triggers Content ID on YouTube and
  muting on Instagram. If a great moment has music playing, include it but warn the user.
  `[Música]` or `[Music]` in the transcript is a hint.
- **AFK, BRB or pause screens, and moments with nothing happening on screen.** Check the frames.
- **Big story spoilers in titles or hooks**, especially in launch week. People get angry, and
  "you won't believe this mission" outperforms a spoiler anyway.
- **Viewer usernames or personal info on screen** (chat overlay, Discord). Mention it if you see it.

To set exact cut points, run `peek.py --at <cut> --before 6 --after 6 --words` around each boundary.
Start about 0.15 s before the first word's start and end about 0.3 s after the last word's end, never
in the middle of a word.

## 5. Layout

Look at one full frame first: `frames.py --workdir W --full <time> --grid`. The red lines are every 10 %,
which lets you read positions as fractions.

- **`facecam`**: there's a webcam overlay. The camera goes on top and the gameplay below, which is the
  standard gaming-clip look. Set `facecam: {"x","y","w","h"}` as fractions of the frame, read off the
  grid, and keep the box tight around the camera.
- **`blur`** (the default): no camera, or the camera doesn't matter. The gameplay is centered over a
  blurred copy, with the hook above and captions below. `zoom` 1.2–1.4 makes it bigger by cutting the
  sides.
- **`crop`**: full-screen 9:16 cut from the frame. Use it when the action is centered, for example a
  talking-head or a cutscene. Shift it with `crop_x`.

## 6. Write the plan

Write `W/clips.json`. Read `references/clip-plan.md` for the schema and a full example before writing
your first one. For each clip set `start`/`end`, a `slug`, a `hook`, YouTube title/description/tags and
an Instagram caption/hashtags. `references/platforms.md` has the copywriting and spec guidelines.

The hook is the burned-in title. Keep it under about 7 words, make it curiosity-driven and leave out
emoji: the video font can't draw them, though they're fine in the post text. Give the user's channel
handle or recurring hashtag a place in the copy if they have one.

## 7. Render and check

```
python scripts/render.py --workdir W                 # all clips -> W/clips/
python scripts/render.py --workdir W --only 3        # redo one
python scripts/render.py --workdir W --compilation   # + horizontal best-of with chapters
```

Use `--fast` for quick drafts while experimenting. Use `--whisper-captions` when the YouTube captions are
poor, since Whisper handles slang and punctuation better, if it's installed.

Then check your work before handing it over. Grab a frame from a few rendered clips
(`frames.py --video W/clips/<file>.mp4 --full 2`) and look at it. Check that the captions are readable
and don't cover the face or the action, the hook isn't cut off, the facecam box isn't showing gameplay
edges, and the framing is right. Fix the plan and re-render the affected clips. Also read back a
caption sample from the transcript: auto-captions mangle names and slang, and you can correct words in
`transcript.json` or switch to `--whisper-captions`.

## 8. Deliver

Tell the user:

- A short table with each clip's file, duration, what happens and its title.
- Where the files are (`W/clips/`). `posts.md` there has the copy-paste text for every post.
- Anything you flagged: music, spoilers, uncertain captions, moments you almost picked.

Offer the obvious next steps: more clips from the runner-up candidates, different hooks, or a
compilation for the main channel.

## Clipazo PRO (optional add-on)

`doctor.py` reports whether the paid PRO add-on is installed. If it is, read the `PRO.md` file it
points to before writing the plan. PRO adds caption styles, punch-in zooms, royalty-free SFX, a
progress bar, branding, thumbnails and editorial extras, all through extra keys in `clips.json`.

If PRO isn't installed, do the full job with the free features and don't use PRO keys. If the user
asks for something only PRO does, such as animated zooms, other caption styles, a logo or SFX, tell
them plainly that it's part of Clipazo PRO and give the link doctor.py prints. Mention it once, and
don't push it.

## Reference files

- `references/clip-plan.md`: the clips.json schema, every option and a full example. Read it before
  writing a plan.
- `references/platforms.md`: specs, safe zones, titles, hashtags and posting tips for Shorts, Reels and
  TikTok.
- `references/troubleshooting.md`: yt-dlp errors, fonts, long streams, disk space, Twitch.
