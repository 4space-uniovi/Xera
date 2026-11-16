import pytest
from pydantic import ValidationError

from backend.config import Settings, load_settings, merge_settings, save_settings


def test_defaults_when_file_missing(tmp_path):
    s = load_settings(tmp_path / "nope.yaml")
    assert s.motion.max_speed == 60 and s.motion.watchdog_ms == 300 and s.camera.width == 640


def test_roundtrip(tmp_path):
    p = tmp_path / "sub" / "rover.yaml"
    s = merge_settings(Settings(), {"rover": {"name": "R2"}, "serial": {"baudrate": 9600}})
    save_settings(s, p)
    assert load_settings(p) == s


def test_example_file_is_valid():
    from backend.config import EXAMPLE_CONFIG_PATH
    load_settings(EXAMPLE_CONFIG_PATH)


@pytest.mark.parametrize("patch", [{"motion": {"max_speed": 19}}, {"wifi": {"password": "x"}}, {"bogus": 1}])
def test_invalid_patch(patch):
    with pytest.raises(ValidationError):
        merge_settings(Settings(), patch)
