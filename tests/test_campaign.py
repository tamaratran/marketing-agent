from marketing_agent import campaign


def test_repo_campaign_file_is_complete():
    """The checked-in campaign.toml is what the Run cycle button runs: it must name the account,
    the niche, the product and its TikToks, and the reference images."""
    c = campaign.load()
    assert c.path.endswith("campaign.toml")
    assert c.account.handle == "kriscaroll"
    assert c.niche.name and c.niche.hashtags
    assert c.product.name and c.product.description and c.product.hashtags
    assert len(c.product.references) >= 1
    assert c.cycle.clips >= 1 and c.cycle.resolution in {"480p", "720p", "1080p"}


def test_missing_file_falls_back_to_defaults(tmp_path):
    c = campaign.load(tmp_path / "none.toml")
    assert c.path == "" and c.niche.name == "" and c.account.handle == ""


def test_env_overrides_single_fields(tmp_path, monkeypatch):
    (tmp_path / "c.toml").write_text(
        '[account]\nhandle = "@Someone"\n[niche]\nname = "pets"\nhashtags = ["dogs"]\n'
        '[product]\ndescription = "a leash"\n[cycle]\nclips = 2\n'
    )
    monkeypatch.setenv("MKT_RESOLUTION", "1080p")
    monkeypatch.setenv("MKT_TAGS", "cats kittens")
    c = campaign.load(tmp_path / "c.toml")
    assert c.account.handle == "someone"
    assert c.niche.name == "pets" and c.niche.hashtags == ["cats", "kittens"]
    assert c.product.description == "a leash"
    assert c.cycle.clips == 2 and c.cycle.resolution == "1080p"
