"""Localization of TLC naive wall-clock time: complete UTC grid, nonexistent and ambiguous local hours."""

from datetime import datetime, timedelta, timezone

from atlas.domains.mobility.aggregate import build_hour_grid, covered_range_utc, month_bounds


def test_month_bounds_roll_over_the_year():
    assert month_bounds("2025-12") == (datetime(2025, 12, 1), datetime(2026, 1, 1))
    assert month_bounds("2025-02") == (datetime(2025, 2, 1), datetime(2025, 3, 1))


def test_plain_month_has_every_hour_once():
    grid = build_hour_grid("2025-01")
    assert len(grid.utc_hours) == 31 * 24
    assert grid.utc_hours[0] == datetime(2025, 1, 1, 5, tzinfo=timezone.utc)  # midnight EST = 05:00Z
    assert grid.local_hours[0] == datetime(2025, 1, 1, 0) and grid.offsets[0] == "-0500"
    assert not any(grid.ambiguous) and grid.nonexistent_local_hours == []
    assert len(set(grid.utc_hours)) == len(grid.utc_hours)


def test_spring_forward_has_one_nonexistent_local_hour_and_no_missing_utc_hour():
    grid = build_hour_grid("2025-03")
    assert len(grid.utc_hours) == 31 * 24 - 1  # 23-hour day
    assert grid.nonexistent_local_hours == [datetime(2025, 3, 9, 2)]
    assert not any(grid.ambiguous)
    # consecutive UTC hours: nothing is skipped on the UTC axis
    step = timedelta(hours=1)
    assert all(b - a == step for a, b in zip(grid.utc_hours, grid.utc_hours[1:], strict=False))
    by_utc = dict(zip(grid.utc_hours, zip(grid.local_hours, grid.offsets, strict=True), strict=True))
    assert by_utc[datetime(2025, 3, 9, 6, tzinfo=timezone.utc)] == (datetime(2025, 3, 9, 1), "-0500")
    assert by_utc[datetime(2025, 3, 9, 7, tzinfo=timezone.utc)] == (datetime(2025, 3, 9, 3), "-0400")


def test_fall_back_has_one_ambiguous_local_hour_mapped_to_two_utc_hours():
    grid = build_hour_grid("2025-11")
    assert len(grid.utc_hours) == 30 * 24 + 1  # 25-hour day
    assert grid.nonexistent_local_hours == []
    assert grid.ambiguous_local_hours == [datetime(2025, 11, 2, 1)]
    flagged = [h for h, amb in zip(grid.utc_hours, grid.ambiguous, strict=True) if amb]
    assert flagged == [datetime(2025, 11, 2, 5, tzinfo=timezone.utc), datetime(2025, 11, 2, 6, tzinfo=timezone.utc)]
    offsets = {o for o, amb in zip(grid.offsets, grid.ambiguous, strict=True) if amb}
    assert offsets == {"-0400", "-0500"}  # the same wall-clock hour under EDT and under EST


def test_covered_range_follows_local_midnights():
    start, end = covered_range_utc(["2025-01", "2025-03"])
    assert start == datetime(2025, 1, 1, 5, tzinfo=timezone.utc)
    assert end == datetime(2025, 4, 1, 4, tzinfo=timezone.utc)  # 2025-04-01 00:00 EDT
