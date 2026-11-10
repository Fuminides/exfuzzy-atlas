"""Contract v0.5 data summary: dedup, binning with the convention of ``classify_observed``, local-time groups."""

import duckdb
import pandas as pd
import pytest

from atlas.contracts import models as m
from atlas.services.summary import SummaryError, classes_for, compute_summary

SCHEME = m.TargetScheme(
    name="EAQI-like", source_url="https://example.org/scheme", unit="ug/m3", boundary="upper_inclusive",
    kind=m.SchemeKind.OFFICIAL_INDEX,
    classes=[
        m.TargetClass(label="Good", lower=None, upper=10),
        m.TargetClass(label="Fair", lower=10, upper=25),
        m.TargetClass(label="Moderate", lower=25, upper=60),
        m.TargetClass(label="Poor or worse", lower=60, upper=None),  # the merged, open top class
    ],
)
LABELS = [c.label for c in SCHEME.classes]


def run(tmp_path, rows, scheme=SCHEME, tz="Europe/Madrid", entity_ids=("A", "B"), **extra):
    """``rows``: (entity, valid_at, value[, issued_at]) tuples; the issue time defaults to valid - 6 h."""
    def utc(value):
        stamp = pd.Timestamp(value)
        return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")

    table = pd.DataFrame([{
        "entity_id": r[0], "valid_at_utc": utc(r[1]), "target": r[2],
        "issued_at_utc": utc(r[3]) if len(r) > 3 else utc(r[1]) - pd.Timedelta(hours=6),
    } for r in rows])
    path = tmp_path / "features.parquet"
    table.to_parquet(path, index=False)
    con = duckdb.connect(config={"threads": 1})
    con.execute("SET TimeZone='UTC'")
    args = dict(
        source=str(path), task_id="t", domain=m.Domain.AIR, variable="no2", label="NO₂ horario observado",
        unit="ug/m3", column="target", time_column="valid_at_utc", horizon_hours=6, entity_ids=list(entity_ids),
        timezone=tz, scheme=scheme, data_version="v", synthetic=True,
    )
    return compute_summary(con, **{**args, **extra})


def shares_of(response, group="all", key="all"):
    row = next(r for r in response.groups[group] if r.key == key)
    return row.n, dict(zip(LABELS, row.shares, strict=True))


def test_values_on_the_boundaries_follow_the_classifier_convention(tmp_path):
    # rounded half up to whole numbers, then the first class whose upper bound is not below the value
    cases = {10.0: "Good", 10.4: "Good", 10.5: "Fair", 25.0: "Fair", 25.4: "Fair", 25.5: "Moderate",
             60.0: "Moderate", 60.4: "Moderate", 60.5: "Poor or worse", 1000.0: "Poor or worse", 0.0: "Good",
             -0.4: "Good", 5.0: "Good"}
    rows = [("A", pd.Timestamp("2025-03-01T00:00Z") + pd.Timedelta(hours=i), v) for i, v in enumerate(cases)]
    response = run(tmp_path, rows)
    n, shares = shares_of(response)
    assert n == len(cases)
    for label in LABELS:
        assert shares[label] == pytest.approx(sum(1 for c in cases.values() if c == label) / len(cases))
    assert [c.label for c in response.classes] == LABELS
    assert response.groups[m.SummaryGroup.ALL][0].quantiles is None


def test_the_open_top_class_takes_everything_above_and_a_closed_scheme_leaves_values_outside(tmp_path):
    rows = [("A", "2025-03-01T00:00Z", 61.0), ("A", "2025-03-01T01:00Z", 99999.0)]
    assert shares_of(run(tmp_path, rows))[1]["Poor or worse"] == 1.0
    closed = SCHEME.model_copy(update={"classes": [*SCHEME.classes[:3], m.TargetClass(
        label="Poor or worse", lower=60, upper=100)]})
    response = run(tmp_path, [*rows, ("A", "2025-03-01T02:00Z", 30.0)], scheme=closed)
    n, shares = shares_of(response)
    assert n == 2 and shares["Moderate"] == 0.5 and shares["Poor or worse"] == 0.5  # 99999 is outside, not binned
    assert any("fuera de las clases" in text for text in response.notes)


def test_each_observed_value_counts_once_per_entity_and_time(tmp_path):
    # two issue times (rows) that observe the same value of the same entity at the same valid time
    rows = [("A", "2025-03-01T06:00Z", 8.0, "2025-03-01T00:00Z"), ("A", "2025-03-01T06:00Z", 8.0, "2025-03-01T01:00Z"),
            ("A", "2025-03-01T07:00Z", 30.0), ("B", "2025-03-01T06:00Z", 8.0)]
    response = run(tmp_path, rows)
    assert response.groups[m.SummaryGroup.ALL][0].n == 3
    by_entity = {r.key: r.n for r in response.groups[m.SummaryGroup.ENTITY]}
    assert by_entity == {"A": 2, "B": 1}


def test_two_different_values_for_one_entity_and_time_are_an_error(tmp_path):
    rows = [("A", "2025-03-01T06:00Z", 8.0, "2025-03-01T00:00Z"), ("A", "2025-03-01T06:00Z", 9.0, "2025-03-01T01:00Z")]
    with pytest.raises(SummaryError, match="different observed values"):
        run(tmp_path, rows)


def test_month_hour_and_weekday_are_local_and_entities_outside_the_model_are_left_out(tmp_path):
    rows = [
        ("A", "2025-01-01T23:30Z", 5.0),   # UTC+1: 2025-01-02 00:30 local, a Thursday
        ("A", "2025-07-01T22:30Z", 5.0),   # UTC+2: 2025-07-02 00:30 local, a Wednesday
        ("A", "2025-07-01T12:00Z", 5.0),   # 14:00 local, a Tuesday
        ("Z", "2025-07-01T12:00Z", 5.0),   # not a published entity
    ]
    response = run(tmp_path, rows)
    keys = lambda g: {r.key: r.n for r in response.groups[g]}  # noqa: E731
    assert keys(m.SummaryGroup.ALL) == {"all": 3}
    assert keys(m.SummaryGroup.YEAR) == {"2025": 3}
    assert keys(m.SummaryGroup.MONTH) == {"01": 1, "07": 2}
    assert keys(m.SummaryGroup.HOUR) == {"00": 2, "14": 1}
    assert keys(m.SummaryGroup.WEEKDAY) == {"1": 1, "2": 1, "3": 1}
    assert keys(m.SummaryGroup.ENTITY) == {"A": 3, "B": 0}  # a published entity without values is listed with n = 0
    assert response.timezone == "Europe/Madrid"
    assert pd.Timestamp(response.period_from_utc) == pd.Timestamp("2025-01-01T23:30Z")
    assert pd.Timestamp(response.period_to_utc) == pd.Timestamp("2025-07-01T22:30Z")


def test_every_group_row_adds_up_to_one_and_the_groups_partition_the_total(tmp_path):
    rows = [("AB"[i % 2], pd.Timestamp("2024-11-01T00:00Z") + pd.Timedelta(hours=7 * i), float(i % 90))
            for i in range(300)]
    response = run(tmp_path, rows)
    total = response.groups[m.SummaryGroup.ALL][0].n
    assert total == 300
    for group, group_rows in response.groups.items():
        assert sum(r.n for r in group_rows) == total, group
        for row in group_rows:
            assert row.n == 0 or sum(row.shares) == pytest.approx(1.0)


def test_a_numeric_variable_gets_quantiles_and_the_time_column_can_be_the_issue_time(tmp_path):
    values = list(range(1, 11))
    rows = [("A", pd.Timestamp("2025-03-03T00:00Z") + pd.Timedelta(hours=i), float(v)) for i, v in enumerate(values)]
    response = run(tmp_path, rows, scheme=None)
    row = response.groups[m.SummaryGroup.ALL][0]
    assert response.classes is None and row.shares is None and row.n == 10
    assert row.quantiles == pytest.approx({"p10": 1.9, "p25": 3.25, "p50": 5.5, "p75": 7.75, "p90": 9.1, "mean": 5.5})
    # the table's valid_at_utc is the end of the covered hour (NYC): the issue time keys the value instead
    late = [("A", "2025-03-03T01:00Z", 4.0, "2025-03-03T00:00Z")]
    as_issued = run(tmp_path, late, scheme=None, time_column="issued_at_utc")
    assert pd.Timestamp(as_issued.period_from_utc) == pd.Timestamp("2025-03-03T00:00Z")
    assert [r.key for r in as_issued.groups[m.SummaryGroup.HOUR]] == ["01"]  # 00:00Z is 01:00 in Madrid (winter)


def test_a_percentile_reference_scheme_is_not_binned():
    level = SCHEME.model_copy(update={"kind": m.SchemeKind.PERCENTILE_REFERENCE})
    assert classes_for(level) is None and classes_for(None) is None
    assert classes_for(SCHEME) is SCHEME
