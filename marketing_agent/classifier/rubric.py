"""The video rubric (rubric.toml) as a pydantic model the video model fills in, so the variables
live in one editable list instead of in code."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, create_model

PATH = Path(__file__).with_name("rubric.toml")
KINDS = {"text": str, "bool": bool, "number": float}


@lru_cache
def load(path: Path = PATH) -> dict:
    doc = tomllib.loads(path.read_text())
    keys = [v["key"] for v in doc["variable"]]
    if len(keys) != len(set(keys)):
        raise ValueError("rubric.toml has a duplicate key")
    for v in doc["variable"]:
        if v["kind"] == "choice" and not v.get("options"):
            raise ValueError(f"rubric variable {v['key']} is a choice with no options")
        if v["kind"] not in KINDS and v["kind"] != "choice":
            raise ValueError(f"rubric variable {v['key']} has unknown kind {v['kind']}")
    return doc


def variables(path: Path = PATH) -> list[dict]:
    return load(path)["variable"]


def version(path: Path = PATH) -> int:
    return int(load(path)["version"])


def model(path: Path = PATH):
    fields = {}
    for v in variables(path):
        typ = Literal[tuple(v["options"])] if v["kind"] == "choice" else KINDS[v["kind"]]
        fields[v["key"]] = (typ, Field(description=v["question"]))
    return create_model("Rubric", **fields)
