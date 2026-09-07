from __future__ import annotations

import copy
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import codex_radar as radar
import codex_claude_usage_web as web


def fixtures():
    # Deliberately unequal weights; averaging the IQs or API cost indexes is wrong.
    software = {
        "schema": 3, "mode": "equal_latest_3", "source_updated_at": "2026-09-07T12:00:00Z",
        "points": [
            {"model": "gpt-6-astra", "effort": "high", "iq": 100, "total": 3,
             "average_price_usd": 2, "average_minutes": 10, "combined_cost_index": 9999},
            {"model": "gpt-5.6-sol", "effort": "high", "iq": 80, "total": 2,
             "average_price_usd": 10, "average_minutes": 10},
            {"model": "gpt-5.5", "effort": "low", "iq": 50, "total": 1,
             "average_price_usd": 1, "average_minutes": 5},
        ],
    }
    visual = {
        "schema": 1, "type": "visual_spatial_reasoning_summary",
        "source_updated_at": "2026-09-07T09:00:00Z",
        "points": [
            {"model": "gpt-6-astra", "effort": "high", "iq": 140, "valid_tasks": 1,
             "average_price_usd": 6, "average_minutes": 10},
            {"model": "gpt-5.6-sol", "effort": "high", "iq": 100, "valid_tasks": 2,
             "average_price_usd": 10, "average_minutes": 10},
        ],
    }
    return software, visual


class CompositeTest(unittest.TestCase):
    def test_weighted_composite_and_normalization_match_source_rules(self):
        result = radar.combine_snapshots(*fixtures())
        astra, sol = result["points"]
        self.assertEqual(len(result["points"]), 2)
        self.assertEqual(astra["iq"], 110)
        self.assertEqual(astra["average_price_usd"], 3)
        self.assertAlmostEqual(astra["combined_cost_index"], 30)
        self.assertEqual(sol["iq"], 90)
        self.assertEqual(sol["combined_cost_index"], 100)
        self.assertEqual(result["source_updated_at"], "2026-09-07T09:00:00+00:00")

    def test_cost_speed_tradeoff_and_legacy_schema(self):
        software, visual = fixtures()
        software.update(schema=2, mode="weighted_latest_3")
        for row in software["points"]:
            row["weighted_total"] = row.pop("total")
        # 2.5 times the price, 1.35 times faster => equal combined cost.
        for payload in (software, visual):
            payload["points"][0].update(average_price_usd=2.5, average_minutes=10 / 1.35)
            payload["points"][1].update(average_price_usd=1, average_minutes=10)
        points = radar.combine_snapshots(software, visual)["points"]
        self.assertAlmostEqual(points[0]["combined_cost_index"], points[1]["combined_cost_index"])

    def test_bad_schema_nonfinite_duplicate_and_missing_intersection_fail(self):
        for kind in ("schema", "nan", "negative", "duplicate", "disjoint", "timestamp"):
            with self.subTest(kind=kind):
                software, visual = fixtures()
                if kind == "schema":
                    software["schema"] = 99
                elif kind == "nan":
                    software["points"][0]["iq"] = float("nan")
                elif kind == "negative":
                    visual["points"][0]["average_minutes"] = -1
                elif kind == "duplicate":
                    visual["points"].append(copy.deepcopy(visual["points"][0]))
                elif kind == "disjoint":
                    visual["points"] = []
                else:
                    visual["source_updated_at"] = "yesterday"
                with self.assertRaises(ValueError):
                    radar.combine_snapshots(software, visual)

    def test_missing_metrics_are_not_fabricated(self):
        software, visual = fixtures()
        visual["points"][0]["average_price_usd"] = None
        points = radar.combine_snapshots(software, visual)["points"]
        self.assertEqual([p["model"] for p in points], ["gpt-5.6-sol"])

    def test_unplottable_zero_values_do_not_discard_other_configurations(self):
        software, visual = fixtures()
        software["points"][0]["total"] = 0
        self.assertEqual(len(radar.combine_snapshots(software, visual)["points"]), 1)
        for field in ("average_price_usd", "average_minutes"):
            with self.subTest(field=field):
                software, visual = fixtures()
                software["points"][0][field] = 0
                points = radar.combine_snapshots(software, visual)["points"]
                self.assertEqual(len(points), 2)
                self.assertEqual(points[0][field], visual["points"][0][field] / 4)
                visual["points"][0][field] = 0
                points = radar.combine_snapshots(software, visual)["points"]
                self.assertEqual([p["model"] for p in points], ["gpt-5.6-sol"])
        software, visual = fixtures()
        software["points"][0]["iq"] = visual["points"][0]["iq"] = 0
        self.assertEqual(radar.combine_snapshots(software, visual)["points"][0]["iq"], 0)


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "radar.json"
        self.now = 1788782400.0
        self.calls = []
        self.error = None
        self.service = radar.RadarService(self.path, clock=lambda: self.now, fetcher=self.fetch)
        self.addCleanup(self.service.close)

    def fetch(self, url):
        self.calls.append(url)
        if self.error:
            raise self.error
        software, visual = fixtures()
        return software if url == radar.METRICS_URL else visual

    def test_reads_never_fetch_and_four_hour_expiry_survives_restart(self):
        self.assertFalse(self.service.snapshot()["available"])
        self.assertEqual(self.calls, [])
        self.assertTrue(self.service.refresh_if_due())
        for _ in range(20):
            self.service.snapshot()
        self.now += radar.REFRESH_SECONDS - 1
        restarted = radar.RadarService(self.path, clock=lambda: self.now, fetcher=self.fetch)
        self.assertFalse(restarted.refresh_if_due())
        self.assertEqual(len(self.calls), 2)
        self.now += 1
        self.assertTrue(restarted.refresh_if_due())
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_failure_preserves_snapshot_and_persists_retry_backoff(self):
        self.service.refresh_if_due()
        before = self.service.snapshot()
        self.now += radar.REFRESH_SECONDS
        self.error = ValueError("upstream changed")
        self.assertFalse(self.service.refresh_if_due())
        failed = self.service.snapshot()
        self.assertEqual(before["data"], failed["data"])
        self.assertEqual(before["fetched_at"], failed["fetched_at"])
        self.assertTrue(failed["stale"])
        count = len(self.calls)
        restarted = radar.RadarService(self.path, clock=lambda: self.now, fetcher=self.fetch)
        self.assertFalse(restarted.refresh_if_due())
        self.assertEqual(len(self.calls), count)
        self.now += radar.RETRY_SECONDS
        self.error = None
        self.assertTrue(restarted.refresh_if_due())
        self.assertFalse(restarted.snapshot()["stale"])
        self.assertIsNone(restarted.snapshot()["last_error"])

    def test_partial_fetch_never_replaces_good_snapshot(self):
        self.service.refresh_if_due()
        before = self.service.snapshot()["data"]
        original = self.service._fetcher
        self.service._fetcher = lambda url: original(url) if url == radar.METRICS_URL else {"schema": 999}
        self.assertFalse(self.service.refresh_if_due(force=True))
        self.assertEqual(self.service.snapshot()["data"], before)

    def test_repeated_failure_backs_off_and_caps_at_four_hours(self):
        self.error = OSError("offline")
        for minutes in (15, 30, 60, 120, 240, 240):
            self.assertFalse(self.service.refresh_if_due())
            state = json.loads(self.path.read_text())
            self.assertEqual(state["next_attempt_at_epoch"] - self.now, minutes * 60)
            self.now = state["next_attempt_at_epoch"]

    def test_cache_read_and_duplicate_refresh_do_not_wait_for_network(self):
        started, release = threading.Event(), threading.Event()
        original = self.service._fetcher
        def slow(url):
            started.set()
            release.wait(timeout=3)
            return original(url)
        self.service._fetcher = slow
        worker = threading.Thread(target=self.service.refresh_if_due)
        worker.start()
        try:
            self.assertTrue(started.wait(timeout=1))
            self.assertTrue(self.service.snapshot()["refreshing"])
            self.assertFalse(self.service.refresh_if_due(force=True))
        finally:
            release.set()
            worker.join(timeout=3)
        self.assertTrue(self.service.snapshot()["available"])

    def test_worker_fetches_without_a_browser_request_and_stops(self):
        saved = threading.Event()
        original = radar.atomic_write
        def write(*args):
            original(*args)
            saved.set()
        with patch.object(radar, "atomic_write", side_effect=write):
            self.service.start()
            self.assertTrue(saved.wait(timeout=2))
            self.service.close()
        self.assertFalse(self.service._thread.is_alive())
        self.assertEqual(len(self.calls), 2)

    def test_corrupt_cache_recovers_and_disk_failure_keeps_live_data(self):
        self.path.write_text('{"broken":')
        service = radar.RadarService(self.path, clock=lambda: self.now, fetcher=self.fetch)
        self.assertFalse(service.snapshot()["available"])
        with patch.object(radar, "atomic_write", side_effect=OSError("read-only")):
            self.assertTrue(service.refresh_if_due())
        self.assertTrue(service.snapshot()["available"])
        self.assertIsNotNone(service.snapshot()["cache_warning"])

    def test_invalid_cache_times_cannot_crash_or_postpone_recovery(self):
        snapshot = radar.combine_snapshots(*fixtures())
        for timestamp in (float("inf"), 1e30, "bad", -1, None):
            with self.subTest(timestamp=timestamp):
                self.path.write_text(json.dumps({"schema_version": 1, "snapshot": snapshot,
                    "fetched_at_epoch": timestamp, "next_attempt_at_epoch": timestamp}))
                service = radar.RadarService(self.path, clock=lambda: self.now, fetcher=self.fetch)
                self.assertFalse(service.snapshot()["available"])
                self.assertTrue(service.refresh_if_due())

    def test_nonfinite_cache_metadata_cannot_break_failure_retries(self):
        self.service.refresh_if_due()
        state = json.loads(self.path.read_text())
        state["unexpected_metadata"] = float("nan")
        self.path.write_text(json.dumps(state))
        restarted = radar.RadarService(self.path, clock=lambda: self.now, fetcher=self.fetch)
        self.assertFalse(restarted.snapshot()["available"])
        self.error = OSError("offline")
        self.assertFalse(restarted.refresh_if_due())
        self.now += radar.RETRY_SECONDS
        self.error = None
        self.assertTrue(restarted.refresh_if_due())


class FetchTest(unittest.TestCase):
    def test_identifies_client_checks_upstream_freshness_and_bounds_response(self):
        class Response:
            headers = {"X-Codex-Cache": "HIT"}
            body = b'{"points": []}'
            limit = None
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit):
                self.limit = limit
                return self.body
        response = Response()
        with patch.object(radar, "urlopen", return_value=response) as request:
            self.assertEqual(radar.fetch_json(radar.METRICS_URL), {"points": []})
            self.assertEqual(response.limit, radar.MAX_RESPONSE_BYTES + 1)
            self.assertEqual(request.call_args.args[0].get_header("User-agent"), "Codex-Usage-Dashboard/1.0")
            for status in ("STALE-ERROR", "ERROR", ""):
                response.headers = {"X-Codex-Cache": status}
                with self.subTest(status=status), self.assertRaises(ValueError):
                    radar.fetch_json(radar.METRICS_URL)
            response.headers = {"X-Codex-Cache": "HIT"}
            response.body = b"x" * (radar.MAX_RESPONSE_BYTES + 1)
            with self.assertRaises(ValueError):
                radar.fetch_json(radar.METRICS_URL)


class RadarAPITest(unittest.TestCase):
    def test_authenticated_endpoint_reads_cache_without_upstream_work(self):
        with tempfile.TemporaryDirectory() as directory:
            service = radar.RadarService(Path(directory) / "cache.json", fetcher=lambda _: self.fail("API initiated network work"))
            server = web.create_server("127.0.0.1", 0, access_token="test-radar-token",
                                       allowed_hosts=["127.0.0.1"], max_workers=2,
                                       max_collectors=1, cache_seconds=5, radar_service=service)
            server.quiet = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for method, authorized, status in (("GET", False, 403), ("HEAD", False, 403),
                                                   ("GET", True, 200), ("HEAD", True, 200)):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                    headers = {"Authorization": "Bearer test-radar-token"} if authorized else {}
                    connection.request(method, "/api/codex-radar", headers=headers)
                    response = connection.getresponse()
                    body = response.read()
                    self.assertEqual(response.status, status)
                    if authorized and method == "GET":
                        self.assertFalse(json.loads(body)["available"])
                    connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
