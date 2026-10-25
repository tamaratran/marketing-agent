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
    product_reveal_s: float
    demo_score_1_5: int = Field(
        ge=1, le=5, description="Does the product demo visually within 5 seconds?"
    )
    why: str
    video_prompt: str = Field(
        description="Prompt for a text-to-video model, vertical 9:16, with timed beats"
    )


class ScriptBatch(BaseModel):
    scripts: list[Script]


PROMPT = """You write TikTok scripts that remix a trending CONCEPT (a format) to a PRODUCT.
Rules: 1-3 second hook, product on screen by 5 seconds, 10-20 seconds total, UGC feel (one person,
phone camera, natural light), no brand-ad polish, no em dashes. Each script must be filmable by one
creator in one take or be generatable by a video model. Vary the hooks across scripts.
Score demo_score_1_5 honestly: 5 means the product's value is obvious on screen within 5s, 1 means it
needs explaining. Write {n} scripts.

CONCEPT: {name}: {description}. Hook pattern: {hook}
PRODUCT: {product}"""


def write_scripts(
    store: Store,
    concept: dict,
    product: str,
    n: int = 12,
    min_score: int = 3,
    model: str = "gpt-5.4",
) -> list[dict]:
    client = OpenAI()
    resp = client.responses.parse(
        model=model,
        input=[
            {
                "role": "user",
                "content": PROMPT.format(
                    n=n,
                    name=concept["name"],
                    description=concept["description"],
                    hook=concept.get("hook_pattern", ""),
                    product=product,
                ),
            }
        ],
        text_format=ScriptBatch,
    )
    kept = []
    for s in resp.output_parsed.scripts:
        row = s.model_dump()
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
