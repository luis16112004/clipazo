# Platforms: specs and copy guidelines

Platform rules change often. Treat the numbers below as a baseline, and if the user reports an upload
problem, trust what the platform says.

## Specs

| | YouTube Shorts | Instagram Reels | TikTok |
|---|---|---|---|
| canvas | 1080×1920 (9:16) | 1080×1920 (9:16) | 1080×1920 (9:16) |
| max length | 3 min | 3 min | 10 min (uploads) |
| sweet spot | 15–45 s | 15–45 s | 20–60 s |
| title | ≤100 chars, the first ~40 show | n/a | n/a |
| caption | description, up to 5,000 chars | ≤2,200 chars, the first line shows | ≤4,000 chars |
| hashtags | 3–5 in the title or description | 3–5 (more doesn't help) | 3–5 |

render.py's output (H.264, AAC, −14 LUFS, ≤60 fps, faststart) uploads fine to all three.

**Safe zones.** The app UI covers the bottom ~20 % (channel name, caption, music) and a strip on the
right (like/comment/share buttons). That's why captions sit around 73 % of the height and the hook sits
near the top. Keep important action out of the bottom fifth.

## Titles and hooks

- **Create a curiosity gap**, so the viewer wants to know what happens: "Le di una avioneta a mi amigo
  y pasó esto". Don't give the payoff away in the title.
- **Lead with the moment, not the game.** Put the game name at the end or in a hashtag ("... #gta6"),
  because people search the moment and the game tags categorize it.
- **Use specific details**: "5 estrellas en el minuto 1" beats "Persecución loca".
- **Write the way the streamer talks.** Slang from the stream ("no manches", "bro") is good, and
  corporate tone is bad.
- **Don't clickbait something that isn't in the clip.** Retention drops and the algorithm punishes it.
- **Keep the burned-in hook and the post title different.** They should complement each other, not
  repeat word for word.
- **Emoji**: one or two in titles and captions is fine. Leave them out of the burned-in hook, since the
  video font can't draw them.

## Descriptions and captions

- **First line**: the hook or a question that invites comments ("¿Ustedes qué hubieran hecho?").
- **Then the call to action**: the full stream link, or "stream completo en el canal", plus the Twitch
  or other channel.
- **Hashtags**: 1–2 broad ones (#gta6, #gaming), 1–2 specific ones (#gta6funny, #gtavi), and the
  channel's own tag if it has one. Use the stream's language.
- **On YouTube**, suggest the user link each Short to the full VOD ("Related video" in YouTube Studio).
  It's the best free funnel from Shorts to long-form.

## Music, Content ID and other risks

- **Game soundtracks and in-game radio carry licensed music.** On YouTube this gets claimed by
  Content ID (monetization goes to the rights holder, and some tracks are blocked). On Instagram the
  audio may be muted. Prefer clips without radio music, and flag the ones that have it.
- **Publisher policies**: most publishers, Rockstar included, allow monetized gameplay videos and
  streams. Short clips of gameplay with the creator's own commentary are the standard, safe case.
  Leaked or pre-release material is not.
- **Spoilers**: in launch week, keep the main story out of titles, hooks and covers. Add "(sin spoilers)"
  when a clip is safe, since that sells.

## Posting cadence (tips to pass on if the user asks)

- **Post 1–3 shorts a day** in the days after a big stream rather than all at once. It gives a steady
  drip, and each post gets its own test audience.
- **Post the strongest clip first** while the topic is trending. A game launch week is the peak.
- **Post the same clip on all three platforms.** Remove other platforms' watermarks. render.py output
  has none.
