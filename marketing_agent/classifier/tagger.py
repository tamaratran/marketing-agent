"""One door for labelling a video, research or ours: Gemini watches the whole clip when a key is
set, otherwise the frames-plus-transcript classifier. Both return {"tags", "run"}; run["model"]
says which one did it."""

from __future__ import annotations

from pathlib import Path

from ..config import settings


def tag_video(video: Path, meta: dict, model: str | None = None, client=None) -> dict:
    if settings.gemini_api_key and not (model and model.startswith("gpt")):
        from .gemini import label_video

        return label_video(
            video, meta, model=model or settings.video_label_model, api_key=settings.gemini_api_key
        )
    from .classify import classify

    return classify(
        video, meta, model or settings.openai_model, settings.transcribe_model, client=client
    )
