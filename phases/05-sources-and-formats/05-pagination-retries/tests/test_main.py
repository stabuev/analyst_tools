from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "paginated_client.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("paginated_client", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)


def page(number: int) -> dict:
    return json.loads((DATA / f"api_page_{number}.json").read_text(encoding="utf-8"))


class Response:
    def __init__(
        self,
        status: int,
        payload: object | None = None,
        *,
        body: bytes | None = None,
        content_type: str = "application/json; charset=utf-8",
        retry_after: str | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self.status_code = status
        self.body = body if body is not None else json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Type": content_type}
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after
        self.closed = False
        self.stream_error = stream_error

    def iter_content(self, chunk_size: int):
        if self.stream_error is not None:
            raise self.stream_error
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


class Session:
    def __init__(self, responses: dict[str, list[Response | Exception]]) -> None:
        self.responses = {url: list(values) for url, values in responses.items()}
        self.calls: list[tuple[str, dict]] = []
        self.closed = False
        self.trust_env = True

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.responses[url].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        self.closed = True


def fixture_session() -> tuple[str, Session]:
    urls = [f"https://api.example.test/orders?page={number}" for number in (1, 2, 3)]
    return urls[0], Session(
        {url: [Response(200, page(index + 1))] for index, url in enumerate(urls)}
    )


class TraversalTest(unittest.TestCase):
    def test_loads_until_explicit_next_null(self) -> None:
        start_url, session = fixture_session()
        result = CLIENT.fetch_all(start_url, session=session, sleep_fn=lambda delay: None)

        self.assertTrue(result["summary"]["valid"])
        self.assertFalse(result["summary"]["published"])
        self.assertEqual(result["summary"]["page_count"], 3)
        self.assertEqual(result["summary"]["record_count"], 5)
        self.assertEqual(
            [row["order_id"] for row in result["records"]],
            [
                "O2301",
                "O2302",
                "O2303",
                "O2304",
                "O2305",
            ],
        )
        self.assertTrue(result["checks"]["terminated_by_next_null"])

    def test_transport_contract_is_applied_to_every_page(self) -> None:
        start_url, session = fixture_session()
        CLIENT.fetch_all(start_url, session=session, timeout=(1.0, 2.0), sleep_fn=lambda _: None)

        self.assertEqual(len(session.calls), 3)
        for _, kwargs in session.calls:
            self.assertEqual(kwargs["timeout"], (1.0, 2.0))
            self.assertTrue(kwargs["stream"])
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(kwargs["headers"], {"Accept": "application/json"})

    def test_relative_next_is_resolved_within_same_origin(self) -> None:
        first = "https://api.example.test/orders?page=1"
        second = "https://api.example.test/orders?page=2"
        first_payload = {"items": [{"order_id": "O1"}], "next": "?page=2"}
        second_payload = {"items": [{"order_id": "O2"}], "next": None}
        session = Session(
            {first: [Response(200, first_payload)], second: [Response(200, second_payload)]}
        )

        result = CLIENT.fetch_all(first, session=session, sleep_fn=lambda _: None)

        self.assertEqual([call[0] for call in session.calls], [first, second])
        self.assertEqual(result["summary"]["record_count"], 2)

    def test_explicit_default_https_port_is_the_same_origin(self) -> None:
        first = "https://api.example.test/orders?page=1"
        second = "https://api.example.test:443/orders?page=2"
        session = Session(
            {
                first: [Response(200, {"items": [{"order_id": "O1"}], "next": second})],
                second: [Response(200, {"items": [{"order_id": "O2"}], "next": None})],
            }
        )

        result = CLIENT.fetch_all(first, session=session, sleep_fn=lambda _: None)

        self.assertEqual(result["summary"]["page_count"], 2)

    def test_cross_origin_next_is_rejected_before_second_request(self) -> None:
        first = "https://api.example.test/orders?page=1"
        payload = {
            "items": [{"order_id": "O1"}],
            "next": "https://evil.example/orders?page=2&token=secret",
        }
        session = Session({first: [Response(200, payload)]})

        with self.assertRaisesRegex(CLIENT.PaginationError, "outside") as caught:
            CLIENT.fetch_all(first, session=session, sleep_fn=lambda _: None)

        self.assertEqual(len(session.calls), 1)
        self.assertNotIn("secret", json.dumps(caught.exception.as_report()))

    def test_https_to_http_next_is_rejected(self) -> None:
        first = "https://api.example.test/orders?page=1"
        payload = {"items": [{"order_id": "O1"}], "next": "http://api.example.test/p2"}
        session = Session({first: [Response(200, payload)]})

        with self.assertRaisesRegex(CLIENT.PaginationError, "HTTP"):
            CLIENT.fetch_all(first, session=session, sleep_fn=lambda _: None)

    def test_invalid_port_is_a_controlled_configuration_error(self) -> None:
        with self.assertRaisesRegex(CLIENT.PaginationError, "invalid port") as caught:
            CLIENT.fetch_all("https://api.example.test:bad/orders")
        self.assertEqual(caught.exception.kind, "configuration")

    def test_cycle_is_detected_before_repeated_request(self) -> None:
        url = "https://api.example.test/orders?page=1"
        session = Session({url: [Response(200, {"items": [{"order_id": "O1"}], "next": url})]})

        with self.assertRaisesRegex(CLIENT.PaginationError, "cycle"):
            CLIENT.fetch_all(url, session=session, sleep_fn=lambda _: None)

        self.assertEqual(len(session.calls), 1)

    def test_max_pages_blocks_unproven_completion(self) -> None:
        first = "https://api.example.test/orders?page=1"
        second = "https://api.example.test/orders?page=2"
        session = Session(
            {
                first: [Response(200, {"items": [{"order_id": "O1"}], "next": second})],
                second: [Response(200, {"items": [{"order_id": "O2"}], "next": None})],
            }
        )

        with self.assertRaisesRegex(CLIENT.PaginationError, "max_pages") as caught:
            CLIENT.fetch_all(first, session=session, max_pages=1, sleep_fn=lambda _: None)

        self.assertEqual(len(session.calls), 1)
        self.assertEqual(caught.exception.details["buffered_records"], 1)

    def test_query_values_are_redacted_in_success_report(self) -> None:
        url = "https://api.example.test/orders?page=1&token=top-secret"
        session = Session({url: [Response(200, {"items": [{"order_id": "O1"}], "next": None})]})

        result = CLIENT.fetch_all(url, session=session, sleep_fn=lambda _: None)

        serialized = json.dumps(result)
        self.assertNotIn("top-secret", serialized)
        self.assertIn("redacted", serialized)


class PageContractTest(unittest.TestCase):
    def test_missing_next_is_not_treated_as_end(self) -> None:
        url = "https://api.example.test/orders"
        session = Session({url: [Response(200, {"items": [{"order_id": "O1"}]})]})
        with self.assertRaisesRegex(CLIENT.PaginationError, "must contain next"):
            CLIENT.fetch_all(url, session=session, sleep_fn=lambda _: None)

    def test_items_must_be_a_list(self) -> None:
        url = "https://api.example.test/orders"
        session = Session({url: [Response(200, {"items": {}, "next": None})]})
        with self.assertRaisesRegex(CLIENT.PaginationError, "items must be a list"):
            CLIENT.fetch_all(url, session=session, sleep_fn=lambda _: None)

    def test_every_record_must_have_the_declared_key(self) -> None:
        url = "https://api.example.test/orders"
        session = Session({url: [Response(200, {"items": [{"amount": 10}], "next": None})]})
        with self.assertRaisesRegex(CLIENT.PaginationError, "order_id"):
            CLIENT.fetch_all(url, session=session, sleep_fn=lambda _: None)

    def test_duplicate_key_within_one_page_is_rejected(self) -> None:
        url = "https://api.example.test/orders"
        payload = {"items": [{"order_id": "O1"}, {"order_id": "O1"}], "next": None}
        session = Session({url: [Response(200, payload)]})
        with self.assertRaisesRegex(CLIENT.PaginationError, "duplicate"):
            CLIENT.fetch_all(url, session=session, sleep_fn=lambda _: None)

    def test_duplicate_key_across_pages_is_rejected(self) -> None:
        first = "https://api.example.test/orders?page=1"
        second = "https://api.example.test/orders?page=2"
        session = Session(
            {
                first: [Response(200, {"items": [{"order_id": "O1"}], "next": second})],
                second: [Response(200, {"items": [{"order_id": "O1"}], "next": None})],
            }
        )
        with self.assertRaisesRegex(CLIENT.PaginationError, "duplicate"):
            CLIENT.fetch_all(first, session=session, sleep_fn=lambda _: None)

    def test_exact_200_is_required_instead_of_any_2xx(self) -> None:
        url = "https://api.example.test/orders"
        response = Response(206, {"items": [{"order_id": "O1"}], "next": None})
        session = Session({url: [response]})
        with self.assertRaisesRegex(CLIENT.PaginationError, "HTTP 206"):
            CLIENT.fetch_all(url, session=session, sleep_fn=lambda _: None)
        self.assertTrue(response.closed)

    def test_vendor_json_media_type_is_allowed(self) -> None:
        url = "https://api.example.test/orders"
        response = Response(
            200,
            {"items": [{"order_id": "O1"}], "next": None},
            content_type="application/vnd.example+json",
        )
        result = CLIENT.fetch_all(url, session=Session({url: [response]}), sleep_fn=lambda _: None)
        self.assertTrue(result["summary"]["valid"])

    def test_html_error_body_is_rejected_before_json_parsing(self) -> None:
        url = "https://api.example.test/orders"
        response = Response(200, body=b"<html>error</html>", content_type="text/html")
        with self.assertRaisesRegex(CLIENT.PaginationError, "not JSON"):
            CLIENT.fetch_all(url, session=Session({url: [response]}), sleep_fn=lambda _: None)

    def test_invalid_utf8_is_rejected(self) -> None:
        url = "https://api.example.test/orders"
        response = Response(200, body=b'{"items": ["\xff"], "next": null}')
        with self.assertRaisesRegex(CLIENT.PaginationError, "UTF-8"):
            CLIENT.fetch_all(url, session=Session({url: [response]}), sleep_fn=lambda _: None)

    def test_decoded_page_size_is_bounded(self) -> None:
        url = "https://api.example.test/orders"
        response = Response(200, {"items": [{"order_id": "O1"}], "next": None})
        with self.assertRaisesRegex(CLIENT.PaginationError, "max_page_bytes"):
            CLIENT.fetch_all(
                url,
                session=Session({url: [response]}),
                max_page_bytes=10,
                sleep_fn=lambda _: None,
            )


class RetryPolicyTest(unittest.TestCase):
    def test_retry_after_seconds_overrides_local_backoff(self) -> None:
        url = "https://api.example.test/orders"
        delays: list[float] = []
        first = Response(429, {}, retry_after="2")
        session = Session(
            {url: [first, Response(200, {"items": [{"order_id": "O1"}], "next": None})]}
        )

        result = CLIENT.fetch_all(url, session=session, sleep_fn=delays.append)

        self.assertEqual(delays, [2.0])
        self.assertEqual(result["retries"][0]["delay_source"], "retry-after")
        self.assertTrue(first.closed)

    def test_http_date_retry_after_is_supported(self) -> None:
        now = datetime(2026, 5, 1, tzinfo=UTC)
        target = (now + timedelta(seconds=4)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        delay = CLIENT.parse_retry_after(target, now=now)
        self.assertEqual(delay, 4.0)

    def test_invalid_retry_after_falls_back_to_jittered_backoff(self) -> None:
        delay, source = CLIENT.retry_delay(
            "not-a-date",
            retry_number=2,
            backoff_factor=1.0,
            max_backoff=10.0,
            jitter_ratio=0.25,
            random_fn=lambda low, high: low,
        )
        self.assertEqual((delay, source), (1.5, "backoff"))

    def test_retry_after_above_wait_budget_stops_instead_of_retrying_early(self) -> None:
        url = "https://api.example.test/orders"
        response = Response(503, {}, retry_after="120")
        session = Session({url: [response]})

        with self.assertRaisesRegex(CLIENT.PaginationError, "refusing to retry early"):
            CLIENT.fetch_all(url, session=session, max_backoff=30, sleep_fn=lambda _: None)

        self.assertEqual(len(session.calls), 1)
        self.assertTrue(response.closed)

    def test_non_retryable_400_fails_after_one_attempt(self) -> None:
        url = "https://api.example.test/orders"
        session = Session({url: [Response(400, {})]})
        with self.assertRaisesRegex(CLIENT.PaginationError, "HTTP 400"):
            CLIENT.fetch_all(url, session=session, sleep_fn=lambda _: None)
        self.assertEqual(len(session.calls), 1)

    def test_transport_error_is_retried_for_get(self) -> None:
        url = "https://api.example.test/orders"
        session = Session(
            {
                url: [
                    requests.ReadTimeout("late page"),
                    Response(200, {"items": [{"order_id": "O1"}], "next": None}),
                ]
            }
        )
        result = CLIENT.fetch_all(
            url,
            session=session,
            jitter_ratio=0,
            sleep_fn=lambda _: None,
        )
        self.assertEqual(result["summary"]["retry_count"], 1)
        self.assertEqual(result["retries"][0]["reason"], "transport:ReadTimeout")

    def test_stream_read_timeout_is_retried_and_response_is_closed(self) -> None:
        url = "https://api.example.test/orders"
        timed_out = Response(200, {}, stream_error=requests.ReadTimeout("late body"))
        session = Session(
            {
                url: [
                    timed_out,
                    Response(200, {"items": [{"order_id": "O1"}], "next": None}),
                ]
            }
        )

        result = CLIENT.fetch_all(url, session=session, sleep_fn=lambda _: None)

        self.assertTrue(timed_out.closed)
        self.assertEqual(result["summary"]["retry_count"], 1)
        self.assertEqual(result["retries"][0]["reason"], "transport:ReadTimeout")

    def test_per_page_retry_budget_is_enforced(self) -> None:
        url = "https://api.example.test/orders"
        session = Session({url: [Response(503, {}), Response(503, {})]})
        with self.assertRaisesRegex(CLIENT.PaginationError, "budget exhausted") as caught:
            CLIENT.fetch_all(
                url,
                session=session,
                max_retries_per_page=1,
                sleep_fn=lambda _: None,
            )
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(caught.exception.details["page_retries"], 1)

    def test_total_retry_budget_is_shared_by_all_pages(self) -> None:
        first = "https://api.example.test/orders?page=1"
        second = "https://api.example.test/orders?page=2"
        session = Session(
            {
                first: [
                    Response(503, {}),
                    Response(200, {"items": [{"order_id": "O1"}], "next": second}),
                ],
                second: [Response(503, {})],
            }
        )
        with self.assertRaisesRegex(CLIENT.PaginationError, "budget exhausted") as caught:
            CLIENT.fetch_all(
                first,
                session=session,
                max_total_retries=1,
                sleep_fn=lambda _: None,
            )
        self.assertEqual(caught.exception.details["completed_pages"], 1)
        self.assertEqual(caught.exception.details["buffered_records"], 1)


class PublicationTest(unittest.TestCase):
    def test_snapshot_is_self_contained_and_atomically_replaces_previous_file(self) -> None:
        start_url, session = fixture_session()
        result = CLIENT.fetch_all(start_url, session=session, sleep_fn=lambda _: None)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders_snapshot.json"
            output.write_text("previous", encoding="utf-8")

            CLIENT.publish_snapshot(result, output)

            published = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(published["summary"]["published"])
            self.assertEqual(len(published["records"]), 5)
            self.assertEqual(published["pages"][-1]["next"], None)
            self.assertEqual(list(output.parent.glob("*.part")), [])

    def test_failed_traversal_preserves_previous_snapshot(self) -> None:
        url = "https://api.example.test/orders"
        session = Session({url: [Response(400, {})]})
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders_snapshot.json"
            output.write_text("previous", encoding="utf-8")

            with self.assertRaises(CLIENT.PaginationError):
                CLIENT.download_snapshot(url, output, session=session, sleep_fn=lambda _: None)

            self.assertEqual(output.read_text(encoding="utf-8"), "previous")

    def test_supplied_session_is_not_closed_by_fetch_all(self) -> None:
        url = "https://api.example.test/orders"
        session = Session({url: [Response(200, {"items": [{"order_id": "O1"}], "next": None})]})
        CLIENT.fetch_all(url, session=session, sleep_fn=lambda _: None)
        self.assertFalse(session.closed)

    def test_owned_session_disables_environment_and_is_closed(self) -> None:
        url = "https://api.example.test/orders"
        session = Session({url: [Response(200, {"items": [{"order_id": "O1"}], "next": None})]})
        with patch.object(CLIENT.requests, "Session", return_value=session):
            CLIENT.fetch_all(url, sleep_fn=lambda _: None)
        self.assertFalse(session.trust_env)
        self.assertTrue(session.closed)

    def test_cli_configuration_failure_has_no_traceback(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.json"
            with patch.dict(CLIENT.os.environ, {}, clear=True), patch("builtins.print") as printer:
                exit_code = CLIENT.main(
                    [
                        "--url",
                        "https://api.example.test/orders",
                        "--output",
                        str(output),
                        "--bearer-token-env",
                        "MISSING_TOKEN",
                    ]
                )
        self.assertEqual(exit_code, 2)
        self.assertIn("missing", printer.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
