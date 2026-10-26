"""With reference images, the video prompt orders the screen to stay on our app for the whole
clip; without them nothing is added."""

from marketing_agent.video.generate import GenRequest, video_prompt


def test_reference_images_pin_the_screen():
    p = video_prompt(
        GenRequest(prompt="She jumps in front of the TV.", reference_images=["a.png", "b.png"])
    )
    assert "@Image1, @Image2" in p
    assert "entire clip" in p and "never switches" in p


def test_no_reference_images_no_screen_rule():
    p = video_prompt(GenRequest(prompt="She jumps."))
    assert "@Image1" not in p and "never switches" not in p
