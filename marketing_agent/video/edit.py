"""ffmpeg editing: trim/concat clips, burn TikTok-style captions, mix a sound, export 1080x1920 H.264.
A TikTok-library sound cannot be attached via API, so audio is baked in here."""

import json
import re
import shlex
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
# DejaVu has no emoji, so drawtext paints them as empty boxes; script hooks copy TikTok hooks and
# often end in one or two ("After 402 calories 😵💦").
EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f900-\U0001f9ff\u2b00-\u2bff"
    "\ufe0f\u200d\U0001f3fb-\U0001f3ff]+"
)


def drawable(text: str) -> str:
    """Caption text the font can actually render: emoji and their modifiers removed."""
    return re.sub(r"  +", " ", EMOJI_RE.sub("", text)).strip()


def wrap_lines(text: str, width: int) -> str:
    """Wrap each line of text on its own; explicit breaks stay where the script put them."""
    out = []
    for line in text.split("\n"):
        out += textwrap.wrap(line, width) or ([""] if out else [])
    return "\n".join(out).strip("\n")


@dataclass
class Caption:
    text: str
    start: float
    end: float


def drawtext_filters(
    captions: list[Caption], workdir: Path, fontsize: int = 64, wrap: int = 24
) -> str:
    """One drawtext per caption. Text goes through a file so quotes/colons need no escaping and
    long hooks wrap onto several centred lines instead of running off the 1080 px frame. Line
    breaks already in the caption (a hook stacked the way the script split it) are kept, so
    "POV: cardio / finally got fun" is not re-flowed into "POV: cardio finally got / fun"."""
    parts = []
    for i, c in enumerate(captions):
        tf = workdir / f"cap{i}.txt"
        tf.write_text(wrap_lines(drawable(c.text), wrap) or " ")
        parts.append(
            f"drawtext=fontfile={FONT}:textfile={tf}:fontsize={fontsize}:fontcolor=white:"
            f"borderw=4:bordercolor=black:line_spacing=10:x=(w-text_w)/2:y=h*0.68:"
            f"enable='between(t,{c.start},{c.end})'"
        )
    return ",".join(parts)


def assemble(
    clips: list[Path],
    out: Path,
    captions: list[Caption] | None = None,
    sound: Path | None = None,
    sound_gain_db: float = -8,
    max_len_s: float | None = None,
) -> Path:
    """Concat clips, scale/pad to 1080x1920, burn captions, mix optional sound, export H.264/AAC."""
    out.parent.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]
    n = len(clips)
    vchain = "".join(
        f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"setsar=1,fps=30[v{i}];"
        for i in range(n)
    )
    achain = "".join(
        f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}];" for i in range(n)
    )
    concat = "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac];"
    fc = vchain + achain + concat
    vlabel = "[vc]"
    workdir = Path(tempfile.mkdtemp(prefix="mkt-captions-"))
    if captions:
        fc += f"{vlabel}{drawtext_filters(captions, workdir)}[vcap];"
        vlabel = "[vcap]"
    alabel = "[ac]"
    if sound:
        inputs += ["-i", str(sound)]
        fc += f"[{n}:a]volume={sound_gain_db}dB[snd];[ac][snd]amix=inputs=2:duration=first:dropout_transition=2[amix];"
        alabel = "[amix]"
    fc = fc.rstrip(";")
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        *inputs,
        "-filter_complex",
        fc,
        "-map",
        vlabel,
        "-map",
        alabel,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
    ]
    if max_len_s:
        cmd += ["-t", str(max_len_s)]
    cmd.append(str(out))
    subprocess.run(cmd, check=True)
    return out


def probe(path: Path) -> dict:
    """What the file really is: pixels, frame rate, length, codecs, sound or not, size."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    d = json.loads(r.stdout)
    streams = d.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    fmt = d.get("format") or {}
    return {
        "width": v.get("width"),
        "height": v.get("height"),
        "fps": round(float(num) / float(den), 2) if float(den or 0) else None,
        "duration_s": round(float(fmt.get("duration") or 0), 2) or None,
        "video_codec": v.get("codec_name"),
        "audio": a is not None,
        "audio_codec": (a or {}).get("codec_name"),
        "size_bytes": int(fmt.get("size") or 0) or None,
        "bitrate_kbps": round(int(fmt.get("bit_rate") or 0) / 1000) or None,
    }


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(r.stdout.strip())


TIMESTAMP_RE = re.compile(r"^\[?\d+:\d{2}\s*(-|to)\s*\d+:\d{2}\]?\s*")


HOOK_S = 2.5
MIN_LINE_S = 2.5


LABEL_RE = re.compile(
    r"^\s*(text on screen|on-screen text|on screen text|caption|title)\s*:\s*", re.I
)


def strip_label(text: str) -> str:
    """'Text on screen: before vs after' -> 'before vs after'. The label is a stage direction from
    the script writer, not something to burn into the video."""
    return LABEL_RE.sub("", text).strip()


def captions_from_script(hook: str, lines: list[str], total_s: float) -> list[Caption]:
    """Hook on screen first, then the script's other on-screen lines spread over the rest.

    Script lines that are just the hook broken over lines ("POV: I made cardio" + "Subway
    Surfers") are shown as the hook itself, stacked, not replayed one fragment at a time. With
    nothing else to show, the hook stays up for half the clip. Never shows a line for less than
    MIN_LINE_S, so short clips drop trailing lines instead of flashing all of them.
    """
    hook = strip_label(hook).strip()
    lines = [TIMESTAMP_RE.sub("", ln.strip(" -•")) for ln in lines if ln.strip()][:6]
    hook_parts = [ln for ln in lines if hook and ln.lower() in hook.lower()]
    extra = [ln for ln in lines if ln not in hook_parts]
    if hook_parts and " ".join(hook_parts).lower() == hook.lower():
        hook = "\n".join(hook_parts)
    caps = []
    hook_end = min(HOOK_S if extra else total_s / 2, total_s)
    if hook:
        caps.append(Caption(hook, 0, hook_end))
    max_lines = int((total_s - hook_end) // MIN_LINE_S)
    extra = extra[:max_lines]
    if extra:
        step = (total_s - hook_end) / len(extra)
        for i, ln in enumerate(extra):
            caps.append(Caption(ln[:60], hook_end + i * step, hook_end + (i + 1) * step))
    return caps


def shell(cmd: list[str]) -> str:
    return " ".join(shlex.quote(c) for c in cmd)
