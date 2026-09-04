import datetime

from app.workers.demo_seeder import demo_cycle_is_spiking


def _at(seconds_into_epoch: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(seconds_into_epoch, tz=datetime.timezone.utc)


def test_early_in_the_cycle_is_healthy():
    # 60s into a 600s cycle with a 180s spike window at the end --
    # comfortably in the healthy portion.
    assert demo_cycle_is_spiking(_at(60), cycle_seconds=600, spike_seconds=180) is False


def test_just_before_the_spike_window_is_still_healthy():
    # spike starts at cycle_seconds - spike_seconds = 420
    assert demo_cycle_is_spiking(_at(419), cycle_seconds=600, spike_seconds=180) is False


def test_the_exact_boundary_second_is_spiking():
    assert demo_cycle_is_spiking(_at(420), cycle_seconds=600, spike_seconds=180) is True


def test_deep_in_the_spike_window_is_spiking():
    assert demo_cycle_is_spiking(_at(550), cycle_seconds=600, spike_seconds=180) is True


def test_the_cycle_wraps_around_correctly():
    # 1200 = exactly two full 600s cycles -- should land back at phase 0
    assert demo_cycle_is_spiking(_at(1200 + 60), cycle_seconds=600, spike_seconds=180) is False
    assert demo_cycle_is_spiking(_at(1200 + 550), cycle_seconds=600, spike_seconds=180) is True


def test_is_deterministic_for_the_same_moment():
    # Two separate worker processes evaluating the same instant must
    # agree -- this is what makes it safe to run without shared state.
    t = _at(500)
    assert demo_cycle_is_spiking(t, 600, 180) == demo_cycle_is_spiking(t, 600, 180)