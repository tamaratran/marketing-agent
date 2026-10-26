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


def test_hook_label_is_not_burned_in():
    caps = captions_from_script("Text on screen: before vs after", [], 5.0)
    assert caps[0].text == "before vs after"
    assert (
        captions_from_script("POV: you wake up tired", [], 5.0)[0].text == "POV: you wake up tired"
    )


def test_video_prompt_bans_generated_text():
    from marketing_agent.video.generate import GenRequest, video_prompt

    assert "No on-screen text" in video_prompt(GenRequest(prompt="a tired selfie"))


def test_stacked_hook_keeps_its_line_break_when_burned(tmp_path):
    from marketing_agent.video.edit import Caption, drawtext_filters, wrap_lines

    assert wrap_lines("POV: cardio\nfinally got fun", 24) == "POV: cardio\nfinally got fun"
    assert wrap_lines("one line that is much too long for the width", 24) == (
        "one line that is much\ntoo long for the width"
    )
    drawtext_filters([Caption("POV: cardio\nfinally got fun", 0, 6)], tmp_path)
    assert (tmp_path / "cap0.txt").read_text() == "POV: cardio\nfinally got fun"
