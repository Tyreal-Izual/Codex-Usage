# Privacy and limitations

[Quick start](../README.md) · [中文快速开始](../README.zh-CN.md)

- The native app talks to its Python helper over private pipes and opens no HTTP port.
- Local Codex/Claude files are read for usage metadata; conversation contents are not
  displayed/exported, and transcripts are not modified. Exports may contain local paths.
- Codex online queries reuse the local signed-in account for read-only requests.
  Subscription endpoints are unofficial and may change; Admin API access is optional.
- Claude capture writes sanitized limit snapshots and its own configuration/support
  files. The optional refresher runs the normal CLI and `/usage` without a prompt;
  client startup may run configured hooks or network requests.
- Radar/Isambard fetch public pages without sending account or transcript data.
  HTTPS always verifies certificates and hostnames using the configured CA roots.
- Demo mode uses synthetic data. Setup checks do not read credentials; optional
  HTTPS diagnostics contact public endpoints without account credentials.
- The [legacy web server](../WEB_DASHBOARD.md) retains its loopback default and authentication.

Review exports before sharing, and keep credentials, private caches and account
screenshots out of Git. See [data boundaries](development.md#data-boundaries)
for accuracy boundaries; displayed values are operational information, not billing statements.
