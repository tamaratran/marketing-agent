from click.testing import CliRunner

from marketing_agent import cli as cli_mod


def test_commands_default_to_campaign(tmp_path, monkeypatch):
    monkeypatch.setenv("MKT_DB", str(tmp_path / "t.sqlite"))
    monkeypatch.setenv("MKT_NICHE", "fitness")
    res = CliRunner().invoke(cli_mod.cli, ["policy"])
    assert res.exit_code == 0, res.output
    assert cli_mod._niche(None) == "fitness"
    assert cli_mod._niche("other") == "other"
    monkeypatch.setenv("MKT_TAGS", "a b")
    assert cli_mod._tags(()) == ["a", "b"]
    assert cli_mod._tags(("c",)) == ["c"]
