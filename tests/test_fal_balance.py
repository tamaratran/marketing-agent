"""The cycle says "needs a top-up" before rendering when fal has locked the account, instead of
failing part-way through the clips."""

import httpx

from marketing_agent.video import generate


class _Resp:
    def __init__(self, status, detail=None):
        self.status_code = status
        self._detail = detail

    def json(self):
        if self._detail is None:
            raise ValueError("no json")
        return {"detail": self._detail}


def test_locked_account_reports_reason(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: _Resp(403, "User is locked. Reason: Exhausted balance")
    )
    assert generate.fal_locked() == "User is locked. Reason: Exhausted balance"


def test_open_account_is_none(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(200, {"token": "t"}))
    assert generate.fal_locked() is None


def test_missing_key(monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    assert generate.fal_locked() == "FAL_KEY not set"
