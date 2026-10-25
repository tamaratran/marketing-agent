from marketing_agent.video.edit import captions_from_script


def test_short_clip_drops_lines_instead_of_flashing():
    caps = captions_from_script("hook", ["a", "b", "c", "d"], 5.0)
    assert [c.text for c in caps] == ["hook", "a"]
    assert all(c.end - c.start >= 2.5 for c in caps)


def test_long_clip_keeps_all_lines_at_readable_pace():
    caps = captions_from_script("hook", ["a", "b", "c", "d"], 15.0)
    assert [c.text for c in caps] == ["hook", "a", "b", "c", "d"]
    assert all(c.end - c.start >= 2.5 for c in caps[1:])
    assert caps[-1].end == 15.0


def test_clip_shorter_than_hook_only_shows_hook():
    caps = captions_from_script("hook", ["a"], 2.0)
    assert len(caps) == 1 and caps[0].end == 2.0
