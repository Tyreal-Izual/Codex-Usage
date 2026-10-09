from __future__ import annotations

import http.client
import json
import socket
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
            radar_service=web.DisabledRadar(),
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

    def test_source_configuration_reaches_page_and_disabled_apis(self):
        self.server.enabled_sources = frozenset({'claude'})
        self.server.default_report = 'claude-usage'
        cookie = self.session_cookie()
        status, _, page = self.request('/', cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn(b'"sources": ["claude"]', page)
        self.assertIn(b'"defaultReport": "claude-usage"', page)
        self.assertNotIn(b'__DASHBOARD_CONFIG__', page)
        with patch.object(web.codex_usage, 'collect_online_usage') as online:
            status, _, body = self.request('/api/usage?report=online-usage', cookie=cookie)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)['data']['disabled'])
        online.assert_not_called()

    def test_disabled_radar_never_constructs_a_worker(self):
        with patch.object(web.codex_radar, 'RadarService') as service:
            server = web.create_server('127.0.0.1', 0, access_token='fixture',
                allowed_hosts=[], max_workers=1, max_collectors=1, cache_seconds=0,
                enabled_sources=frozenset({'claude'}))
            try:
                server.radar_service.start()
                self.assertTrue(server.radar_service.snapshot()['disabled'])
            finally:
                server.server_close()
        service.assert_not_called()

    def test_source_switches_require_authentication_and_action_header(self):
        path = '/api/sources?isambard=false'
        self.assertEqual(self.request(path, method='POST')[0], 403)
        cookie = self.session_cookie()
        self.assertEqual(self.request(path, method='POST', cookie=cookie)[0], 403)
        self.assertEqual(self.request('/api/sources', cookie=cookie)[0], 200)
        for invalid in ('isambard=1', 'codex=false', 'radar=true&radar=false', 'radar='):
            self.assertEqual(self.request('/api/sources?'+invalid, cookie=cookie, method='POST', action='set-sources')[0], 400)

    def test_runtime_isambard_switch_bypasses_previous_report_cache(self):
        cookie = self.session_cookie()
        with patch.object(web.isambard_status, 'collect_status', return_value={'ok':True, 'status':{}}) as collect:
            self.request('/api/usage?report=isambard-status', cookie=cookie)
            self.assertEqual(collect.call_count, 1)
            status, _, body = self.request('/api/sources?isambard=false', cookie=cookie, method='POST', action='set-sources')
            self.assertEqual(status, 200)
            self.assertNotIn('isambard', json.loads(body)['sources'])
            _, _, body = self.request('/api/usage?report=isambard-status', cookie=cookie)
            self.assertTrue(json.loads(body)['data']['disabled'])
            self.assertEqual(collect.call_count, 1)
            self.request('/api/sources?isambard=true', cookie=cookie, method='POST', action='set-sources')
            _, _, body = self.request('/api/usage?report=isambard-status', cookie=cookie)
            self.assertFalse(json.loads(body)['data'].get('disabled', False))

    def test_radar_switch_pauses_and_resumes_same_worker(self):
        from unittest.mock import Mock
        service = Mock()
        self.server.radar_service = service
        cookie = self.session_cookie()
        self.request('/api/sources?radar=false', cookie=cookie, method='POST', action='set-sources')
        service.set_enabled.assert_called_with(False)
        _, _, body = self.request('/api/codex-radar', cookie=cookie)
        self.assertTrue(json.loads(body)['disabled'])
        service.snapshot.assert_not_called()
        self.request('/api/sources?radar=true', cookie=cookie, method='POST', action='set-sources')
        service.set_enabled.assert_called_with(True)
        service.start.assert_called_once()
        self.assertIs(self.server.radar_service, service)

    def test_timing_is_injected_without_visible_numeric_controls(self):
        self.server.local_days = 60
        self.server.refresh_seconds = 45
        cookie = self.session_cookie()
        _, _, body = self.request('/', cookie=cookie)
        self.assertIn(b'"days": 60', body)
        self.assertIn(b'"refreshSeconds": 45', body)
        self.assertNotIn(b'id="days"', body)
        self.assertNotIn(b'id="refresh"', body)
        self.assertIn(b'id="isambard-enabled"', body)
        self.assertIn(b'id="radar-enabled"', body)


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


class BoundedServerTest(unittest.TestCase):
    def test_busy_client_that_stays_open_cannot_stall_next_request(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = web.BoundedThreadingHTTPServer(("127.0.0.1", 0), Handler, max_workers=1)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        server._request_slots.acquire()
        reserved = True
        thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=3) as idle:
                # Do not send headers or close after reading the rejection.
                self.assertIn(b"503 Service Unavailable", idle.recv(4096))
                server._request_slots.release()
                reserved = False
                self.assertEqual(self._get_status(server.server_port), 204)
        finally:
            if reserved:
                server._request_slots.release()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

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
                for _ in range(10):
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
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()


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
