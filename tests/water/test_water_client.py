"""Pagination, retry/backoff, pacing and request shape of the API client (no network: scripted transport)."""

from collections import Counter

import pytest
from water_helpers import BASE, Response, ScriptedTransport, make_client, ok

from atlas.domains.water.client import USER_AGENT, ApiError

NEXT = f"{BASE}/data/observation?skip=2"


def page(n: int, total: int | None, more: bool) -> Response:
    return ok(b"x" * n, total=total, next_url=NEXT if more else None)


def collect(client, **kwargs):
    return list(client.pages("POST", "data/observation", {"determinand": "9924"}, accept="text/csv", limit=2, **kwargs))


def test_pagination_walks_every_page_and_stops_on_the_last_one():
    transport = ScriptedTransport(page(5, 5, True), page(5, 5, True), page(1, 5, False))
    client, _ = make_client(transport)
    pages = collect(client)
    assert [p.skip for p in pages] == [0, 2, 4]
    assert [p.has_next for p in pages] == [True, True, False]
    assert all(p.total_items == 5 for p in pages)
    assert len(transport.calls) == 3  # no request beyond the last page
    assert "skip=4" in transport.calls[2][1] and "limit=2" in transport.calls[2][1]


def test_exact_multiple_of_the_page_size_does_not_request_an_extra_page():
    transport = ScriptedTransport(page(4, 4, True), page(4, 4, False))
    client, _ = make_client(transport)
    assert [p.skip for p in collect(client)] == [0, 2]
    assert len(transport.calls) == 2


def test_empty_result_204_is_one_empty_page_not_an_error():
    transport = ScriptedTransport(Response(204, {}, b""))
    client, _ = make_client(transport)
    pages = collect(client)
    assert len(pages) == 1 and pages[0].body == b"" and not pages[0].has_next and pages[0].total_items is None


def test_empty_body_stops_even_if_the_server_still_advertises_next():
    transport = ScriptedTransport(page(3, 9, True), ok(b"", total=9, next_url=NEXT))
    client, _ = make_client(transport)
    assert [p.skip for p in collect(client)] == [0, 2]


def test_without_link_header_the_total_decides():
    transport = ScriptedTransport(
        Response(200, {"x-total-items": "3"}, b"aa"), Response(200, {"x-total-items": "3"}, b"b")
    )
    client, _ = make_client(transport)
    assert [p.skip for p in collect(client)] == [0, 2]


def test_a_server_that_never_ends_is_cut_by_max_pages():
    transport = ScriptedTransport(*[page(2, 99, True) for _ in range(5)])
    client, _ = make_client(transport)
    with pytest.raises(ApiError, match="did not end"):
        collect(client, max_pages=3)


def test_request_shape_post_headers_and_url():
    transport = ScriptedTransport(page(1, 1, False))
    client, _ = make_client(transport)
    collect(client)
    method, url, headers = transport.calls[0]
    assert method == "POST"
    assert url == f"{BASE}/data/observation?determinand=9924&limit=2&skip=0"
    assert headers["User-Agent"] == USER_AGENT and "exfuzzy-atlas" in USER_AGENT
    assert headers["Accept"] == "text/csv" and headers["API-Version"] == "1"
    assert headers["Accept-Crs"].endswith("/27700")
    assert client.url("sampling-point", {"a": None, "b": "x y"}) == f"{BASE}/sampling-point?b=x+y"


@pytest.mark.parametrize("bad", [429, 500, 502, 503, 504])
def test_retries_retryable_statuses_with_exponential_backoff(bad):
    transport = ScriptedTransport(Response(bad, {}, b"busy"), Response(503, {}, b""), ok(b"data", total=1))
    client, clock = make_client(transport, backoff_s=2.0)
    _, response = client.request("GET", "sampling-point")
    assert response.body == b"data"
    assert clock.sleeps == [2.0, 4.0]
    assert client.stats.requests == 3 and client.stats.retries == 2
    assert client.stats.statuses == dict(Counter([bad, 503, 200]))


def test_retry_after_longer_than_backoff_wins_and_backoff_is_capped():
    transport = ScriptedTransport(Response(429, {"retry-after": "30"}, b""), ok(b"d", total=1))
    client, clock = make_client(transport, backoff_s=2.0)
    client.request("GET", "sampling-point")
    assert clock.sleeps == [30.0]

    transport = ScriptedTransport(*[Response(503, {}, b"") for _ in range(4)], ok(b"d", total=1))
    client, clock = make_client(transport, backoff_s=10.0, max_backoff_s=25.0, max_attempts=5)
    client.request("GET", "sampling-point")
    assert clock.sleeps == [10.0, 20.0, 25.0, 25.0]


def test_network_errors_are_retried_too():
    transport = ScriptedTransport(TimeoutError("timed out"), ConnectionResetError("reset"), ok(b"d", total=1))
    client, clock = make_client(transport)
    client.request("GET", "sampling-point")
    assert client.stats.retries == 2 and len(clock.sleeps) == 2


def test_gives_up_after_max_attempts():
    transport = ScriptedTransport(*[Response(503, {}, b"down") for _ in range(3)])
    client, _ = make_client(transport, max_attempts=3)
    with pytest.raises(ApiError, match="after 3 attempts") as caught:
        client.request("GET", "sampling-point")
    assert caught.value.status == 503 and len(transport.calls) == 3


@pytest.mark.parametrize("status", [400, 404, 405, 422])
def test_client_errors_are_not_retried(status):
    transport = ScriptedTransport(Response(status, {}, b'{"detail":"nope"}'), ok(b"never"))
    client, clock = make_client(transport)
    with pytest.raises(ApiError, match="nope") as caught:
        client.request("GET", "sampling-point")
    assert caught.value.status == status and len(transport.calls) == 1 and not clock.sleeps


def test_requests_are_paced():
    transport = ScriptedTransport(ok(b"a", total=1), ok(b"b", total=1), ok(b"c", total=1))
    client, clock = make_client(transport, min_interval_s=0.5)
    for _ in range(3):
        client.request("GET", "sampling-point")
    assert clock.sleeps == [0.5, 0.5]  # the fake clock does not advance on its own, so each gap is the full interval
