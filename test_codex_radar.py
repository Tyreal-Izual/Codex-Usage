from __future__ import annotations

import copy
import http.client
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
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
        self.assertEqual(astra["combined_cost_index"], 100)  # separate generation scales
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
            payload["points"][1].update(model="gpt-6-astra", effort="medium")
            payload["points"][0].update(average_price_usd=2.5, average_minutes=10 / 1.35)
            payload["points"][1].update(average_price_usd=1, average_minutes=10)
        points = radar.combine_snapshots(software, visual)["points"]
        self.assertAlmostEqual(points[0]["combined_cost_index"], points[1]["combined_cost_index"])

    def test_bad_schema_nonfinite_duplicate_and_timestamp_fail(self):
        for kind in ("schema", "nan", "negative", "duplicate", "timestamp"):
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
                else:
                    visual["source_updated_at"] = "yesterday"
                with self.assertRaises(ValueError):
                    radar.combine_snapshots(software, visual)

    def test_missing_metrics_are_not_fabricated(self):
        software, visual = fixtures()
        visual["points"][0]["average_price_usd"] = None
        points = radar.combine_snapshots(software, visual)["points"]
        self.assertIsNone(points[0]["average_price_usd"])
        self.assertIsNone(points[0]["combined_cost_index"])
        self.assertEqual(points[0]["iq"], 110)

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
                self.assertIsNone(points[0]["combined_cost_index"])
                self.assertEqual(points[1]["combined_cost_index"], 100)
        software, visual = fixtures()
        software["points"][0]["iq"] = visual["points"][0]["iq"] = 0
        self.assertEqual(radar.combine_snapshots(software, visual)["points"][0]["iq"], 0)


class CurrentRadarRulesTest(unittest.TestCase):
    def payloads(self, software_samples=30, visual_samples=29):
        software, visual = fixtures()
        software["points"] = [{**software["points"][0], "model":"gpt-6-sol", "total":software_samples, "price_aggregation":"median"}]
        visual["points"] = [{**visual["points"][0], "model":"gpt-6-sol", "valid_tasks":visual_samples, "benchmark_tasks":86, "price_aggregation":"median"}]
        return software, visual

    def test_new_gpt6_software_only_does_not_treat_visual_as_zero(self):
        result = radar.combine_snapshots(*self.payloads())
        point = result["points"][0]
        self.assertEqual(point["iq"], 100)
        self.assertEqual(point["average_price_usd"], 2)
        self.assertIsNone(point["visual_iq"])
        self.assertFalse(point["visual_included"])
        self.assertEqual(point["score_basis"], "software")
        self.assertEqual(result["views"]["visual"]["points"], [])
        self.assertEqual(result["samples"][0]["visual_samples"], 29)
        self.assertEqual(result["views"]["software"]["points"][0]["price_aggregation"], "median")

    def test_below_threshold_snapshot_shows_insufficient_data_without_invented_scores(self):
        result = radar.combine_snapshots(*self.payloads(29, 29))
        self.assertTrue(radar.validate_snapshot(result))
        self.assertTrue(all(not view["points"] for view in result["views"].values()))
        self.assertEqual(result["samples"][0]["software_samples"], 29)

    def test_visual_contributes_at_thirty_samples(self):
        result = radar.combine_snapshots(*self.payloads(30, 30))
        self.assertEqual(result["points"][0]["iq"], 120)
        self.assertEqual(result["points"][0]["average_price_usd"], 4)
        self.assertTrue(result["points"][0]["visual_included"])

    def test_software_threshold_blocks_composite_but_not_valid_visual_view(self):
        result = radar.combine_snapshots(*self.payloads(29, 30))
        self.assertEqual(result["points"], [])
        self.assertEqual(result["views"]["software"]["points"], [])
        self.assertEqual(len(result["views"]["visual"]["points"]), 1)
        self.assertTrue(radar.validate_snapshot(result))

    def test_legacy_models_still_need_two_components_for_composite(self):
        software, visual = fixtures()
        visual["points"] = []
        result = radar.combine_snapshots(software, visual)
        self.assertEqual(result["points"], [])
        self.assertTrue(result["views"]["software"]["points"])

    def test_more_than_thirty_points_are_valid_and_generations_normalize_separately(self):
        software, visual = fixtures()
        a, b = software["points"][0], visual["points"][0]
        software["points"] = [{**a,"model":m,"effort":e,"total":40} for m in radar.MODEL_NAMES for e in radar.EFFORTS]
        visual["points"] = [{**b,"model":m,"effort":e,"valid_tasks":40} for m in radar.MODEL_NAMES for e in radar.EFFORTS]
        result = radar.combine_snapshots(software, visual)
        self.assertGreater(len(result["points"]),30)
        self.assertTrue(radar.validate_snapshot(result))
        self.assertEqual(len(result["points"]), 46)  # 8 families; 6.1 Sol/Luna have no ultra
        for models in radar.MODEL_GROUPS.values():
            self.assertEqual(max(p["combined_cost_index"] for p in result["points"] if p["model"] in models),100)

    def test_distinct_coverage_is_not_derived_from_sample_count(self):
        result = radar.combine_snapshots(*self.payloads(90, 30), coverage={("gpt-6-sol","high"):(20,112)})
        point=result["points"][0]
        self.assertEqual(point["software_samples"],90)
        self.assertEqual(point["software_covered_tasks"],20)
        self.assertEqual(point["software_benchmark_tasks"],112)


class Gpt61Test(unittest.TestCase):
    def payloads(self, visual_samples=30):
        software, visual = fixtures()
        a, b = software["points"][0], visual["points"][0]
        software["points"]=[{**a,"model":"gpt-6.1-sol","effort":e,"total":30} for e in radar.EFFORTS]
        visual["points"]=[{**b,"model":"gpt-6.1-sol","effort":e,"valid_tasks":visual_samples} for e in radar.EFFORTS]
        return software, visual

    def test_five_efforts_in_all_views_and_no_ultra(self):
        result=radar.combine_snapshots(*self.payloads())
        self.assertTrue(radar.validate_snapshot(result))
        for view in result["views"].values():
            self.assertEqual({p["effort"] for p in view["points"]},set(radar.EFFORTS)-{"ultra"})
            self.assertTrue(all(p["model"]=="gpt-6.1-sol" for p in view["points"]))
            self.assertTrue(all(p["combined_cost_index"]==100 for p in view["points"]))
        self.assertEqual(result["points"][0]["iq"],120)

    def test_gpt61_shares_gpt6_cost_scale_and_coverage(self):
        software,visual=self.payloads()
        a={**software["points"][0],"model":"gpt-6-sol","average_price_usd":20}
        b={**visual["points"][0],"model":"gpt-6-sol","average_price_usd":20}
        software["points"].append(a); visual["points"].append(b)
        coverage={("gpt-6.1-sol","low"):(24,112)}
        result=radar.combine_snapshots(software,visual,coverage)
        point=next(p for p in result["points"] if p["model"]=="gpt-6.1-sol" and p["effort"]=="low")
        self.assertAlmostEqual(point["combined_cost_index"],20)
        self.assertEqual(point["software_covered_tasks"],24)
        self.assertEqual(point["software_benchmark_tasks"],112)

    def test_gpt61_applies_thirty_sample_threshold_without_zero_filling(self):
        software,visual=self.payloads(29)
        result=radar.combine_snapshots(software,visual)
        self.assertEqual(result["views"]["visual"]["points"],[])
        self.assertTrue(all(p["score_basis"]=="software" and p["iq"]==100 for p in result["points"]))
        for point in software["points"]: point["total"]=29
        result=radar.combine_snapshots(software,visual)
        self.assertTrue(radar.validate_snapshot(result))
        self.assertTrue(all(not v["points"] for v in result["views"].values()))



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
        self.assertEqual(len(self.calls), 3)
        self.now += 1
        self.assertTrue(restarted.refresh_if_due())
        self.assertEqual(len(self.calls), 6)
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

    def test_legacy_cache_refreshes_immediately_and_survives_network_failure(self):
        self.service.refresh_if_due()
        state = json.loads(self.path.read_text())
        state["schema_version"] = 1
        state["snapshot"].pop("views")
        self.path.write_text(json.dumps(state))
        upgraded = radar.RadarService(self.path, clock=lambda: self.now, fetcher=self.fetch)
        self.assertTrue(upgraded.snapshot()["available"])
        self.assertTrue(upgraded.snapshot()["stale"])
        self.error = OSError("offline")
        self.assertFalse(upgraded.refresh_if_due())
        self.assertTrue(upgraded.snapshot()["available"])
        upgraded = radar.RadarService(self.path, clock=lambda: self.now, fetcher=self.fetch)
        self.assertTrue(upgraded.snapshot()["available"])
        count = len(self.calls)
        self.assertFalse(upgraded.refresh_if_due())
        self.assertEqual(len(self.calls), count)
        self.now += radar.RETRY_SECONDS
        self.error = None
        self.assertTrue(upgraded.refresh_if_due())
        self.assertEqual(json.loads(self.path.read_text())["schema_version"], radar.CACHE_VERSION)
        self.assertIn("views", upgraded.snapshot()["data"])

    def test_version_two_cache_refreshes_catalog_and_keeps_failure_backoff(self):
        self.service.refresh_if_due()
        state=json.loads(self.path.read_text())
        state["schema_version"]=2
        self.path.write_text(json.dumps(state))
        service=radar.RadarService(self.path,clock=lambda:self.now,fetcher=self.fetch)
        self.assertTrue(service.snapshot()["available"])
        self.assertTrue(service.snapshot()["stale"])
        self.error=OSError("offline")
        self.assertFalse(service.refresh_if_due())
        restarted=radar.RadarService(self.path,clock=lambda:self.now,fetcher=self.fetch)
        count=len(self.calls)
        self.assertTrue(restarted.snapshot()["available"])
        self.assertFalse(restarted.refresh_if_due())
        self.assertEqual(len(self.calls),count)
        self.now+=radar.RETRY_SECONDS
        self.error=None
        self.assertTrue(restarted.refresh_if_due())
        self.assertFalse(restarted.snapshot()["stale"])
        self.assertEqual(json.loads(self.path.read_text())["schema_version"],radar.CACHE_VERSION)

    def test_optional_coverage_failure_keeps_new_scores(self):
        self.service.refresh_if_due()
        self.assertTrue(self.service.snapshot()["available"])
        self.assertIsNotNone(self.service.snapshot()["data"]["coverage_warning"])
        self.assertIsNone(self.service.snapshot()["last_error"])

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
        self.assertEqual(len(self.calls), 3)

    def test_corrupt_cache_recovers_and_disk_failure_keeps_live_data(self):
        self.path.write_text('{"broken":')
        service = radar.RadarService(self.path, clock=lambda: self.now, fetcher=self.fetch)
        self.assertFalse(service.snapshot()["available"])
        with patch.object(radar, "atomic_write", side_effect=OSError("read-only")):
            self.assertTrue(service.refresh_if_due())
        self.assertTrue(service.snapshot()["available"])
        self.assertIsNotNone(service.snapshot()["cache_warning"])

    def test_missing_measurement_fields_in_cache_do_not_break_startup(self):
        for version in (1, 2, radar.CACHE_VERSION):
            for field in ("average_price_usd", "average_minutes", "combined_cost_index"):
                with self.subTest(version=version, field=field):
                    snapshot = radar.combine_snapshots(*fixtures())
                    if version == 1:
                        snapshot.pop("views")
                    del snapshot["points"][0][field]
                    self.path.write_text(json.dumps({"schema_version": version, "snapshot": snapshot,
                        "fetched_at_epoch": self.now, "next_attempt_at_epoch": self.now + radar.REFRESH_SECONDS}))
                    service = radar.RadarService(self.path, clock=lambda: self.now, fetcher=self.fetch)
                    self.assertFalse(service.snapshot()["available"])
                    self.assertTrue(service.refresh_if_due())
                    self.assertTrue(service.snapshot()["available"])

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


class WorkerToggleTest(unittest.TestCase):
    def test_paused_worker_never_fetches_and_resume_keeps_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            fetcher = unittest.mock.Mock(side_effect=RuntimeError('synthetic offline'))
            service = radar.RadarService(Path(directory)/'cache.json', fetcher=fetcher)
            service.set_enabled(False)
            self.assertFalse(service.refresh_if_due(force=True))
            fetcher.assert_not_called()
            service.set_enabled(True)
            service.refresh_if_due(force=True)
            self.assertTrue(fetcher.called)
            before = service.snapshot()
            service.set_enabled(False)
            self.assertEqual(service.snapshot(), before)


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


class CoverageContractTest(unittest.TestCase):
    def test_coverage_accepts_only_distinct_counts_within_benchmark(self):
        data={"schema":1,"benchmark_id":"deep-swe","coverage_mode":"distinct-task-selected-n-v1",
              "total_tasks":112,"latest_graded_at":"2026-09-26T12:00:00Z",
              "points":[{"model":"gpt-6-sol","effort":"high","covered_tasks":20}]}
        self.assertEqual(radar.coverage_points(data),{("gpt-6-sol","high"):(20,112)})
        for covered in (-1,113,True,2.5):
            data["points"][0]["covered_tasks"]=covered
            with self.subTest(covered=covered), self.assertRaises(ValueError):
                radar.coverage_points(data)

    def test_expired_or_unknown_coverage_headers_are_rejected(self):
        class Response:
            headers={"X-Codex-Cache":"HIT"}
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,_): return b'{}'
        response=Response()
        with patch.object(radar,"urlopen",return_value=response):
            with self.assertRaises(ValueError): radar.fetch_json(radar.COVERAGE_URL)
            response.headers.update({"X-Codex-Cache-Age":"12","X-Codex-Fetched-At":"1788782400"})
            self.assertEqual(radar.fetch_json(radar.COVERAGE_URL),{})
            response.headers["X-Codex-Cache-Age"]="300"
            with self.assertRaises(ValueError): radar.fetch_json(radar.COVERAGE_URL)


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for renderer regression tests")
class RadarRendererTest(unittest.TestCase):
    def render_script(self, script):
        # Execute the actual pure renderer helpers; no browser or account state.
        start = radar.SCRIPT.index("      const models =")
        end = radar.SCRIPT.index("      function render()")
        return subprocess.run(
            [shutil.which("node")], input=radar.SCRIPT[start:end] + "\n" + script,
            text=True, capture_output=True, check=True, timeout=5,
        ).stdout

    def test_gpt61_frontend_group_and_placeholder_efforts_match_collector(self):
        output=self.render_script('''
          const views = ['comprehensive', 'software', 'visual'].map(value => {
            mode=value;
            generation='gpt6'; const gpt6=cards([], {});
            generation='gpt5'; return {gpt6, gpt5:cards([], {})};
          });
          process.stdout.write(JSON.stringify({models:Object.keys(models), groups:generationModels, views}));
        ''')
        result=json.loads(output)
        self.assertEqual(set(result["models"]),set(radar.MODEL_NAMES))
        self.assertIn("gpt-6.1-sol",result["groups"]["gpt6"])
        self.assertNotIn("gpt-6.1-sol",result["groups"]["gpt5"])
        for view in result["views"]:
            families=ET.fromstring('<root>'+view["gpt6"]+'</root>')
            family=next(f for f in families if f.findtext('h3')=='GPT-6.1 Sol')
            scores=family.findall('./div/div')
            self.assertEqual([s.text for s in scores], ['max', 'xhigh', 'high', 'medium', 'low'])
            self.assertTrue(all(s.findtext('strong')=='—' for s in scores))
            self.assertTrue(all(s.findtext('small')=='Insufficient data' for s in scores))
            self.assertNotIn('GPT-6.1 Sol', view["gpt5"])

    def test_gpt61_eligible_scores_render_as_cards_and_chart_points(self):
        software, visual = fixtures()
        for payload, weight in ((software, 'total'), (visual, 'valid_tasks')):
            template = payload['points'][0]
            payload['points'].extend({**template, 'model':'gpt-6.1-sol', 'effort':effort,
                                      weight:30} for effort in ('low', 'medium', 'high', 'xhigh', 'max'))
        snapshot = radar.combine_snapshots(software, visual)
        output = self.render_script('const data='+json.dumps(snapshot)+''';
          root={clientWidth:1000};
          const views=Object.entries(data.views).map(([name, view])=>{
            mode=name;
            visiblePoints=view.points.filter(p=>generationModels.gpt6.includes(p.model));
            return {cards:cards(visiblePoints,data), chart:chart(visiblePoints)};
          });
          process.stdout.write(JSON.stringify(views));
        ''')
        for view in json.loads(output):
            families=ET.fromstring('<root>'+view['cards']+'</root>')
            family=next(f for f in families if f.findtext('h3')=='GPT-6.1 Sol')
            buttons=family.findall('./div/button')
            self.assertEqual(len(buttons), 5)
            svg=ET.fromstring(view['chart'])
            labels=[p.get('aria-label') for p in svg.findall('g')]
            for button in buttons:
                self.assertIn(button.get('aria-label'), labels)
                self.assertNotEqual(button.findtext('strong'), '—')
            self.assertNotIn('NaN', view['chart'])
            self.assertNotIn('Infinity', view['chart'])

    def test_two_distinct_costs_have_unique_ticks_and_use_full_plot_width(self):
        for costs in ((1, 100), (1, 1, 100)):
            with self.subTest(costs=costs):
                points = [{"model": "gpt-6-astra", "effort": radar.EFFORTS[i], "iq": 90 + i * 5,
                           "average_price_usd": cost, "average_minutes": 10,
                           "combined_cost_index": cost} for i, cost in enumerate(costs)]
                source = "root={clientWidth:1000}; visiblePoints=" + json.dumps(points)
                source += "; process.stdout.write(chart(visiblePoints));"
                output = self.render_script(source)
                svg = ET.fromstring(output)
                ticks = []
                for element in svg.findall("text"):
                    if element.get("text-anchor") != "middle":
                        continue
                    try:
                        value = float(element.text)
                    except (ValueError, TypeError):
                        continue
                    ticks.append((float(element.get("x")), value))
                positions = [x for x, _ in ticks]
                self.assertGreaterEqual(len(ticks), 2)
                self.assertEqual(len(positions), len(set(positions)))
                self.assertEqual(ticks[0][1], min(costs))
                self.assertEqual(ticks[-1][1], max(costs))
                self.assertGreater(ticks[-1][0], 900)


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
