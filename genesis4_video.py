#!/usr/bin/env python3
"""Immutable Genesis 4 song intake and CPU-only kinetic lyric video renderer."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
INTAKE = ROOT / "intake"
OUT = ROOT / "out"
FONTS = ROOT / "assets" / "fonts"
VIDEO_FPS = 24
DEFAULT_SIZE = (1920, 1080)
PALETTES = {
    "origin": ((193, 159, 92), (17, 24, 29)),
    "blood": ((210, 70, 69), (27, 15, 25)),
    "exile": ((129, 112, 166), (16, 21, 35)),
    "generations": ((137, 175, 177), (14, 28, 35)),
    "hope": ((223, 185, 109), (21, 27, 30)),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def executable(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    homebrew = Path("/opt/homebrew/bin") / name
    if homebrew.is_file():
        return str(homebrew)
    raise FileNotFoundError(f"{name} is required on PATH or in /opt/homebrew/bin")


def ffprobe(path: Path) -> dict:
    proc = subprocess.run(
        [executable("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


def duration_of(path: Path) -> float:
    data = ffprobe(path)
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise ValueError(f"No audio stream: {path}")
    duration = float(data.get("format", {}).get("duration", 0))
    if not 20 <= duration <= 720:
        raise ValueError(f"Song duration out of range: {duration:.2f}s")
    return duration


def lyric_lines(data: dict) -> list[dict]:
    if data.get("book") != "Genesis" or data.get("chapter") != 4:
        raise ValueError("Lyrics must identify Genesis chapter 4.")
    verses = data.get("verses")
    if not isinstance(verses, list) or len(verses) != 26:
        raise ValueError("Genesis 4 intake needs all 26 verses in order.")
    lines: list[dict] = []
    for expected, verse in enumerate(verses, 1):
        if not isinstance(verse, dict) or int(verse.get("number", 0)) != expected:
            raise ValueError(f"Missing or out-of-order Genesis 4:{expected}.")
        lyric = verse.get("lyric")
        if not isinstance(lyric, str) or not lyric.strip():
            raise ValueError(f"Empty lyric for Genesis 4:{expected}.")
        parts = [x.strip() for x in lyric.splitlines() if x.strip()]
        if not parts:
            raise ValueError(f"No display lines for Genesis 4:{expected}.")
        for line_no, text in enumerate(parts, 1):
            lines.append({"verse": expected, "line": line_no, "text": text})
    return lines


def draft_timing(lines: list[dict], duration: float) -> dict:
    # This is deliberately only a layout draft; sung timing must be checked.
    start, stop = 4.0, max(4.1, duration - 3.0)
    weights = [max(4, sum(ch.isalpha() for ch in item["text"])) ** 0.8 for item in lines]
    total = sum(weights)
    t = start
    segments = []
    for item, weight in zip(lines, weights):
        next_t = min(stop, t + (stop - start) * weight / total)
        segments.append({**item, "start": round(t, 3), "end": round(next_t, 3)})
        t = next_t
    segments[-1]["end"] = round(stop, 3)
    return {"status": "estimated", "method": "line-length allocation; not audio alignment", "segments": segments}


def check_timing(timing: dict, lines: list[dict], duration: float) -> list[dict]:
    events = timing.get("segments")
    if not isinstance(events, list) or len(events) < len(lines):
        raise ValueError(f"Timing needs all {len(lines)} lyric lines in order.")
    if timing.get("status") not in ("estimated", "machine_aligned", "checked"):
        raise ValueError("Timing status must be 'estimated', 'machine_aligned', or 'checked'.")
    cleaned = []
    previous_end = 0.0
    for idx, (event, line) in enumerate(zip(events[:len(lines)], lines), 1):
        if not isinstance(event, dict):
            raise ValueError(f"Timing segment {idx} is not an object.")
        for key in ("verse", "line", "text"):
            if event.get(key) != line[key]:
                raise ValueError(f"Timing segment {idx} does not match the exact sung lyric line ({key}).")
        try:
            start, end = float(event["start"]), float(event["end"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"Timing segment {idx} has invalid times.") from exc
        if not (math.isfinite(start) and math.isfinite(end)):
            raise ValueError(f"Timing segment {idx} has nonfinite times.")
        if start < previous_end - 0.001 or end <= start or end > duration + 0.1:
            raise ValueError(f"Timing segment {idx} overlaps, reverses, or passes the audio end.")
        cleaned.append({**line, "start": start, "end": end})
        previous_end = end
    for idx, event in enumerate(events[len(lines):], len(lines) + 1):
        if not isinstance(event, dict) or event.get("repeat") is not True:
            raise ValueError(f"Extra timing segment {idx} must be an observed repeated lyric fragment.")
        source = next((line for line in lines if line["verse"] == event.get("verse") and line["line"] == event.get("line")), None)
        repeated = event.get("text")
        if not source or not isinstance(repeated, str) or repeated.lower().strip(" .,;:!?") not in source["text"].lower():
            raise ValueError(f"Repeated lyric segment {idx} is not a phrase from its source line.")
        start, end = float(event["start"]), float(event["end"])
        if start < previous_end - .001 or end <= start or end > duration + .1:
            raise ValueError(f"Repeated lyric segment {idx} overlaps or passes the audio end.")
        cleaned.append({"verse": source["verse"], "line": source["line"], "text": repeated, "start": start, "end": end, "repeat": True})
        previous_end = end
    return cleaned


def safe_copy(source: Path, dest: Path, expected: str) -> None:
    if dest.exists():
        if sha256(dest) != expected:
            raise ValueError(f"Immutable destination differs: {dest}")
        return
    temporary = dest.with_name(dest.name + f".{uuid.uuid4().hex}.partial")
    shutil.copyfile(source, temporary)
    if sha256(temporary) != expected:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"Copy checksum mismatch: {source}")
    try:
        # Linking inside one directory is atomic and refuses an existing path.
        # POSIX rename would silently replace that path, which is forbidden.
        os.link(temporary, dest)
    except FileExistsError:
        if sha256(dest) != expected:
            raise ValueError(f"Immutable destination differs: {dest}")
    finally:
        temporary.unlink(missing_ok=True)


def intake(args: argparse.Namespace) -> Path:
    audio = Path(args.audio).expanduser().resolve()
    lyrics = Path(args.lyrics).expanduser().resolve()
    cover = Path(args.cover).expanduser().resolve() if args.cover else None
    timing_path = Path(args.timing).expanduser().resolve() if args.timing else None
    if audio.suffix.lower() not in (".mp3", ".wav", ".flac", ".m4a"):
        raise ValueError("Audio must be MP3, WAV, FLAC, or M4A.")
    for path in (audio, lyrics, cover, timing_path):
        if path and not path.is_file():
            raise FileNotFoundError(path)
    expected = args.expected_sha256.lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("--expected-sha256 needs 64 hex characters.")
    if sha256(audio) != expected:
        raise ValueError("Approved audio SHA-256 mismatch; no intake was written.")
    duration = duration_of(audio)
    lyric_data = read_json(lyrics)
    lines = lyric_lines(lyric_data)
    if lyric_data.get("textStatus") not in ("approved_adapted", "verified_sung"):
        raise ValueError("Lyrics need textStatus='approved_adapted' or 'verified_sung'.")
    timing_data = read_json(timing_path) if timing_path else draft_timing(lines, duration)
    check_timing(timing_data, lines, duration)
    source_hashes = {
        "audio": expected,
        "lyrics": sha256(lyrics),
        "timing": sha256(timing_path) if timing_path else hashlib.sha256(json_bytes(timing_data)).hexdigest(),
        "cover": sha256(cover) if cover else None,
    }
    identity = hashlib.sha256(json_bytes({**source_hashes, "sourceTakeId": args.source_take_id})).hexdigest()[:16]
    folder = INTAKE / identity
    folder.mkdir(parents=True, exist_ok=True)
    safe_copy(audio, folder / f"audio{audio.suffix.lower()}", expected)
    safe_copy(lyrics, folder / "lyrics.json", source_hashes["lyrics"])
    if timing_path:
        safe_copy(timing_path, folder / "timing.json", source_hashes["timing"])
    else:
        target = folder / "timing.json"
        data = json_bytes(timing_data)
        if target.exists() and target.read_bytes() != data:
            raise ValueError("Immutable draft timing file differs.")
        if not target.exists():
            target.write_bytes(data)
    if cover:
        safe_copy(cover, folder / f"cover{cover.suffix.lower()}", source_hashes["cover"])
    manifest = {
        "schemaVersion": 1, "book": "Genesis", "chapter": 4,
        "intakeId": identity, "sourceTakeId": args.source_take_id,
        "sourceUrl": args.source_url or None, "sourceVersionId": args.source_version_id or None,
        "audioFilename": f"audio{audio.suffix.lower()}",
        "coverFilename": f"cover{cover.suffix.lower()}" if cover else None,
        "coverCredit": "Cover image downloaded from the approved Suno song page" if cover else None,
        "coverSourceUrl": (args.source_url or None) if cover else None,
        "durationSeconds": duration, "lineCount": len(lines), "verseCount": 26,
        "timingStatus": timing_data["status"], "sourceHashes": source_hashes,
        "preparedAt": datetime.now(timezone.utc).isoformat(),
        "textStatus": lyric_data["textStatus"],
        "scriptureSource": lyric_data.get("scriptureSource"),
        "sourceArchiveSha256": lyric_data.get("sourceArchiveSha256"),
        "provenanceNote": "Source audio and approved lyric script are immutable; timing may be estimated until checked.",
    }
    manifest_path = folder / "manifest.json"
    if manifest_path.exists():
        prior = read_json(manifest_path)
        for key in ("intakeId", "sourceHashes", "sourceTakeId", "audioFilename"):
            if prior.get(key) != manifest[key]:
                raise ValueError("Immutable intake manifest differs.")
    else:
        manifest_path.write_bytes(json_bytes(manifest))
    print(folder)
    return folder


def phase(verse: int) -> str:
    if verse <= 7:
        return "origin"
    if verse <= 10:
        return "blood"
    if verse <= 15:
        return "exile"
    if verse <= 24:
        return "generations"
    return "hope"


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    paths = {
        "display": FONTS / "ArchivoBlack-Regular.ttf",
        "serif": FONTS / "CormorantGaramond.ttf",
        "condensed": FONTS / "BebasNeue-Regular.ttf",
    }
    return ImageFont.truetype(str(paths[name]), size)


def make_base(size: tuple[int, int], cover: Path | None) -> Image.Image:
    w, h = size
    pad = max(80, int(w * 0.05))
    bw, bh = w + pad * 2, h + pad * 2
    if cover:
        base = ImageOps.fit(Image.open(cover).convert("RGB"), (bw, bh), method=Image.Resampling.LANCZOS)
        base = base.filter(ImageFilter.GaussianBlur(max(5, w // 220)))
        base = Image.blend(base, Image.new("RGB", (bw, bh), (9, 15, 23)), 0.67)
    else:
        base = Image.new("RGB", (bw, bh))
        draw = ImageDraw.Draw(base)
        for y in range(bh):
            p = y / bh
            draw.line((0, y, bw, y), fill=(int(8 + p * 11), int(18 + p * 7), int(28 + p * 4)))
        draw.ellipse((int(bw * .57), -int(bh * .3), int(bw * 1.1), int(bh * .65)), fill=(31, 34, 37))
        draw.ellipse((int(bw * .66), -int(bh * .2), int(bw * 1.0), int(bh * .5)), fill=(22, 26, 32))
    return base


def wrap_words(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    result: list[str] = []
    row = ""
    for word in words:
        candidate = (row + " " + word).strip()
        if row and draw.textbbox((0, 0), candidate, font=face)[2] > max_width:
            result.append(row)
            row = word
        else:
            row = candidate
    if row:
        result.append(row)
    return result


@lru_cache(maxsize=8)
def phrase_sprite(text: str, phase_name: str, width: int) -> Image.Image:
    scale = width / 1920
    box_w = int(width * .77)
    box_h = int(width * .20)
    canvas = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    bold = phase_name in ("blood", "exile")
    face_name = "display" if bold else "serif"
    size = int((68 if bold else 83) * scale)
    face = font(face_name, max(18, size))
    rows = wrap_words(draw, text, face, box_w - int(80 * scale))
    while len(rows) > 3 and size > int(43 * scale):
        size -= max(1, int(4 * scale))
        face = font(face_name, max(16, size))
        rows = wrap_words(draw, text, face, box_w - int(80 * scale))
    leading = int(size * 1.18)
    total_h = len(rows) * leading
    y = max(10, (box_h - total_h) // 2)
    accent = PALETTES[phase_name][0]
    for row in rows:
        bbox = draw.textbbox((0, 0), row, font=face)
        x = (box_w - (bbox[2] - bbox[0])) // 2
        if bold:
            draw.text((x, y), row, font=face, fill=(244, 236, 217, 255), stroke_width=max(1, int(3 * scale)), stroke_fill=(5, 7, 12, 220))
        else:
            draw.text((x, y), row, font=face, fill=(247, 239, 223, 255), stroke_width=max(1, int(2 * scale)), stroke_fill=(7, 10, 16, 220))
        y += leading
    # A short, quiet rule grounds each phrase without turning it into subtitles.
    draw.line((box_w * .40, box_h - int(10 * scale), box_w * .60, box_h - int(10 * scale)), fill=(*accent, 190), width=max(1, int(2 * scale)))
    return canvas


def make_frame(t: float, duration: float, events: list[dict], starts: list[float], base: Image.Image, size: tuple[int, int], draft: bool) -> Image.Image:
    w, h = size
    pad = (base.width - w) // 2
    dx = int(math.sin(t * .035) * pad * .65)
    dy = int(math.cos(t * .024) * pad * .45)
    frame = base.crop((pad + dx, pad + dy, pad + dx + w, pad + dy + h)).convert("RGBA")
    idx = bisect.bisect_right(starts, t) - 1
    event = events[idx] if idx >= 0 and t < events[idx]["end"] else None
    verse = event["verse"] if event else (events[max(0, idx)]["verse"] if events else 1)
    phase_name = phase(verse)
    accent, dark = PALETTES[phase_name]
    tint = Image.new("RGBA", (w, h), (*dark, 64))
    frame = Image.alpha_composite(frame, tint)
    draw = ImageDraw.Draw(frame, "RGBA")
    # Architectural arc and moving horizon make the frame alive even in gaps.
    pulse = .5 + .5 * math.sin(t * 1.7)
    x0, y0 = int(w * .52), int(-h * .65)
    x1, y1 = int(w * 1.20), int(h * .61)
    draw.arc((x0, y0, x1, y1), 45, 315, fill=(*accent, int(70 + 20 * pulse)), width=max(1, int(w * .0015)))
    draw.arc((x0 + 35, y0 + 35, x1 - 35, y1 - 35), 55, 300, fill=(*accent, 28), width=max(1, int(w * .0008)))
    horizon = int(h * .78 + math.sin(t * .16) * h * .012)
    draw.line((int(w * .12), horizon, int(w * .88), horizon), fill=(*accent, 60), width=max(1, int(h * .002)))
    # Deterministic particles: smoke/ash in Cain's middle story, warm dust at its edges.
    for particle in range(28):
        seed = particle * 173 + 41
        x = int((seed * 331 + t * (5 + particle % 8)) % (w + 80)) - 40
        y = int((seed * 151 - t * (7 + particle % 6)) % (h + 70)) - 35
        radius = 1 + particle % 3
        draw.ellipse((x, y, x + radius, y + radius), fill=(*accent, 35 + particle % 5 * 12))
    scale = w / 1920
    small = font("condensed", max(12, int(27 * scale)))
    medium = font("condensed", max(16, int(37 * scale)))
    draw.text((int(w * .08), int(h * .10)), "THE BROTHER'S BLOOD", font=small, fill=(240, 231, 210, 196))
    ref = f"GENESIS  4 : {verse:02d}"
    draw.text((int(w * .08), int(h * .155)), ref, font=medium, fill=(*accent, 242))
    if event:
        start, end = event["start"], event["end"]
        fade = min(1.0, max(0.0, (t - start) / .24), max(0.0, (end - t) / .22))
        sprite = phrase_sprite(event["text"], phase_name, w)
        if fade < 1:
            sprite = sprite.copy()
            alpha = sprite.getchannel("A").point(lambda value: int(value * fade))
            sprite.putalpha(alpha)
        rise = int((1 - min(1, (t - start) / .45)) * 32 * scale)
        px = (w - sprite.width) // 2
        py = int(h * .46) - sprite.height // 2 + rise
        frame.alpha_composite(sprite, (px, py))
    bar_y = int(h * .905)
    draw = ImageDraw.Draw(frame, "RGBA")
    draw.line((int(w * .08), bar_y, int(w * .92), bar_y), fill=(244, 233, 207, 62), width=max(2, int(3 * scale)))
    draw.line((int(w * .08), bar_y, int(w * (.08 + .84 * min(1, t / duration))), bar_y), fill=(*accent, 220), width=max(2, int(4 * scale)))
    draw.text((int(w * .08), int(h * .925)), "THE FOURTH CHAPTER  /  THE FIRST BOOK OF MOSES", font=small, fill=(233, 225, 208, 132))
    if draft:
        draw.text((int(w * .80), int(h * .10)), "TIMING DRAFT", font=small, fill=(255, 206, 120, 220))
    return frame.convert("RGB")


def checked_intake(folder: Path) -> tuple[dict, list[dict], Path, Path | None]:
    manifest = read_json(folder / "manifest.json")
    if manifest.get("chapter") != 4 or manifest.get("book") != "Genesis":
        raise ValueError("Not a Genesis 4 intake.")
    audio = folder / manifest["audioFilename"]
    lyrics = folder / "lyrics.json"
    timing = folder / "timing.json"
    cover = folder / manifest["coverFilename"] if manifest.get("coverFilename") else None
    paths = {"audio": audio, "lyrics": lyrics, "timing": timing, "cover": cover}
    for label, path in paths.items():
        if path and sha256(path) != manifest["sourceHashes"][label]:
            raise ValueError(f"Frozen {label} bytes changed: {path}")
    lines = lyric_lines(read_json(lyrics))
    timing_data = read_json(timing)
    events = check_timing(timing_data, lines, float(manifest["durationSeconds"]))
    return manifest, events, audio, cover


def render(args: argparse.Namespace) -> Path:
    folder = Path(args.intake).expanduser().resolve()
    manifest, events, audio, cover = checked_intake(folder)
    draft = manifest["timingStatus"] == "estimated"
    if draft and not args.allow_draft:
        raise ValueError("Timing is estimated. Use checked line timings, or --allow-draft for a marked preview.")
    width, height = map(int, args.size.lower().split("x"))
    if (width, height) not in ((1920, 1080), (1280, 720), (640, 360)):
        raise ValueError("--size must be 1920x1080, 1280x720, or 640x360.")
    total = float(manifest["durationSeconds"])
    if args.preview_seconds:
        total = min(total, float(args.preview_seconds))
    frames = round(total * VIDEO_FPS)
    out_dir = OUT / manifest["intakeId"] / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6])
    out_dir.mkdir(parents=True, exist_ok=False)
    name = "genesis-4-preview.mp4" if args.preview_seconds else "genesis-4-full.mp4"
    movie = out_dir / name
    partial = out_dir / (name + ".partial.mp4")
    log = out_dir / "ffmpeg.log"
    print(f"Rendering {frames} frames, CPU-only, to {movie}", flush=True)
    command = [
        executable("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{width}x{height}",
        "-framerate", str(VIDEO_FPS), "-i", "pipe:0", "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0", "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.5f}",
        "-movflags", "+faststart", str(partial),
    ]
    base = make_base((width, height), cover)
    starts = [event["start"] for event in events]
    sheet = []
    sample_frames = set(round(x * max(0, frames - 1) / 11) for x in range(12))
    started = time.perf_counter()
    with log.open("wb") as errors:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
        try:
            assert proc.stdin is not None
            for frame_idx in range(frames):
                t = frame_idx / VIDEO_FPS
                image = make_frame(t, float(manifest["durationSeconds"]), events, starts, base, (width, height), draft)
                if frame_idx in sample_frames:
                    thumb = image.copy()
                    thumb.thumbnail((480, 270), Image.Resampling.LANCZOS)
                    sheet.append((t, thumb))
                proc.stdin.write(image.tobytes())
                if frame_idx % (VIDEO_FPS * 10) == 0:
                    print(f"{t:.0f}/{total:.0f}s", flush=True)
            proc.stdin.close()
            code = proc.wait()
        except Exception:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
            proc.kill()
            proc.wait()
            raise
    if code != 0:
        raise RuntimeError(f"ffmpeg failed ({code}); see {log}")
    partial.rename(movie)
    probe = ffprobe(movie)
    video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    song = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)
    actual_duration = float(probe.get("format", {}).get("duration", 0))
    if not video or not song or video.get("width") != width or video.get("height") != height or abs(actual_duration - total) > .15:
        raise RuntimeError("Rendered movie failed stream/duration validation.")
    contact = Image.new("RGB", (480 * 4, 300 * 3), (8, 11, 18))
    draw = ImageDraw.Draw(contact)
    for idx, (sample_t, thumb) in enumerate(sheet):
        x, y = (idx % 4) * 480, (idx // 4) * 300
        contact.paste(thumb, (x, y))
        draw.text((x + 8, y + 274), f"{sample_t:.1f}s", font=font("condensed", 18), fill=(220, 214, 202))
    contact.save(out_dir / "contact-sheet.jpg", quality=90)
    record = {
        "schemaVersion": 1, "sourceIntakeId": manifest["intakeId"],
        "sourceTakeId": manifest["sourceTakeId"], "sourceUrl": manifest.get("sourceUrl"),
        "sourceVersionId": manifest.get("sourceVersionId"),
        "coverCredit": manifest.get("coverCredit"), "coverSourceUrl": manifest.get("coverSourceUrl"),
        "audioSha256": manifest["sourceHashes"]["audio"],
        "lyricsSha256": manifest["sourceHashes"]["lyrics"],
        "timingSha256": manifest["sourceHashes"]["timing"],
        "timingStatus": manifest["timingStatus"],
        "textStatus": manifest["textStatus"],
        "scriptureSource": manifest.get("scriptureSource"),
        "sourceArchiveSha256": manifest.get("sourceArchiveSha256"),
        "coverSha256": manifest["sourceHashes"].get("cover"),
        "videoSha256": sha256(movie), "durationSeconds": actual_duration,
        "width": width, "height": height, "fps": VIDEO_FPS,
        "renderEngine": "Pillow + CPU ffmpeg libx264", "preview": bool(args.preview_seconds),
        "elapsedSeconds": round(time.perf_counter() - started, 2),
        "finishedAt": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "provenance.json").write_bytes(json_bytes(record))
    print(json.dumps({"movie": str(movie), "contactSheet": str(out_dir / "contact-sheet.jpg"), "provenance": str(out_dir / "provenance.json")}, indent=2), flush=True)
    return movie


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("intake", help="freeze reviewed audio, exact sung text, and timings")
    add.add_argument("--audio", required=True)
    add.add_argument("--expected-sha256", required=True)
    add.add_argument("--lyrics", required=True)
    add.add_argument("--timing")
    add.add_argument("--cover")
    add.add_argument("--source-take-id", required=True)
    add.add_argument("--source-url")
    add.add_argument("--source-version-id")
    create = sub.add_parser("render", help="render a prepared Genesis 4 intake on CPU")
    create.add_argument("--intake", required=True)
    create.add_argument("--allow-draft", action="store_true")
    create.add_argument("--preview-seconds", type=float)
    create.add_argument("--size", default="1920x1080")
    args = parser.parse_args()
    if args.command == "intake":
        intake(args)
    else:
        render(args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
