import pytest

from energy_attestation.bridge.cli import plan_estimate

H = 3600
T = 1_761_696_000  # a whole hour


def test_first_estimate_covers_the_last_whole_hour():
    assert plan_estimate(T + 25 * 60, 0, [1.40, 1.50, 1.30]) == (T - H, 60, 1400)


def test_continues_from_chain_tip_and_spans_missed_hours():
    start, minutes, wh = plan_estimate(T + 2 * H + 10, T, [2.0])
    assert (start, minutes, wh) == (T, 120, 4000)


def test_refuses_when_no_whole_hour_has_passed():
    with pytest.raises(ValueError, match="no whole hour"):
        plan_estimate(T + H + 600, T + H, [1.0])


def test_rejects_bad_readings():
    with pytest.raises(ValueError):
        plan_estimate(T + H, 0, [])
    with pytest.raises(ValueError):
        plan_estimate(T + H, 0, [-1])


M = 60


def test_custom_window_first_reading():
    s, e = T + 30 * M, T + 90 * M  # 9:30 to 10:30 style
    readings = [0.777, 1.34, 2.27, 2.32, 2.4, 2.5, 2.6]
    start, minutes, wh = plan_estimate(T + 92 * M, 0, readings, s, e)
    assert (start, minutes) == (s, 60)
    assert wh == round(sum(readings) / len(readings) * 1000)


def test_custom_window_rejects_future_end():
    with pytest.raises(ValueError, match="hasn't happened yet"):
        plan_estimate(T + 80 * M, 0, [1.0], T + 30 * M, T + 90 * M)


def test_custom_start_must_match_tip_once_record_exists():
    with pytest.raises(ValueError, match="continues from"):
        plan_estimate(T + 3 * H, T + H, [1.0], T + 30 * M, T + 2 * H)
    start, minutes, _ = plan_estimate(T + 3 * H, T + H, [1.0], None, T + 2 * H + 15 * M)
    assert (start, minutes) == (T + H, 75)
