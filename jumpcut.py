"""Dynamic framing: punch-in zoom cycle that changes on every cut.

Usage: python3 jumpcut.py <video> <transcript.json> <out_video> <out_timemap.json>
         [--mode scenes|pauses] [--scene 0.12] [--zooms 1.0,1.16,1.0,1.3]

mode=scenes (default): cuts = scene changes already in the footage; nothing is removed.
mode=pauses: also cuts at Whisper phrase boundaries and drops silences (ffmpeg silencedetect).
The timemap ([[orig_start, orig_end, new_start], ...]) lets render.py move captions, cards and
b-roll (all authored in ORIGINAL video time) onto the cut timeline.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

W, H = 1080, 1920


def detect_silences(video: str, noise_db: float, min_len: float) -> list[tuple[float, float]]:
    log = subprocess.run(["ffmpeg", "-hide_banner", "-i", video, "-af", f"silencedetect=noise={noise_db}dB:d={min_len}",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(l.split("silence_start: ")[1].split()[0]) for l in log.splitlines() if "silence_start" in l]
    ends = [float(l.split("silence_end: ")[1].split()[0]) for l in log.splitlines() if "silence_end" in l]
    return list(zip(starts, ends))


def detect_scene_cuts(video: str, threshold: float) -> list[float]:
    log = subprocess.run(["ffmpeg", "-hide_banner", "-i", video, "-vf",
                          f"scale=270:-1,select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return [float(l.split("pts_time:")[1].split()[0]) for l in log.splitlines() if "pts_time:" in l]


def scene_shots(cuts: list[float], duration: float) -> list[list[float]]:
    """Keep every frame; only the existing scene cuts become shot boundaries (framing changes there)."""
    b = [0.0] + sorted(cuts) + [duration]
    return [[s, e] for s, e in zip(b, b[1:]) if e - s > 0.04]


def takes(transcript: list[dict], silences, duration: float, keep: float, min_take: float):
    """Split at every phrase boundary and every pause; drop the pause interiors (keeping `keep` s of air)."""
    removed = [(s + keep, e - keep) for s, e in silences if e - s > 2 * keep + 0.04]
    cuts = sorted({round(seg["start"], 3) for seg in transcript[1:]})
    bounds = [0.0]
    for s, e in removed:
        bounds += [s, e]
    bounds += cuts + [duration]
    bounds = sorted(set(bounds))
    pieces = []
    for s, e in zip(bounds, bounds[1:]):
        if any(rs <= s and e <= re for rs, re in removed) or e - s < 0.04:
            continue
        if pieces and (e - s < min_take or pieces[-1][1] - pieces[-1][0] < min_take) and abs(pieces[-1][1] - s) < 1e-3:
            pieces[-1][1] = e  # too short to be its own shot: merge with the previous one
        else:
            pieces.append([s, e])
    return pieces


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("transcript"); ap.add_argument("out"); ap.add_argument("timemap")
    ap.add_argument("--mode", choices=["scenes", "pauses"], default="scenes",
                    help="scenes: change framing only at the cuts already in the footage, no time removed; "
                         "pauses: also cut at phrase boundaries and drop pauses")
    ap.add_argument("--scene", type=float, default=0.12, help="scene-change threshold (mode=scenes)")
    ap.add_argument("--noise", type=float, default=-32, help="silence threshold (dB)")
    ap.add_argument("--min-silence", type=float, default=0.16)
    ap.add_argument("--keep", type=float, default=0.05, help="air kept on each side of a removed pause")
    ap.add_argument("--min-take", type=float, default=1.2, help="shorter shots merge into the previous one")
    ap.add_argument("--zooms", default="1.0,1.16,1.0,1.3", help="punch-in cycle applied shot by shot")
    ap.add_argument("--focus", default="540,760", help="point kept fixed when zooming (face)")
    a = ap.parse_args()

    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                a.video], capture_output=True, text=True, check=True).stdout)
    if a.mode == "scenes":
        segs = scene_shots(detect_scene_cuts(a.video, a.scene), dur)
    else:
        silences = detect_silences(a.video, a.noise, a.min_silence)
        segs = takes(json.loads(Path(a.transcript).read_text()), silences, dur, a.keep, a.min_take)
    zooms = [float(z) for z in a.zooms.split(",")]
    fx, fy = (float(v) for v in a.focus.split(","))

    parts, labels, tmap, t_new = [], [], [], 0.0
    for i, (s, e) in enumerate(segs):
        z = zooms[i % len(zooms)]
        cw, ch = round(W / z / 2) * 2, round(H / z / 2) * 2
        cx, cy = round(fx * (1 - 1 / z)), round(fy * (1 - 1 / z))
        fade = min(0.012, (e - s) / 4)
        parts.append(f"[0:v]trim={s:.3f}:{e:.3f},setpts=PTS-STARTPTS,crop={cw}:{ch}:{cx}:{cy},"
                     f"scale={W}:{H}:flags=lanczos,setsar=1,fps=30[v{i}];"
                     f"[0:a]atrim={s:.3f}:{e:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={fade:.3f},afade=t=out:st={e - s - fade:.3f}:d={fade:.3f}[a{i}];")
        labels.append(f"[v{i}][a{i}]")
        tmap.append([round(s, 3), round(e, 3), round(t_new, 3)])
        t_new += e - s
    graph = "".join(parts) + "".join(labels) + f"concat=n={len(segs)}:v=1:a=1[v][a]"

    script = Path(a.out).with_suffix(".filter.txt")
    script.write_text(graph)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.video, "-filter_complex_script", str(script),
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", a.out], check=True)
    script.unlink()
    Path(a.timemap).write_text(json.dumps(tmap))
    print(f"{len(segs)} shots · {dur:.1f}s -> {t_new:.1f}s ({dur - t_new:.1f}s of pauses removed)")


if __name__ == "__main__":
    main()
