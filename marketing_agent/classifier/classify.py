"""Frame sampling + transcript + caption context into a multimodal model, strict JSON out.
Context (caption, sound, hashtags) matters: a 499K-view selfie's whole concept was in its caption."""

import base64
import json
import subprocess
import tempfile
import time
from pathlib import Path

from openai import OpenAI

from .schema import PROMPT_VERSION, VideoTags

SYSTEM = """You review short vertical TikTok videos for a marketing team that wants to learn which
formats and hooks earn organic views. You will get frames sampled in order every FRAME_SECONDS
seconds, the audio transcript, and the post context (caption, sound, hashtags). The concept is often
in the caption, not the frames: read both. Return JSON matching the schema exactly."""


def sample_frames(video: Path, every_s: float, width: int, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps=1/{every_s},scale={width}:-2",
            str(out_dir / "f%03d.jpg"),
        ],
        check=True,
    )
    return sorted(out_dir.glob("f*.jpg"))


def transcribe(video: Path, client: OpenAI, model: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        audio = Path(tmp.name)
    r = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-b:a",
            "48k",
            str(audio),
        ],
        check=False,
    )
    if r.returncode != 0 or audio.stat().st_size < 1000:
        return ""
    try:
        with audio.open("rb") as f:
            return client.audio.transcriptions.create(model=model, file=f).text
    except Exception as e:  # videos with no audio stream etc.
        return f"[transcription failed: {e}]"
    finally:
        audio.unlink(missing_ok=True)


def classify(
    video: Path,
    meta: dict,
    model: str = "gpt-5.4",
    transcribe_model: str = "gpt-4o-mini-transcribe",
    every_s: float = 3.0,
    frame_width: int = 360,
    client: OpenAI | None = None,
) -> dict:
    """Return {"tags": VideoTags dict, "run": processing metadata}."""
    client = client or OpenAI()
    t0 = time.time()
    with tempfile.TemporaryDirectory() as d:
        frames = sample_frames(video, every_s, frame_width, Path(d))
        transcript = transcribe(video, client, transcribe_model)
        context = (
            f"Caption: {meta.get('desc', '')}\nSound: {meta.get('music', '')}\n"
            f"Hashtags: {', '.join(meta.get('hashtags') or [])}\nDuration: {meta.get('duration')}s\n"
            f"Transcript: {transcript or '(none)'}\n{len(frames)} frames follow, one every {every_s}s."
        )
        content = [{"type": "input_text", "text": context}]
        for f in frames:
            content.append(
                {
                    "type": "input_image",
                    "detail": "low",
                    "image_url": "data:image/jpeg;base64,"
                    + base64.b64encode(f.read_bytes()).decode(),
                }
            )
    resp = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM.replace("FRAME_SECONDS", str(every_s))},
            {"role": "user", "content": content},
        ],
        text_format=VideoTags,
    )
    tags = resp.output_parsed
    return {
        "tags": tags.model_dump(),
        "run": {
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "latency_s": round(time.time() - t0, 1),
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "transcript": transcript,
            "frame_times": [i * every_s for i in range(len(frames))],
            "raw": json.loads(resp.output_text),
        },
    }
