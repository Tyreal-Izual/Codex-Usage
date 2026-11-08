from __future__ import annotations

import io
import os
import ssl
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import codex_usage
import usage_common


class TLSTransportTest(unittest.TestCase):
    def test_system_bundle_loads_roots_and_keeps_verification_enabled(self):
        with patch.dict(os.environ, {}, clear=True):
            context = usage_common.ssl_context()
        self.assertGreater(context.cert_store_stats()['x509_ca'], 0)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_explicit_invalid_ca_override_fails_instead_of_silently_falling_back(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'SSL_CERT_FILE': str(Path(directory) / 'missing.pem')}):
                with self.assertRaises(FileNotFoundError): usage_common.ssl_context()

    def test_both_codex_transports_use_the_shared_verified_context(self):
        with patch.dict(os.environ, {}, clear=True):
            context = usage_common.ssl_context()
        response = Mock(status=200, read=lambda: b'{}')
        manager = Mock(__enter__=lambda _: response, __exit__=lambda *args: None)
        with patch.object(codex_usage, 'ssl_context', return_value=context) as make_context:
            with patch('urllib.request.urlopen', return_value=manager) as request:
                self.assertTrue(codex_usage.fetch_json('/fixture', 'fake-token', 'fake-account')['ok'])
                self.assertTrue(codex_usage.fetch_admin_json('/fixture', {}, 'fake-key')['ok'])
        self.assertEqual(make_context.call_count, 2)
        for call in request.call_args_list:
            self.assertIs(call.kwargs['context'], context)
            self.assertEqual(call.kwargs['timeout'], 25)

    def test_real_https_rejects_an_untrusted_local_server_for_both_transports(self):
        # Public, untrusted test identity: no platform-specific openssl executable.
        fixtures = Path(__file__).resolve().parent / 'tests' / 'fixtures'
        cert = fixtures / 'untrusted-localhost.cert.pem'
        key = fixtures / 'untrusted-localhost.key.pem'
        server = HTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(cert, key)
        server.socket = server_context.wrap_socket(server.socket, server_side=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        url = f'https://127.0.0.1:{server.server_port}'
        try:
            with patch.dict(os.environ, {'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1'}, clear=True):
                subscription = codex_usage.fetch_json(url, 'fake-token', 'fake-account', timeout=3)
                with patch.object(codex_usage, 'ADMIN_API_BASE', url):
                    admin = codex_usage.fetch_admin_json('/fixture', {}, 'fake-key', timeout=3)
            for result in (subscription, admin):
                self.assertFalse(result['ok'])
                self.assertIn('CERTIFICATE_VERIFY_FAILED', result['error'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)

    def test_trust_diagnostics_are_offline_by_default(self):
        with patch('urllib.request.urlopen') as request:
            result = usage_common.tls_diagnostics()
        request.assert_not_called()
        self.assertTrue(result['ok'])
        self.assertNotIn('probes', result)

    def test_public_probe_counts_http_errors_as_verified_tls_without_credentials(self):
        def forbidden(request, **kwargs):
            self.assertEqual(request.get_method(), 'HEAD')
            self.assertFalse(request.has_header('Authorization'))
            self.assertFalse(request.has_header('Cookie'))
            self.assertEqual(kwargs['context'].verify_mode, ssl.CERT_REQUIRED)
            raise HTTPError(request.full_url, 403, 'Forbidden', {}, io.BytesIO())
        with patch('urllib.request.urlopen', side_effect=forbidden):
            result = usage_common.tls_diagnostics(probe=True)
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['probes']), 2)
        self.assertTrue(all(item['tls_verified'] and item['http_status'] == 403 for item in result['probes']))


if __name__ == '__main__':
    unittest.main()
