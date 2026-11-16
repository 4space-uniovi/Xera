import pytest

from backend.motion import sanitize_xy, scale_speed


# --- conversión y límites ---------------------------------------------------
@pytest.mark.parametrize("x,y,expected", [(0, 0, (0, 0)), (150, -150, (100, -100)), (12.4, 99.6, (12, 100))])
def test_sanitize_clamps(x, y, expected):
    assert sanitize_xy(x, y) == expected


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "10", None, True, [1]])
def test_sanitize_rejects_garbage(bad):
    with pytest.raises(ValueError):
        sanitize_xy(bad, 0)


@pytest.mark.parametrize("x,y,pct,expected", [(100, -100, 50, (50, -50)), (100, 100, 20, (20, 20)), (7, 0, 100, (7, 0))])
def test_scale_speed(x, y, pct, expected):
    assert scale_speed(x, y, pct) == expected


def test_max_speed_applied_to_output(motion, esp):
    motion.set_max_speed(40)
    motion.connect("a")
    motion.request_control("a")
    motion.move("a", 100, -50)
    assert esp.transport.last == (40, -20)


# --- control exclusivo ------------------------------------------------------
def test_only_one_owner(motion):
    motion.connect("a"); motion.connect("b")
    assert motion.request_control("a") is True
    assert motion.request_control("b") is False
    assert motion.request_control("a") is True  # idempotente para el dueño


def test_non_owner_cannot_move(motion, esp):
    motion.connect("a"); motion.connect("b")
    motion.request_control("a")
    assert motion.move("b", 50, 50) is False
    assert len(esp.transport.frames) == 0


def test_release_stops_and_frees(motion, esp):
    motion.connect("a"); motion.connect("b")
    motion.request_control("a")
    motion.move("a", 50, 50)
    assert motion.release_control("a") is True
    assert esp.transport.last == (0, 0)
    assert motion.request_control("b") is True


def test_owner_disconnect_sends_stop(motion, esp):
    motion.connect("a")
    motion.request_control("a")
    motion.move("a", 80, 80)
    motion.disconnect("a")
    assert motion.owner is None
    assert esp.transport.last == (0, 0)


def test_spectator_disconnect_does_not_stop_owner(motion, esp):
    motion.connect("a"); motion.connect("b")
    motion.request_control("a")
    motion.move("a", 80, 80)
    motion.disconnect("b")
    assert esp.transport.last == (80, 80)


def test_anyone_can_stop(motion, esp):
    motion.connect("a"); motion.connect("b")
    motion.request_control("a")
    motion.move("a", 80, 80)
    motion.stop("b")
    assert esp.transport.last == (0, 0)


def test_unknown_client_cannot_take_control(motion):
    assert motion.request_control("ghost") is False


# --- watchdog ---------------------------------------------------------------
def test_watchdog_stops_after_300ms(motion, esp, clock):
    motion.connect("a")
    motion.request_control("a")
    motion.move("a", 60, 60)
    clock.advance(0.25)
    motion.check()
    assert esp.transport.last == (60, 60)  # aún dentro del plazo
    clock.advance(0.1)
    motion.check()
    assert esp.transport.last == (0, 0)
    assert motion.watchdog_trips == 1


def test_watchdog_fed_by_commands(motion, esp, clock):
    motion.connect("a")
    motion.request_control("a")
    for _ in range(10):
        motion.move("a", 60, 60)
        clock.advance(0.05)
        motion.check()
    assert esp.transport.last == (60, 60)
    assert motion.watchdog_trips == 0


def test_invalid_commands_do_not_feed_watchdog(motion, esp, clock):
    motion.connect("a")
    motion.request_control("a")
    motion.move("a", 60, 60)
    clock.advance(0.2)
    assert motion.move("a", float("nan"), 0) is False
    clock.advance(0.2)
    motion.check()
    assert esp.transport.last == (0, 0)


def test_watchdog_does_not_spam_when_already_stopped(motion, esp, clock):
    motion.connect("a")
    motion.request_control("a")
    motion.move("a", 0, 0)
    n = len(esp.transport.frames)
    clock.advance(1)
    motion.check()
    assert len(esp.transport.frames) == n
    assert motion.watchdog_trips == 0


def test_idle_owner_loses_control(motion, esp, clock):
    motion.connect("a"); motion.connect("b")
    motion.request_control("a")
    clock.advance(6)
    motion.check()
    assert motion.owner is None
    assert motion.request_control("b") is True
