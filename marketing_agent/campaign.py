"""campaign.toml: the account we post from, the niche we watch, the product we market and how
many clips a cycle makes. The API, `mkt daily` and `mkt devin kickoff` all read it, so the Run
cycle button needs no hidden settings. MKT_* environment variables override single fields
(tests, one-off runs); normally they are unset."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

CAMPAIGN_FILE = Path(
    os.environ.get("MKT_CAMPAIGN", Path(__file__).resolve().parent.parent / "campaign.toml")
)


class Account(BaseModel):
    handle: str = ""
    backup_hashtag: str = ""


class Niche(BaseModel):
    name: str = ""
    hashtags: list[str] = Field(default_factory=list)


class Product(BaseModel):
    name: str = ""
    developer: str = ""
    website: str = ""
    app_store: str = ""
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class Cycle(BaseModel):
    clips: int = 5
    resolution: str = "720p"
    max_acu: int = 10


class Campaign(BaseModel):
    account: Account = Field(default_factory=Account)
    niche: Niche = Field(default_factory=Niche)
    product: Product = Field(default_factory=Product)
    cycle: Cycle = Field(default_factory=Cycle)
    path: str = ""


def _env_list(name: str) -> list[str] | None:
    v = os.environ.get(name)
    return v.split() if v is not None else None


def load(path: Path | str | None = None) -> Campaign:
    p = Path(path or CAMPAIGN_FILE)
    data = tomllib.loads(p.read_text()) if p.exists() else {}
    c = Campaign.model_validate(data)
    c.path = str(p) if p.exists() else ""
    env = os.environ
    c.account.handle = env.get("MKT_ACCOUNT", c.account.handle).lstrip("@").lower()
    c.niche.name = env.get("MKT_NICHE", c.niche.name)
    c.niche.hashtags = _env_list("MKT_TAGS") or c.niche.hashtags
    c.product.description = env.get("MKT_PRODUCT", c.product.description)
    c.product.hashtags = _env_list("MKT_PRODUCT_TAGS") or c.product.hashtags
    c.product.references = _env_list("MKT_REFS") or c.product.references
    c.cycle.clips = int(env.get("MKT_RENDERS", c.cycle.clips))
    c.cycle.resolution = env.get("MKT_RESOLUTION", c.cycle.resolution)
    c.cycle.max_acu = int(env.get("MKT_MAX_ACU", c.cycle.max_acu))
    return c
