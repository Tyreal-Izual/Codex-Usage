// Bounded, progressive report loading. Each source can fail independently.
const DashboardRefresh = (() => {
  const definitions = {
    local_usage: ['codex', 'local-usage'], claude_usage: ['claude', 'claude-usage'],
    reset_credits: ['codex', 'resets'], online_usage: ['codex', 'online-usage'],
    isambard_status: ['isambard', 'isambard-status'], api_usage: ['codex', 'api-usage']
  };
  const reports = {
    all: ['local_usage', 'claude_usage', 'online_usage', 'reset_credits', 'isambard_status'],
    'codex-usage': ['local_usage', 'online_usage', 'reset_credits', 'api_usage'],
    'claude-usage': ['claude_usage'], 'isambard-status': ['isambard_status']
  };
  async function request(report, days, force, signal) {
    const params = new URLSearchParams({report, top: '10', days, warn_days: '7'});
    const options = {cache: 'no-store'};
    if (force && report === 'isambard-status') {
      params.set('isambard_force_refresh', 'true');
      options.method = 'POST';
      options.headers = {'X-Codex-Usage-Action': 'force-refresh'};
    }
    for (let attempt = 0; ; attempt++) {
      if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
      const controller = new AbortController();
      const cancel = () => controller.abort();
      signal?.addEventListener("abort", cancel, {once:true});
      const timeout = setTimeout(() => controller.abort(), 130000);
      let response;
      try {
        response = await fetch(`/api/usage?${params}`, {...options, signal: controller.signal});
        if (![429, 503].includes(response.status) || attempt >= 3) {
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
          return payload;
        }
        // Consume a bounded busy response before retrying.
        await response.text();
      } finally {
        clearTimeout(timeout);
        signal?.removeEventListener("abort", cancel);
      }
      const delay = Math.min(30, Math.max(1, Number(response.headers.get('Retry-After')) || 1));
      await new Promise((resolve, reject) => {
        if (signal?.aborted) { reject(new DOMException("Cancelled", "AbortError")); return; }
        const cancel = () => { clearTimeout(timer); reject(new DOMException("Cancelled", "AbortError")); };
        const timer = setTimeout(() => {signal?.removeEventListener("abort", cancel); resolve();}, delay * 1000);
        signal?.addEventListener("abort", cancel, {once:true});
      });
    }
  }
  async function run(settings, onUpdate) {
    const names = reports[settings.report] || [];
    const data = {};
    const failures = {};
    const jobs = [];
    for (const name of names) {
      const [source] = definitions[name];
      if (!settings.sources.includes(source) || (name === 'api_usage' && !settings.adminEnabled)) {
        data[name] = {ok: true, disabled: true, source};
      } else {
        jobs.push(name);
      }
    }
    const pending = new Set(jobs);
    function emit() {
      const payload = {
        report: settings.report,
        ok: Object.keys(failures).length === 0,
        errors: Object.values(failures),
        pending: [...pending],
        data: ['all', 'codex-usage'].includes(settings.report) ? {...data} : data[names[0]] || {},
        served_at_local: new Date().toLocaleString()
      };
      onUpdate(payload);
      return payload;
    }
    emit();
    async function worker() {
      while (jobs.length && !settings.signal?.aborted) {
        const name = jobs.shift();
        try {
          const payload = await request(definitions[name][1], settings.days, settings.force, settings.signal);
          data[name] = payload.data;
          if (!payload.ok) {
            failures[name] = {section: name, message: payload.errors?.map(e => e.message).join('; ') || 'Source unavailable'};
          }
        } catch (error) {
          const message = error.name === 'AbortError' ? 'Request timed out' : String(error.message || error);
          data[name] = {ok: false, error: {message}};
          failures[name] = {section: name, message};
        }
        pending.delete(name);
        emit();
      }
    }
    await Promise.all([worker(), worker()]);
    return emit();
  }
  return {run};
})();
