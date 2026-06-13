from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "paginated_client.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("paginated_client", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)


class Response:
    def __init__(self, status: int, payload=None, retry_after: str | None = None):
        self.status_code = status
        self.payload = payload
        self.headers = {"Content-Type": "application/json"}
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after
        self.closed = False

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses):
        self.responses = {url: list(values) for url, values in responses.items()}
        self.calls = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses[url].pop(0)


def page(number: int) -> dict:
    return json.loads((DATA / f"api_page_{number}.json").read_text())


class PaginatedClientTest(unittest.TestCase):
    def test_loads_until_next_is_null(self) -> None:
        urls = [f"https://api.example.test/orders?page={number}" for number in (1, 2, 3)]
        session = Session({url: [Response(200, page(index + 1))] for index, url in enumerate(urls)})
        result = CLIENT.fetch_all(urls[0], session=session, sleep_fn=lambda delay: None)
        self.assertTrue(result["summary"]["valid"])
        self.assertEqual(result["summary"]["page_count"], 3)
        self.assertEqual(result["summary"]["record_count"], 5)

    def test_timeout_is_passed_on_every_request(self) -> None:
        url = "https://api.example.test/orders?page=3"
        session = Session({url: [Response(200, page(3))]})
        CLIENT.fetch_all(url, session=session, timeout=(1.0, 2.0), sleep_fn=lambda delay: None)
        self.assertEqual(session.calls[0][1]["timeout"], (1.0, 2.0))

    def test_retry_after_overrides_exponential_backoff(self) -> None:
        url = "https://api.example.test/orders?page=3"
        delays = []
        session = Session({url: [Response(429, retry_after="2"), Response(200, page(3))]})
        result = CLIENT.fetch_all(url, session=session, sleep_fn=delays.append)
        self.assertEqual(delays, [2.0])
        self.assertEqual(result["retries"][0]["reason"], "HTTP 429")

    def test_exponential_backoff_is_bounded(self) -> None:
        self.assertEqual(
            CLIENT.retry_delay(
                None,
                attempt=5,
                backoff_factor=1.0,
                max_backoff=10.0,
            ),
            10.0,
        )

    def test_http_date_retry_after_is_supported(self) -> None:
        now = datetime(2026, 5, 1, tzinfo=UTC)
        target = (now + timedelta(seconds=4)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        delay = CLIENT.retry_delay(
            target,
            attempt=0,
            backoff_factor=0.5,
            max_backoff=30.0,
            now=now,
        )
        self.assertEqual(delay, 4.0)

    def test_non_retryable_status_fails_immediately(self) -> None:
        url = "https://api.example.test/orders?page=1"
        session = Session({url: [Response(400, {})]})
        with self.assertRaisesRegex(CLIENT.PaginationError, "not recoverable"):
            CLIENT.fetch_all(url, session=session, sleep_fn=lambda delay: None)
        self.assertEqual(len(session.calls), 1)

    def test_pagination_cycle_is_detected(self) -> None:
        url = "https://api.example.test/orders?page=1"
        payload = {"items": [{"order_id": "O1"}], "next": url}
        session = Session({url: [Response(200, payload)]})
        with self.assertRaisesRegex(CLIENT.PaginationError, "cycle"):
            CLIENT.fetch_all(url, session=session, sleep_fn=lambda delay: None)

    def test_export_writes_records_and_report(self) -> None:
        url = "https://api.example.test/orders?page=3"
        result = CLIENT.fetch_all(
            url,
            session=Session({url: [Response(200, page(3))]}),
            sleep_fn=lambda delay: None,
        )
        with TemporaryDirectory() as directory:
            CLIENT.export_result(result, directory)
            output = Path(directory)
            self.assertEqual(len((output / "orders.jsonl").read_text().splitlines()), 1)
            self.assertTrue((output / "report.json").is_file())


if __name__ == "__main__":
    unittest.main()
