"""Video generation behind a small provider interface. Default: Seedance 2.5 on fal.ai
(newest Seedance; ~$0.22/s at 480p, $0.47/s at 720p). Replicate Seedance 2.0 fast is the cheap
fallback (~$0.08/s). Generation takes 45-120 s per clip, so callers should batch."""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import httpx

NO_TEXT = (
    " No on-screen text, captions, subtitles, titles, logos or watermarks anywhere in the frame;"
    " any phone or app screen shows simple shapes and numbers only, no legible words."
    " Captions are added afterwards."
)


CASTING = (
    " The person is good-looking in a real, everyday way: fit, natural skin texture, a few stray"
    " hairs, ordinary clothes, phone-camera light; not a flawless model, not airbrushed, nothing"
    " that reads as AI-generated."
)


def video_prompt(req: "GenRequest") -> str:
    """The model prompt: the script's beats, a casting note (attractive but natural; polished
    AI-looking people underperform) and a standing ban on generated text, because the editor
    burns the real captions in and generated text comes out as gibberish."""
    return req.prompt.rstrip() + CASTING + NO_TEXT


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
            "prompt": video_prompt(req),
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


def fal_locked() -> str | None:
    """Why fal would refuse a render right now, or None. fal locks the whole account when the
    balance is exhausted and every call then fails with 403 'User is locked. Reason: Exhausted
    balance'; the storage token endpoint shows that without rendering (or paying) anything."""
    key = os.environ.get("FAL_KEY")
    if not key:
        return "FAL_KEY not set"
    try:
        r = httpx.post(
            "https://rest.fal.ai/storage/auth/token",
            params={"storage_type": "fal-cdn-v3"},
            headers={"Authorization": f"Key {key}"},
            timeout=30,
        )
    except httpx.HTTPError as e:
        return f"fal unreachable: {e}"
    if r.status_code < 400:
        return None
    try:
        detail = r.json().get("detail")
    except ValueError:
        detail = None
    return str(detail or f"fal {r.status_code}")


class FalSeedance(VideoProvider):
    """Seedance on fal.ai (newest version: 2.5, US-hosted). 4-30 s or auto duration, 480p/720p/1080p,
    9:16, synchronized audio with lip-synced speech. Reference images/videos/audio switch the endpoint
    to reference-to-video; refer to them in the prompt as @Image1, @Video1, @Audio1."""

    PRICE_PER_S: ClassVar[dict[str, float]] = {"480p": 0.2205, "720p": 0.473, "1080p": 0.80}

    def __init__(self, model: str = "bytedance/seedance-2.5/us"):
        if not os.environ.get("FAL_KEY"):
            raise RuntimeError("FAL_KEY not set")
        import fal_client

        self.fal = fal_client
        self.model = model.rstrip("/")

    def _url(self, ref: str) -> str:
        """Every reference goes up to fal's own storage. fal fetches remote URLs itself and
        rejects some hosts (App Store mzstatic images: 'not accessible or has expired'), so a URL
        is downloaded here and uploaded like a local file."""
        if os.path.exists(ref):
            return self.fal.upload_file(ref)
        r = httpx.get(ref, follow_redirects=True, timeout=60)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "image/jpeg").split(";")[0]
        return self.fal.upload(r.content, content_type=ctype)

    def generate(self, req: GenRequest, out: Path) -> GenResult:
        duration = "auto" if req.duration_s < 0 else str(max(4, min(req.duration_s, 30)))
        args: dict = {
            "prompt": video_prompt(req),
            "duration": duration,
            "aspect_ratio": req.aspect_ratio,
            "resolution": req.resolution,
            "generate_audio": req.generate_audio,
        }
        endpoint = f"{self.model}/text-to-video"
        if req.reference_images:
            endpoint = f"{self.model}/reference-to-video"
            args["image_urls"] = [self._url(p) for p in req.reference_images]
        t0 = time.time()
        result = self.fal.subscribe(endpoint, arguments=args, with_logs=False)
        url = result["video"]["url"]
        out.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as r:
            r.raise_for_status()
            with out.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        secs = req.duration_s if req.duration_s > 0 else 5
        return GenResult(
            path=out,
            model=endpoint,
            seconds=round(time.time() - t0, 1),
            cost_usd=round(secs * self.PRICE_PER_S.get(req.resolution, 0.5), 3),
            raw={"input": {k: v for k, v in args.items() if k != "image_urls"}, "result": result},
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
    name = name or os.environ.get("MKT_VIDEO_PROVIDER", "fal")
    if name == "stub":
        return StubProvider()
    if name == "fal":
        return FalSeedance(os.environ.get("MKT_VIDEO_MODEL", "bytedance/seedance-2.5/us"))
    if name == "replicate":
        return ReplicateSeedance(
            os.environ.get("MKT_REPLICATE_MODEL", "bytedance/seedance-2.0-fast")
        )
    raise ValueError(f"unknown provider {name}")
