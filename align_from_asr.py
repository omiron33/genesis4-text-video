#!/usr/bin/env python3
"""Make a provisional Genesis 4 line timeline from ASR segments and reviewed verse windows.

This does not certify sung words or exact consonant boundaries. It uses the
approved lyric script and ASR text only to place display phrases in time.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from pathlib import Path

from genesis4_video import json_bytes, lyric_lines

VERSE_WINDOWS = [
    (0, 27.2), (27.2, 38), (38, 44), (44, 55), (55, 67), (67, 77),
    (77, 92), (92, 102), (102, 114), (114, 122), (122, 130),
    (130, 144), (148, 156), (156, 169), (169, 184), (194.6, 201),
    (203.1, 211.4), (212, 221.8), (221.8, 225.6), (225.6, 229.9), (229.9, 234.1),
    (234.1, 240), (240, 253), (253, 265), (267.2, 286), (286.9, 299),
]


def tokens(text: str) -> list[str]:
    return [x.casefold() for x in re.findall(r"[^\W_]+(?:['’][^\W_]+)?", text, re.UNICODE)]


def allocate_line_boundaries(lines: list[dict], asr: list[dict], start: float, end: float) -> list[float]:
    words = [tokens(line["text"]) for line in lines]
    flat = [token for row in words for token in row]
    if not flat:
        raise ValueError("Empty lyric verse.")
    segments = [segment for segment in asr if float(segment["start"]) < end and float(segment["end"]) > start]
    transcript: list[str] = []
    transcript_times: list[float] = []
    for segment in segments:
        row = tokens(segment["text"])
        a, b = max(start, float(segment["start"])), min(end, float(segment["end"]))
        for i, token in enumerate(row):
            transcript.append(token)
            transcript_times.append(a + (i + .5) * (b - a) / max(1, len(row)))
    mapped: dict[int, float] = {}
    if transcript:
        matcher = difflib.SequenceMatcher(None, flat, transcript, autojunk=False)
        for a, b, n in matcher.get_matching_blocks():
            for i in range(n):
                mapped[a + i] = transcript_times[b + i]
    known = [(-1, start), *sorted(mapped.items()), (len(flat), end)]
    positions = [0.0] * len(flat)
    for (i0, t0), (i1, t1) in zip(known, known[1:]):
        for index in range(max(0, i0), min(len(flat), i1 + 1)):
            if index in mapped:
                positions[index] = mapped[index]
            elif i1 > i0:
                positions[index] = t0 + (index - i0) * (t1 - t0) / (i1 - i0)
    # ASR matches occasionally cross under repeated words. Restore chronology.
    for i in range(1, len(positions)):
        positions[i] = max(positions[i], positions[i - 1] + .001)
    boundaries = [start]
    offset = 0
    for row in words[:-1]:
        offset += len(row)
        cut = (positions[offset - 1] + positions[offset]) / 2
        boundaries.append(max(boundaries[-1] + .15, min(end - .15, cut)))
    boundaries.append(end)
    return boundaries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lyrics", required=True)
    parser.add_argument("--base-asr", required=True)
    parser.add_argument("--tiny-asr")
    parser.add_argument("--word-asr", help="full-song CPU word-timestamp JSON used to audit anchor times")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    lyrics_file = Path(args.lyrics)
    base_file = Path(args.base_asr)
    tiny_file = Path(args.tiny_asr) if args.tiny_asr else None
    word_file = Path(args.word_asr) if args.word_asr else None
    lines = lyric_lines(json.loads(lyrics_file.read_text(encoding="utf-8")))
    asr = json.loads(base_file.read_text(encoding="utf-8"))["segments"]
    out = []
    for verse in range(1, 27):
        group = [line for line in lines if line["verse"] == verse]
        start, end = VERSE_WINDOWS[verse - 1]
        bounds = allocate_line_boundaries(group, asr, start, end)
        if verse == 1:
            # The full-song base.en first segment spuriously spans 0–16s.
            # A focused CPU word-timestamp pass on the original 0–30s WAV
            # locates the first audible vocal at 11.42s, then 15.76s/22.8s.
            bounds = [11.42, 15.76, 22.8, 27.2]
        elif verse == 2:
            # "Again she bore" starts within the ASR 26–30s segment,
            # before its "his brother Abel" segment at 30–32s.
            bounds = [27.2, 32.0, 35.0, 38.0]
        elif verse == 25:
            bounds = [267.2, 271.9, 275.1, 280.2, 286.0]
        elif verse == 17:
            bounds = [203.1, 205.3, 208.8, 209.8, 211.4]
        elif verse == 12:
            bounds = [130.0, 132.96, 136.14, 138.4, 144.0]
        elif verse == 19:
            bounds = [221.8, 222.9, 224.7, 225.6]
        elif verse == 20:
            bounds = [225.6, 226.7, 228.7, 229.9]
        elif verse == 21:
            bounds = [229.9, 231.5, 233.3, 234.1]
        elif verse == 22:
            bounds = [234.1, 235.2, 237.5, 240.0]
        elif verse == 26:
            bounds = [286.9, 290.0, 293.4, 295.0, 299.0]
        for line, a, b in zip(group, bounds, bounds[1:]):
            out.append({**line, "start": round(a, 3), "end": round(b, 3)})
    # Focused CPU ASR crops agree there are no words from 299–312s. Full-song
    # ASR's conflicting late "repeat"/"thank you" results were hallucinations.
    evidence = {
        "method": "ASR segment windows plus in-segment token interpolation; not human-aligned",
        "baseAsrSha256": hashlib.sha256(base_file.read_bytes()).hexdigest(),
        "tinyAsrSha256": hashlib.sha256(tiny_file.read_bytes()).hexdigest() if tiny_file else None,
        "wordAsrSha256": hashlib.sha256(word_file.read_bytes()).hexdigest() if word_file else None,
        "openingAnchor": "Focused CPU base.en word timestamps on original audio: first vocal 11.42s, next phrase 15.76s, third phrase 22.8s, verse 2 begins about 27.2s. The 0–11.42s interval is instrumental.",
        "knownUncertainty": "Proper names and phrase seams may differ by 1–3s. Focused tiny.en and base.en crops find no sung words at 299–312s; outro is treated as instrumental. No direct human listening alignment is claimed.",
    }
    result = {"status": "machine_aligned", "alignmentEvidence": evidence, "segments": out}
    Path(args.output).write_bytes(json_bytes(result))
    print(f"wrote {args.output}: {len(out)} timed phrases across 26 verses")


if __name__ == "__main__":
    main()
