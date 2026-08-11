from __future__ import annotations

import http.client
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from unittest.mock import patch

import codex_claude_usage_web as web


class UsageWebSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.access_token = "test-access-token"
        self.server = web.create_server(
            "127.0.0.1",
            0,
            access_token=self.access_token,
            allowed_hosts=["127.0.0.1", "localhost"],
            max_workers=2,
            max_collectors=1,
            cache_seconds=30,
        )
        self.port = int(self.server.server_address[1])
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.server_thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)

    def request(
        self,
        path: str,
        *,
        host: str | None = None,
        cookie: str | None = None,
        authorization: str | None = None,
        method: str = "GET",
        action: str | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if cookie:
            headers["Cookie"] = cookie
        if authorization:
            headers["Authorization"] = authorization
        if action:
            headers[web.FORCE_REFRESH_ACTION_HEADER] = action
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        result = response.status, dict(response.getheaders()), body
        connection.close()
        return result

    def session_cookie(self) -> str:
        status, headers, _ = self.request(f"/?access_token={self.access_token}")
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("Location"), "/")
        cookie = headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        return cookie.split(";", 1)[0]

    def test_rejects_unrecognized_host_before_collecting(self) -> None:
        with patch.object(web, "collect_report") as collector:
            status, _, _ = self.request(
                "/api/usage?report=local-usage",
                host=f"attacker.example:{self.port}",
                cookie=f"{web.ACCESS_COOKIE_NAME}={self.access_token}",
            )

        self.assertEqual(status, 421)
        collector.assert_not_called()

    def test_requires_session_capability_before_collecting(self) -> None:
        with patch.object(web, "collect_report") as collector:
            status, _, _ = self.request("/api/usage?report=local-usage")

        self.assertEqual(status, 403)
        collector.assert_not_called()

    def test_requires_session_capability_for_dashboard_html(self) -> None:
        status, _, _ = self.request("/")

        self.assertEqual(status, 403)

    def test_invalid_bootstrap_token_is_rejected(self) -> None:
        status, headers, _ = self.request("/?access_token=wrong")

        self.assertEqual(status, 403)
        self.assertNotIn("Set-Cookie", headers)

    def test_bearer_capability_allows_direct_api_usage(self) -> None:
        stub_data = {"ok": True, "local_usage": {"session_files": 0}}
        with patch.object(web, "collect_report", return_value=(stub_data, [])):
            status, _, body = self.request(
                "/api/usage?report=local-usage",
                authorization=f"Bearer {self.access_token}",
            )

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["data"], stub_data)

    def test_bootstrap_cookie_allows_legitimate_usage_request(self) -> None:
        cookie = self.session_cookie()
        stub_data = {"ok": True, "local_usage": {"session_files": 0}}
        with patch.object(web, "collect_report", return_value=(stub_data, [])) as collector:
            status, _, body = self.request(
                "/api/usage?report=local-usage",
                cookie=cookie,
            )

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["data"], stub_data)
        collector.assert_called_once()

    def test_session_cookie_allows_dashboard_html(self) -> None:
        cookie = self.session_cookie()
        status, _, body = self.request("/", cookie=cookie)

        self.assertEqual(status, 200)
        self.assertIn(b"Codex &amp; Claude Code Usage", body)

    def test_admin_limit_is_capped_before_collection(self) -> None:
        cookie = self.session_cookie()
        with patch.object(web, "collect_report", return_value=({}, [])) as collector:
            status, _, _ = self.request(
                "/api/usage?report=codex-usage&limit=999999999",
                cookie=cookie,
            )

        self.assertEqual(status, 200)
        self.assertEqual(collector.call_args.kwargs["limit"], web.MAX_ADMIN_LIMIT)

    def test_distinct_api_collection_is_rate_limited_at_capacity(self) -> None:
        cookie = self.session_cookie()
        started = threading.Event()
        release = threading.Event()

        def collect_report(**_: object) -> tuple[dict[str, bool], list[str]]:
            started.set()
            self.assertTrue(release.wait(timeout=3))
            return {"ok": True}, []

        with patch.object(web, "collect_report", side_effect=collect_report):
            with ThreadPoolExecutor(max_workers=1) as executor:
                first = executor.submit(
                    self.request,
                    "/api/usage?report=local-usage&days=30",
                    cookie=cookie,
                )
                self.assertTrue(started.wait(timeout=3))
                status, headers, _ = self.request(
                    "/api/usage?report=local-usage&days=31",
                    cookie=cookie,
                )
                release.set()
                first_status, _, _ = first.result(timeout=3)

        self.assertEqual(status, 429)
        self.assertEqual(headers.get("Retry-After"), "1")
        self.assertEqual(first_status, 200)

    def test_force_refresh_requires_post_action_and_is_rate_limited(self) -> None:
        cookie = self.session_cookie()
        path = "/api/usage?report=isambard-status&isambard_force_refresh=true"
        with patch.object(web, "collect_report", return_value=({}, [])) as collector:
            get_status, get_headers, _ = self.request(path, cookie=cookie)
            missing_action_status, _, _ = self.request(
                path,
                cookie=cookie,
                method="POST",
            )
            post_status, _, _ = self.request(
                path,
                cookie=cookie,
                method="POST",
                action=web.FORCE_REFRESH_ACTION,
            )
            limited_status, limited_headers, _ = self.request(
                path + "&days=31",
                cookie=cookie,
                method="POST",
                action=web.FORCE_REFRESH_ACTION,
            )

        self.assertEqual(get_status, 405)
        self.assertEqual(get_headers.get("Allow"), "POST")
        self.assertEqual(missing_action_status, 403)
        self.assertEqual(post_status, 200)
        self.assertEqual(limited_status, 429)
        self.assertGreaterEqual(int(limited_headers["Retry-After"]), 1)
        collector.assert_called_once()


class HostValidationTest(unittest.TestCase):
    def test_accepts_only_expected_host_and_port_forms(self) -> None:
        allowed = {"127.0.0.1", "localhost", "::1"}

        self.assertTrue(web.host_is_allowed("127.0.0.1:8765", allowed, 8765))
        self.assertTrue(web.host_is_allowed("LOCALHOST.:8765", allowed, 8765))
        self.assertTrue(web.host_is_allowed("[::1]:8765", allowed, 8765))
        self.assertTrue(web.host_is_allowed("localhost", allowed, 80))
        self.assertFalse(web.host_is_allowed("localhost", allowed, 8765))
        self.assertFalse(web.host_is_allowed("127.0.0.1:8766", allowed, 8765))
        self.assertFalse(web.host_is_allowed("127.0.0.1:", allowed, 8765))
        self.assertFalse(web.host_is_allowed("127.0.0.1/path", allowed, 8765))
        self.assertFalse(web.host_is_allowed("127.0.0.1#attacker", allowed, 8765))
        self.assertFalse(web.host_is_allowed("attacker.example:8765", allowed, 8765))

    def test_wildcard_bind_requires_explicit_allowed_host(self) -> None:
        with self.assertRaisesRegex(ValueError, "allowed-host"):
            web.allowed_hostnames("0.0.0.0", [])


class DashboardScriptTest(unittest.TestCase):
    def test_manual_refresh_uses_post_only_for_isambard_reports(self) -> None:
        self.assertIn(
            'const forceSourceRefresh = forceIsambardRefresh\n'
            '          && ["all", "isambard-status"].includes($("report").value);',
            web.INDEX_HTML,
        )
        self.assertIn("fetch(queryUrl(forceSourceRefresh), options)", web.INDEX_HTML)


class BoundedServerTest(unittest.TestCase):
    def test_excess_http_request_is_rejected_without_spawning_a_worker(self) -> None:
        started = threading.Event()
        release = threading.Event()

        class BlockingHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server API name.
                started.set()
                release.wait(timeout=3)
                self.send_response(204)
                self.end_headers()

            def log_message(self, fmt: str, *args: object) -> None:
                pass

        server = web.BoundedThreadingHTTPServer(
            ("127.0.0.1", 0),
            BlockingHandler,
            max_workers=1,
        )
        port = int(server.server_address[1])
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                first = executor.submit(self._get_status, port)
                self.assertTrue(started.wait(timeout=3))
                self.assertEqual(self._get_status(port), 503)
                release.set()
                self.assertEqual(first.result(timeout=3), 204)
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

    @staticmethod
    def _get_status(port: int) -> int:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("GET", "/")
        response = connection.getresponse()
        response.read()
        status = response.status
        connection.close()
        return status


class ReportCoordinatorTest(unittest.TestCase):
    def test_completed_result_is_cached(self) -> None:
        coordinator = web.ReportCoordinator(cache_seconds=30, max_collectors=1)
        calls = 0

        def collect() -> dict[str, int]:
            nonlocal calls
            calls += 1
            return {"call": calls}

        self.assertEqual(coordinator.get_or_collect(("cached",), collect), {"call": 1})
        self.assertEqual(coordinator.get_or_collect(("cached",), collect), {"call": 1})
        self.assertEqual(calls, 1)

    def test_identical_inflight_requests_share_one_collection(self) -> None:
        coordinator = web.ReportCoordinator(cache_seconds=30, max_collectors=1)
        started = threading.Event()
        release = threading.Event()
        results: list[dict[str, bool]] = []
        calls = 0

        def collect() -> dict[str, bool]:
            nonlocal calls
            calls += 1
            started.set()
            self.assertTrue(release.wait(timeout=2))
            return {"ok": True}

        def run() -> None:
            results.append(coordinator.get_or_collect(("same",), collect))

        first = threading.Thread(target=run)
        second = threading.Thread(target=run)
        first.start()
        self.assertTrue(started.wait(timeout=2))
        second.start()
        release.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertEqual(calls, 1)
        self.assertEqual(results, [{"ok": True}, {"ok": True}])

    def test_distinct_collection_is_rejected_at_capacity(self) -> None:
        coordinator = web.ReportCoordinator(cache_seconds=30, max_collectors=1)
        started = threading.Event()
        release = threading.Event()

        def collect() -> dict[str, bool]:
            started.set()
            self.assertTrue(release.wait(timeout=2))
            return {"ok": True}

        worker = threading.Thread(
            target=lambda: coordinator.get_or_collect(("first",), collect)
        )
        worker.start()
        self.assertTrue(started.wait(timeout=2))
        try:
            with self.assertRaises(web.CollectionBusy):
                coordinator.get_or_collect(("second",), lambda: {"ok": True})
        finally:
            release.set()
            worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
