import sys
import types

import httpx

from marketing_agent.video import generate


class _Fal:
    uploaded = []

    @staticmethod
    def upload(data, content_type):
        _Fal.uploaded.append((len(data), content_type))
        return "https://fal.media/files/x.jpg"

    @staticmethod
    def upload_file(path):
        return "https://fal.media/files/local.jpg"


def test_remote_reference_is_downloaded_and_uploaded(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.setitem(
        sys.modules,
        "fal_client",
        types.SimpleNamespace(upload=_Fal.upload, upload_file=_Fal.upload_file),
    )
    monkeypatch.setattr(
        generate.httpx,
        "get",
        lambda url, **kw: httpx.Response(
            200,
            content=b"\xff\xd8jpg",
            headers={"content-type": "image/jpeg; charset=binary"},
            request=httpx.Request("GET", url),
        ),
    )
    prov = generate.FalSeedance()
    assert (
        prov._url("https://is1-ssl.mzstatic.com/a.png/512x512bb.jpg")
        == "https://fal.media/files/x.jpg"
    )
    assert _Fal.uploaded == [(5, "image/jpeg")]
    local = tmp_path / "ref.jpg"
    local.write_bytes(b"x")
    assert prov._url(str(local)) == "https://fal.media/files/local.jpg"
