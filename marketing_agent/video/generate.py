"""Video generation behind a small provider interface. Default: Seedance 2.0 fast on Replicate
(~$0.08 per second of 720p with native audio). Generation takes 45-90s, so callers should batch."""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import httpx


@dataclass
class GenRequest:
    prompt: str
    duration_s: int = 10
    aspect_ratio: str = "9:16"
    resolution: str = "720p"
    reference_images: list[str] = field(default_factory=list)  # URLs or local paths
    generate_audio: bool = True


@dataclass
class GenResult:
    path: Path
    model: str
    seconds: float
    cost_usd: float
    raw: dict


class VideoProvider:
    def generate(self, req: GenRequest, out: Path) -> GenResult:  # pragma: no cover - interface
        raise NotImplementedError


class ReplicateSeedance(VideoProvider):
    PRICE_PER_S: ClassVar[dict[str, float]] = {
        "bytedance/seedance-2.0-fast": 0.08,
        "bytedance/seedance-2.0": 0.10,
    }

    def __init__(self, model: str = "bytedance/seedance-2.0-fast"):
        if not os.environ.get("REPLICATE_API_TOKEN"):
            raise RuntimeError("REPLICATE_API_TOKEN not set")
        import replicate

        self.client = replicate.Client()
        self.model = model

    def generate(self, req: GenRequest, out: Path) -> GenResult:
        duration = max(-1, min(req.duration_s, 15))  # Replicate schema: -1 (auto) to 15 s
        inputs = {
            "prompt": req.prompt,
            "duration": duration,
            "aspect_ratio": req.aspect_ratio,
            "resolution": req.resolution,
            "generate_audio": req.generate_audio,
        }
        if req.reference_images:
            inputs["reference_images"] = [
                open(p, "rb") if os.path.exists(p) else p for p in req.reference_images
            ]
        t0 = time.time()
        output = self.client.run(self.model, input=inputs)
        url = (
            output.url
            if hasattr(output, "url")
            else str(output[0] if isinstance(output, list) else output)
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with out.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return GenResult(
            path=out,
            model=self.model,
            seconds=round(time.time() - t0, 1),
            cost_usd=round(max(duration, 5) * self.PRICE_PER_S.get(self.model, 0.1), 3),
            raw={"input": {k: v for k, v in inputs.items() if k != "reference_images"}, "url": url},
        )


class StubProvider(VideoProvider):
    """Renders a colour card with ffmpeg so the pipeline runs end to end without any API key."""

    def generate(self, req: GenRequest, out: Path) -> GenResult:
        import subprocess

        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x202830:s=720x1280:d={req.duration_s}:r=24",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=220:duration={req.duration_s}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(out),
            ],
            check=True,
        )
        return GenResult(path=out, model="stub", seconds=0, cost_usd=0, raw={"prompt": req.prompt})


def get_provider(name: str | None = None) -> VideoProvider:
    name = name or os.environ.get("MKT_VIDEO_PROVIDER", "replicate")
    if name == "stub":
        return StubProvider()
    if name == "replicate":
        return ReplicateSeedance(os.environ.get("MKT_VIDEO_MODEL", "bytedance/seedance-2.0-fast"))
    raise ValueError(f"unknown provider {name}")
