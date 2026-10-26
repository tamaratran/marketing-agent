"""Remix a concept to a product: N scripts with a 1-3s hook and the product on screen by 5s,
each scored for 'does this demo visually in 5s'. Weak scripts are dropped before anything is rendered."""

import json
import time

from openai import OpenAI
from pydantic import BaseModel, Field

from ..store import Store


class Script(BaseModel):
    hook: str = Field(description="On-screen text or spoken line for seconds 0-2")
    body: str = Field(
        description="Shot-by-shot script with timestamps, 10-20s total, product visible by 0:05"
    )
    captions: list[str] = Field(
        description="3-5 short on-screen caption lines shown after the hook, in order, under 40 chars each"
    )
    product_reveal_s: float
    demo_score_1_5: int = Field(
        ge=1, le=5, description="Does the product demo visually within 5 seconds?"
    )
    why: str
    video_prompt: str = Field(
        description="Prompt for a text-to-video model, vertical 9:16, with timed beats"
    )
    spoken: str = Field(
        default="",
        description="Everything the person says, verbatim, in order; empty if nobody talks",
    )
    hook_on_screen: bool = Field(
        default=True,
        description="False when the hook is spoken or visual and must not be burned in as text",
    )
    sound: str = Field(
        default="",
        description="TikTok sound to post with, as named in the format; empty if original audio",
    )


class ScriptBatch(BaseModel):
    scripts: list[Script]


PROMPT = """You write TikTok scripts that remix a trending CONCEPT (a format) to a PRODUCT.
Rules: the video_prompt describes picture and sound only; never ask the video model for on-screen text, captions, titles or legible app UI (the captions field is burned in afterwards, generated text renders as gibberish). The hook field is the caption text itself, with no 'Text on screen:' label. 1-3 second hook, product on screen by 5 seconds, 10-20 seconds total, UGC feel (one person,
phone camera, natural light), no brand-ad polish, no em dashes. Cast the person as good-looking in a
real, everyday way: fit, natural skin and hair, a face that could be a friend's; never a flawless
model or an AI-polished look (videos with attractive people do well, ones that look generated do not). Each script must be filmable by one
creator in one take or be generatable by a video model. Vary the hooks across scripts.
Score demo_score_1_5 honestly: 5 means the product's value is obvious on screen within 5s, 1 means it
needs explaining. Write {n} scripts.

CONCEPT: {name}: {description}. Hook pattern: {hook}
PRODUCT: {product}"""


FORMAT_PROMPT = """You write TikTok scripts that CLONE a proven format for a PRODUCT. The format
below was reverse-engineered from the product's best-performing TikToks. Follow it beat for beat:
same opening shot, same hook delivery, same shot order and timings, same pacing (if the sources
speed footage up, say so in the video_prompt), same amount of talking, same amount of on-screen
text. Vary only the words: {n} different hooks and spoken lines, all in the sources' register.
Rules: on_screen text is limited to {text_lines} line(s) of at most {text_words} words each; put
nothing else in `captions`. If hook_delivery is spoken or visual, set hook_on_screen=false and put
the spoken hook in `spoken` and `hook` (it is still the first line a viewer hears). Set `sound` to
"{sound}" on every script. The video_prompt describes picture and sound only; never ask the video
model for on-screen text, titles or legible UI. Total length {duration}s. UGC feel, one person, phone
camera, no brand-ad polish, no em dashes, no explaining the product in text: show it. Cast the person
as good-looking in a real, everyday way: fit, natural skin and hair, a face that could be a friend's;
never a flawless model or an AI-polished look (attractive does well, generated-looking does not). Score
demo_score_1_5 honestly (5 = the product's value is obvious on screen within 5s). Write {n} scripts.

FORMAT: {name}
{summary}
Hook: {hook_delivery}. On screen 0-2s: {hook_shot}
Opening lines the sources used: {hook_examples}
Beats:
{beats}
Pacing: {pacing}
Talking: {talking}
Never: {dont}

PRODUCT: {product}"""


def format_prompt(concept: dict, product: str, n: int, duration: int = 12) -> str:
    sheet = concept["beat_sheet"]
    beats = "\n".join(
        f"  {b['start_s']:.0f}-{b['end_s']:.0f}s: {b['shot']} | audio: {b['audio']}"
        for b in sheet.get("beats", [])
    )
    return FORMAT_PROMPT.format(
        n=n,
        text_lines=sheet.get("on_screen_text_lines", 1),
        text_words=sheet.get("text_budget_words", 6),
        sound=concept.get("sound") or "original audio",
        duration=duration,
        name=sheet.get("name", concept.get("name", "")),
        summary=sheet.get("summary", ""),
        hook_delivery=sheet.get("hook_delivery", ""),
        hook_shot=sheet.get("hook_shot", ""),
        hook_examples=" / ".join(sheet.get("hook_examples", [])[:6]),
        beats=beats,
        pacing=sheet.get("pacing", ""),
        talking=sheet.get("talking", ""),
        dont="; ".join(sheet.get("dont", [])),
        product=product,
    )


def write_scripts(
    store: Store,
    concept: dict,
    product: str,
    n: int = 12,
    min_score: int = 3,
    model: str = "gpt-5.4",
    context: str = "",
) -> list[dict]:
    client = OpenAI()
    if concept.get("beat_sheet"):
        prompt = format_prompt(concept, product, n)
    else:
        prompt = PROMPT.format(
            n=n,
            name=concept["name"],
            description=concept["description"],
            hook=concept.get("hook_pattern", ""),
            product=product,
        )
    resp = client.responses.parse(
        model=model,
        input=[
            {
                "role": "user",
                "content": prompt
                + (
                    f"\n\nWhat has worked so far on this account (scores are log10 views against niche videos of the same age and account size; +1 is 10x):\n{context}\nLean on the winners, avoid the losers, but keep 2-3 scripts that try something else."
                    if context
                    else ""
                ),
            }
        ],
        text_format=ScriptBatch,
    )
    kept = []
    for s in resp.output_parsed.scripts:
        row = s.model_dump()
        if concept.get("beat_sheet"):
            sheet = concept["beat_sheet"]
            row["captions"] = [
                " ".join(c.split()[: sheet.get("text_budget_words", 6)])
                for c in row["captions"][: sheet.get("on_screen_text_lines", 1)]
            ]
            row["sound"] = row["sound"] or concept.get("sound", "")
            row["sound_id"] = concept.get("sound_id", "")
        row["kept"] = s.demo_score_1_5 >= min_score
        row["id"] = store.insert(
            "scripts",
            {
                "concept_id": concept.get("id"),
                "product": product,
                "created_at": int(time.time()),
                "hook": s.hook,
                "body": s.body,
                "demo_score": s.demo_score_1_5,
                "payload": json.dumps(row),
            },
        )
        kept.append(row)
    kept.sort(key=lambda r: -r["demo_score_1_5"])
    return kept
