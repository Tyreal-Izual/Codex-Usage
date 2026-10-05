from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import codex_claude_usage_web as web


@unittest.skipUnless(shutil.which('node'), 'Node.js is needed for renderer regression tests')
class ProgressiveRefreshTest(unittest.TestCase):
    def run_js(self, code):
        script = Path(__file__).with_name('static').joinpath('refresh.js').read_text(encoding='utf-8')
        result = subprocess.run([shutil.which('node')], input=script+'\n'+code,
                                text=True, capture_output=True, timeout=10, check=True)
        return json.loads(result.stdout)

    def test_fast_local_results_arrive_before_slow_online_and_force_only_isambard(self):
        result = self.run_js('''
        const requests = [], updates = [];
        let finishOnline;
        const blocked = new Promise(resolve => finishOnline = resolve);
        global.fetch = async (url, options) => {
          const report = new URL(url, 'http://local').searchParams.get('report');
          requests.push({report, method:options.method || 'GET', headers:options.headers});
          if (report === 'online-usage') await blocked;
          return {ok:true,status:200,json:async()=>({ok:true,data:{report}})};
        };
        const promise = DashboardRefresh.run({report:'all',days:'30',sources:['codex','claude','isambard'],force:true}, p => {
          updates.push(JSON.parse(JSON.stringify(p)));
          if (p.data.local_usage && p.pending.includes('online_usage')) finishOnline();
        });
        promise.then(last=>process.stdout.write(JSON.stringify({requests,updates,last})));
        ''')
        self.assertTrue(any(u['data'].get('local_usage') and 'online_usage' in u['pending'] for u in result['updates']))
        self.assertFalse(result['last']['pending'])
        self.assertTrue(result['last']['ok'])
        for request in result['requests']:
            self.assertEqual(request['method'], 'POST' if request['report']=='isambard-status' else 'GET')
        self.assertEqual(len(result['requests']), 5)

    def test_disabled_sources_make_no_requests_and_failures_stay_local(self):
        result = self.run_js('''
        const requests=[];
        global.fetch=async url=>{
          const report=new URL(url,'http://local').searchParams.get('report'); requests.push(report);
          if(report==='online-usage')throw new Error('offline');
          return {ok:true,status:200,json:async()=>({ok:true,data:{report}})};
        };
        DashboardRefresh.run({report:'all',days:'30',sources:['codex'],force:false},()=>{})
          .then(last=>process.stdout.write(JSON.stringify({requests,last})));
        ''')
        self.assertEqual(set(result['requests']), {'local-usage','online-usage','resets'})
        self.assertEqual(result['last']['data']['local_usage']['report'], 'local-usage')
        self.assertEqual(result['last']['errors'], [{'section':'online_usage','message':'offline'}])
        self.assertTrue(result['last']['data']['claude_usage']['disabled'])

    def test_inflight_requests_are_bounded(self):
        result = self.run_js('''
        let active=0, max=0;
        global.fetch=async()=>{
          active++;max=Math.max(max,active);
          await new Promise(resolve=>setTimeout(resolve,5));active--;
          return {ok:true,status:200,json:async()=>({ok:true,data:{}})};
        };
        DashboardRefresh.run({report:'all',days:'30',sources:['codex','claude','isambard']},()=>{})
          .then(()=>process.stdout.write(JSON.stringify({max})));
        ''')
        self.assertEqual(result['max'], 2)

    def test_default_get_does_not_force_public_cache(self):
        result = self.run_js('''
        let request;
        global.fetch=async(url,options)=>{
          request={url,method:options.method||'GET'};
          return {ok:true,status:200,json:async()=>({ok:true,data:{}})};
        };
        DashboardRefresh.run({report:'isambard-status',days:'30',sources:['isambard'],force:false},()=>{})
          .then(()=>process.stdout.write(JSON.stringify(request)));
        ''')
        self.assertEqual(result['method'], 'GET')
        self.assertNotIn('isambard_force_refresh', result['url'])

    def test_cancelled_refresh_stops_queued_source_requests(self):
        result = self.run_js("""
        const controller = new AbortController(), requests=[];
        global.fetch=async (url, options)=>{
          requests.push(url);
          return new Promise((resolve,reject)=>{
            options.signal.addEventListener('abort',()=>reject(new DOMException('Cancelled','AbortError')));
          });
        };
        const running=DashboardRefresh.run({report:'all',days:'30',sources:['codex','claude','isambard'],signal:controller.signal},()=>{});
        controller.abort();
        running.then(()=>process.stdout.write(JSON.stringify({count:requests.length})));
        """)
        self.assertEqual(result['count'], 2)

    def test_assembled_dashboard_and_maintenance_scripts_parse(self):
        for html in (web.INDEX_HTML.replace('__DASHBOARD_CONFIG__', '{}').replace('__DEFAULT_REFRESH__','15'), web.MAINTENANCE_HTML):
            scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
            self.assertTrue(scripts)
            for script in scripts:
                result = subprocess.run([shutil.which('node'), '--check'], input=script,
                                        text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotRegex(html, r'__[A-Z_]+__')
