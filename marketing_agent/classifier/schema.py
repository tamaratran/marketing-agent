from typing import Literal

from pydantic import BaseModel, Field

PROMPT_VERSION = "v2"  # v2: beats

HookType = Literal[
    "question",
    "bold_claim",
    "pov",
    "text_on_screen",
    "visual_surprise",
    "storytime",
    "tutorial",
    "before_after",
    "other",
]
VisualStyle = Literal[
    "realistic_footage", "screen_recording", "animation", "talking_head", "ugc_selfie", "mixed"
]
MusicRole = Literal["none", "background", "beat_synced", "trend_sound", "voiceover_only"]


class Beat(BaseModel):
    t_s: float = Field(description="Seconds from the start")
    what: str = Field(
        description="What happens on screen and in the audio at that moment, one line"
    )


class VideoTags(BaseModel):
    hook_type: HookType
    hook_text: str = Field(description="What the viewer reads or hears in the first 2 seconds")
    seconds_until_main_subject: float
    visual_style: VisualStyle
    has_voiceover: bool
    has_on_screen_captions: bool
    caption_style: str
    music_role: MusicRole
    pacing_cuts_per_10s: float = Field(description="Estimated number of cuts per 10 seconds")
    concept: str = Field(description="One sentence: the reusable format, not the topic")
    topic: str = Field(description="What the video is about, a few words")
    product_or_brand_visible: bool
    product_on_screen_by_5s: bool
    cta: str = Field(description="Call to action if any, else empty")
    quality_issues: list[str]
    demo_score_1_5: int = Field(
        ge=1, le=5, description="Could a product be shown convincingly in this format within 5s?"
    )
    concept_confidence_0_1: float = Field(ge=0, le=1)
    summary: str
    beats: list[Beat] = Field(
        default_factory=list,
        description="2 to 6 beats, in order: what the viewer sees and hears, like a shot list",
    )
