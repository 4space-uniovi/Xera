from backend.controllers.led_controller import RGB_LEDS, LedController


def make_sysfs(tmp_path, triggers=None):
    triggers = triggers or {"green:wlan": "none [phy0tx]", "blue:bt": "none [bluetooth-power]"}
    for rgb in RGB_LEDS:
        for name in rgb:
            d = tmp_path / name
            d.mkdir()
            (d / "brightness").write_text("0")
            if name in triggers:
                (d / "trigger").write_text(triggers[name])
    return tmp_path


def val(root, name):
    return (root / name / "brightness").read_text()


def test_green_sets_only_green_channels(tmp_path):
    root = make_sysfs(tmp_path)
    leds = LedController(root)
    assert leds.set_color("green") is True
    for r, g, b in RGB_LEDS:
        assert (val(root, r), val(root, g), val(root, b)) == ("0", "1", "0")
    assert (root / "green:wlan" / "trigger").read_text() == "none"   # sin parpadeo de Wi-Fi


def test_no_rewrite_when_color_unchanged(tmp_path):
    leds = LedController(make_sysfs(tmp_path))
    assert leds.set_color("red") is True
    assert leds.set_color("red") is False


def test_restore_returns_original_triggers(tmp_path):
    root = make_sysfs(tmp_path)
    leds = LedController(root)
    leds.set_color("green")
    leds.restore()
    assert (root / "green:wlan" / "trigger").read_text() == "phy0tx"
    assert (root / "blue:bt" / "trigger").read_text() == "bluetooth-power"
    assert val(root, "green:user") == "0"


def test_no_leds_on_a_pc_is_a_noop(tmp_path):
    leds = LedController(tmp_path / "no-existe")
    assert leds.available is False
    leds.set_color("green")
    leds.restore()


def test_permission_error_disables_leds(tmp_path, monkeypatch):
    root = make_sysfs(tmp_path)
    leds = LedController(root)

    def boom(self, path, value):
        raise PermissionError("denegado")

    monkeypatch.setattr(LedController, "_write", boom)
    assert leds.set_color("green") is False
    assert leds.enabled is False


def test_disabled_in_config_does_nothing(tmp_path):
    root = make_sysfs(tmp_path)
    LedController(root, enabled=False).set_color("green")
    assert val(root, "green:user") == "0"


def test_demo_mode_never_touches_real_leds():
    from backend.config import Settings
    from backend.main import create_app

    app = create_app(Settings(demo=True), "/tmp/_unused_rover.yaml")
    assert app.state.leds.enabled is False
