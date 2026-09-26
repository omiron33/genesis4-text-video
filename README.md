# Genesis 4 text video

A separate, CPU-only Genesis 4 lyric-video renderer. It never reads or writes
`~/storybook/ark-video`, its Genesis 7 song, shot files, or outputs. It takes a
reviewed song and the words actually sung, creates an immutable local intake,
and renders kinetic type over a slowly moving dark visual field. Optional cover
art becomes the backdrop. Audio is copied bit for bit at intake; the video
mux uses that frozen copy.

## Inputs

- The selected complete MP3 or WAV and its expected SHA-256.
- `lyrics.json`: Genesis 4 verses 1–26 in sung order. Each verse has `number`
  and `lyric` with one display phrase per line. `textStatus` is
  `approved_adapted` for the approved lyric script or `verified_sung` after
  word-for-word listening; the former does not claim every syllable was sung.
- Optional `timing.json`: one timed entry for **each lyric line** in the same
  order. Give each `verse`, `line`, `text`, `start`, and `end`. Times are seconds
  in the chosen audio. `machine_aligned` identifies timings inferred from ASR;
  `checked` is reserved for a direct listening review of timing. Without this
  file, intake makes an estimated draft and the final render refuses it;
  `--allow-draft` makes a clearly labeled timing preview.
  An observed repeated lyric at the end may be an extra segment with
  `repeat: true`, pointing to its source verse and line; its text must be a
  substring of that lyric line.
- Optional cover image (PNG/JPEG), selected take ID and Suno URL.

The input schema is demonstrated by `examples/lyrics.example.json` and
`examples/timing.example.json`. The included example has only two verses and
is for testing the format; intake requires all 26.

`source/approved-lyrics.json` is the approved Genesis 4 adaptation and original
Brenton verse mapping from songbook version
`e1cbdb12-d2df-48b7-b6ac-e1a611fdb377`. `source/timing.machine.json`
has 95 line timings based on the three CPU ASR reports under `source/asr/`.
These reports are diagnostic evidence, not a claim of exact sung words or
human-approved timing. To reproduce the line timing file:

```bash
.venv/bin/python align_from_asr.py --lyrics source/approved-lyrics.json \
  --base-asr source/asr/base-segments.json \
  --tiny-asr source/asr/tiny-segments.json \
  --word-asr source/asr/base-word-timestamps.json \
  --output source/timing.machine.json
```

## Setup

Python 3.12, Pillow, ffmpeg, and ffprobe are required. On the Mac mini:

```bash
cd ~/storybook/genesis4-video
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Freeze the selected song

```bash
.venv/bin/python genesis4_video.py intake \
  --audio '/path/to/approved-genesis4.mp3' \
  --expected-sha256 '<64 hex characters>' \
  --lyrics '/path/to/checked-lyrics.json' \
  --timing '/path/to/checked-timing.json' \
  --source-take-id '<take id>' \
  --source-url 'https://suno.com/song/<id>' \
  --cover '/path/to/cover.png'
```

It prints the intake directory under `intake/`. All source files are copied
there and hashed. Another audio, lyric, timing, or cover revision gets another
directory; existing inputs are never replaced.

## Render

```bash
.venv/bin/python genesis4_video.py render --intake 'intake/<id>'
```

Output lands under `out/<intake-id>/genesis-4-<timestamp>.mp4` with a contact
sheet and `provenance.json`. No existing movie is replaced. Rendering uses
Pillow and **CPU libx264** through ffmpeg; no Mac MPS, CUDA, ComfyUI, or AI
image/video model is invoked. The final movie is 1920×1080, 24 fps, H.264,
AAC, and matches the whole song duration. A short draft timing check is:

```bash
.venv/bin/python genesis4_video.py render --intake 'intake/<id>' \
  --allow-draft --preview-seconds 12
```

After the full movie passes playback and text checks, copy it to OmiPC and
use the songbook's `scripts/ingest-video.mjs` or `/api/admin/videos/ingest`.
That puts the *finished* film in the Studio Video approvals tab. Intake here
does not publish either the song or video.

## First approved-song render

The first full private video used approved songbook recording
`e1cbdb12-d2df-48b7-b6ac-e1a611fdb377` (Suno take
`55246c72-1d7a-4c90-a4d6-2fb3d06569ac-2`, original song
`https://suno.com/song/dd723dc8-5303-4694-9553-6d29f9768d04`). Its audio
SHA-256 is `c26b0dfd26850b091b408953120f2a0e07188f7415c6b03792320bf2b422cc2b`.
The cover came from that Suno song page. The final timing intake is
`8b41f03d8b50ed57`; its line timings are **machine-aligned** and remain
subject to human review. The 0–11.42s intro and 299–312s outro contain no
lyric captions. The first generated version with a caption during the intro
was rejected and remains only as a local comparison.

The submitted render's SHA-256 is
`579b680dd4e23886599935ff3aababb143ab40ef9b817f84df01dcd2ab57fd3b`
(312.000s, 1920×1080 H.264, 24 fps, AAC). It was transferred to OmiPC at
`C:\Users\sjfis\Videos\Genesis4\genesis4-text-v1-579b680d.mp4` and ingested
as `vid-20260926-3baa530e`, pending review. The local video directory also
holds its contact sheet and provenance JSON; generated media is ignored by
this Git repository.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Visual direction

The chapter begins in subdued gold, turns crimson for Abel's death and God's
question, then moves through indigo exile and iron gray generations. Seth and
Enos regain a restrained dawn gold. Type enters with controlled slide, fade,
and scale; high-impact words get a stronger pulse. References stay visible as
`GENESIS 4:8`, and an understated progress line tracks the whole chapter.
The exact timed phrase is the only lyric shown in each interval. Instrumental
gaps show only the scene and verse reference.
