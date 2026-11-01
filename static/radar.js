    const CodexRadar = (() => {
      const models = {
        "gpt-6-astra": ["GPT-6 Astra", "#f97316"],
        "gpt-6.1-sol": ["GPT-6.1 Sol", "#fde047"],
        "gpt-6.1-terra": ["GPT-6.1 Terra", "#38bdf8"],
        "gpt-6-sol": ["GPT-6 Sol", "#facc15"], "gpt-6-luna": ["GPT-6 Luna", "#a5b4fc"],
        "gpt-5.6-sol": ["GPT-5.6 Sol", "#eab308"], "gpt-5.6-terra": ["GPT-5.6 Terra", "#60a5fa"], "gpt-5.6-luna": ["GPT-5.6 Luna", "#c7d2e0"]
      };
      const efforts = ["low", "medium", "high", "xhigh", "max", "ultra"];
      const benchEfforts = __RADAR_BENCH_EFFORTS__;
      const words = {
        en: {title:"Codex Radar", subtitle:"Degradation radar · Score / 150",
          source:"Source: Codex Radar ↗", sync:"Synced", through:"Source data", next:"Next check", cadence:"Sync every 4 hours",
          loading:"Fetching the first benchmark snapshot…", unavailable:"Benchmark data is temporarily unavailable.",
          stale:"Showing the last successful snapshot; the next sync will retry automatically.",
          failed:"Could not read the local Radar cache. Retrying automatically.",
          cache:"The latest data could not be saved to disk.", refreshing:"Syncing…",
          table:"View all data", model:"Model", effort:"Effort", hint:"Hover, tap, or focus a card to inspect its score."},
        zh: {title:"Codex Radar", subtitle:"降智雷达 · 总分 / 150",
          source:"来源：Codex Radar ↗", sync:"上次同步", through:"源数据截至", next:"下次检查", cadence:"每 4 小时同步",
          loading:"正在获取首次评测快照…", unavailable:"评测数据暂时不可用。",
          stale:"正在显示上次成功的快照；下次同步将自动重试。",
          failed:"暂时无法读取本地 Radar 缓存，将自动重试。",
          cache:"最新数据暂未保存到磁盘。", refreshing:"正在同步…",
          table:"查看完整数据", model:"模型", effort:"推理档位", hint:"悬停、点击或用键盘聚焦卡片查看雷达分。"}
      };
      let visiblePoints = [], root = null, lang = "en", payload = null, formatAge = null;
      let pending = false, checkedAt = 0, timer = null, localError = false, tableOpen = false, signature = "";
      const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
      const t = (key) => words[lang][key];
      const date = (v) => v ? new Date(v).toLocaleString(lang === "zh" ? "zh-CN" : "en-GB", {month:"short", day:"numeric", hour:"2-digit", minute:"2-digit", timeZoneName:"short"}) : "—";
      const benchWords = {
        en: {score:'Total score', name:'Degradation radar', missing:'Not tested',
          scale:'Score and bar = published total / 150',
          note:'Current homepage assessment: Qin Shi Huang, Pompeii, Pelican and Candy. Totals are read directly from the published score table, without recomputing components. Not comparable with previous RadarBench scores.',
          through:'Test period'},
        zh: {score:'总分', name:'降智雷达', missing:'未测',
          scale:'分数和条 = 官网总分 / 满分 150',
          note:'官网当前评测：秦始皇、庞贝、鹈鹕、糖果。直接读取已发布的总分，不自行合成分项成绩；不能与旧 RadarBench 分数混用。',
          through:'本轮测试'}
      };
      const bt = key => benchWords[lang][key];
      const scoreText = value => Number.isFinite(value) ? value.toFixed(2) : '—';
      function scoreMeter(value) {
        const known=Number.isFinite(value);
        const percent=known?Math.max(0,Math.min(100,value/150*100)):0;
        return `<span class="radar-meter${known?'':' radar-meter--missing'}" aria-hidden="true">${known?`<span class="radar-meter-fill" style="width:${percent.toFixed(4)}%"></span>`:''}</span>`;
      }
      const benchPointText = p => `${models[p.model][0]} · ${p.effort} · ${bt('score')} ${scoreText(p.score)} / 150${p.score==null?' · '+bt('missing'):''}`;
      function benchCards(points) {
        return Object.entries(benchEfforts).map(([model, supported])=>{
          const family=points.filter(p=>p.model===model);
          return `<div class="radar-family"><h3>${models[model][0]}</h3><div class="radar-scores">${supported.slice().reverse().map(effort=>{
            const p=family.find(p=>p.effort===effort);
            if(!p) return '';
            return `<button type="button" class="radar-score" style="--series-color:${models[model][1]};--score-column:${efforts.length-efforts.indexOf(effort)}" data-radar-card="${points.indexOf(p)}" aria-label="${esc(benchPointText(p))}"><span class="radar-score-heading"><span>${effort}</span></span><strong>${scoreText(p.score)}</strong>${scoreMeter(p.score)}</button>`;
          }).join('')}</div></div>`;
        }).join('');
      }
      function renderBench() {
        const data=payload?.data?.benchmark_kind==='codex-four-task-degradation-150'?payload.data:null, points=data?.points||[];
        visiblePoints=points;
        const key=JSON.stringify([payload,lang,localError,Math.round(root.clientWidth)]);
        if(signature===key) return;
        signature=key;
        const focused=document.activeElement;
        const focusAttr=['data-radar-card'].find(attr=>root.contains(focused)&&focused.hasAttribute(attr));
        const focusValue=focusAttr?focused.getAttribute(focusAttr):null;
        const focusSummary=root.contains(focused)&&focused.matches('summary');
        const warning=localError?t('failed'):payload?.stale?t('stale'):payload?.cache_warning?t('cache'):'';
        const toolbar=`<div class="radar-toolbar"><strong>${bt('name')} · ${bt('score')}</strong><a class="radar-source" href="https://codexradar.com/#stationmaster-round" target="_blank" rel="noopener noreferrer">${t('source')}</a></div><div class="radar-meta">${t('cadence')} · ${t('sync')}: ${date(payload?.fetched_at)} · ${bt('through')}: ${date(data?.source_started_at)} – ${date(data?.source_updated_at)} · ${t('next')}: ${date(payload?.next_attempt_at)}${payload?.refreshing?' · '+t('refreshing'):''}</div>${warning?`<p class="radar-warning" role="status">${warning}</p>`:''}`;
        if(!data) {root.innerHTML=toolbar+`<div class="empty" role="status">${payload?.last_error||localError?t('unavailable'):t('loading')}</div>`;return;}
        const rows=points.map(p=>[models[p.model][0],p.effort,scoreText(p.score)]);
        const table=(headers,rows)=>`<div class="table-wrap"><table><thead><tr>${headers.map(v=>`<th>${esc(v)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
        root.innerHTML=toolbar+`<p class="radar-formula">${bt('scale')}</p>${benchCards(points)}<div class="radar-detail" aria-live="polite">${t('hint')}</div><details class="radar-table" ${tableOpen?'open':''}><summary>${t('table')} · ${points.length}</summary>${table([t('model'),t('effort'),bt('score')],rows)}<p class="radar-formula">${bt('note')}</p></details>`;
        root.querySelector('details').addEventListener('toggle',e=>{tableOpen=e.target.open;});
        if(focusAttr) root.querySelector(`[${focusAttr}="${focusValue}"]`)?.focus({preventScroll:true});
        else if(focusSummary) root.querySelector('summary')?.focus({preventScroll:true});
      }
      function render() {
        if (!root?.isConnected) return;
        const age = root.closest('section')?.querySelector('[data-radar-age]');
        if (age) {
          const syncedAt = Date.parse(payload?.fetched_at || '');
          age.textContent = Number.isFinite(syncedAt) && formatAge ? formatAge(syncedAt) : '—';
          age.title = `${t("sync")}: ${date(payload?.fetched_at)} · ${bt("through")}: ${date(payload?.data?.source_started_at)} – ${date(payload?.data?.source_updated_at)}`;
          age.closest('.panel-heading-extra')?.classList.toggle('panel-heading-extra--warn', Boolean(payload?.stale || localError));
        }
        renderBench();
      }
      async function poll() {
        if (pending || !root?.isConnected) return;
        pending=true;
        const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),10000);
        try {
          const response=await fetch('/api/codex-radar',{cache:'no-store',signal:controller.signal});
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          payload=await response.json();
          localError=false;
        } catch (_) { localError=true; }
        finally { clearTimeout(timeout); pending=false; checkedAt=Date.now(); render(); schedule(); }
      }
      function schedule() {
        clearTimeout(timer);
        if (root?.isConnected) timer=setTimeout(poll,payload?.available?60000:5000);
      }
      const observer=new ResizeObserver(()=>render());
      return {
        title: (language) => words[language].title,
        subtitle: (language) => words[language].subtitle,
        mount(element, language, ageFormatter) {
          lang=language;
          formatAge=ageFormatter;
          if (root!==element) {
            observer.disconnect(); root=element; signature="";
            if (!root) {clearTimeout(timer); return;}
            observer.observe(root);
            const inspect=e=>{
              const marker=e.target.closest('[data-radar-card]');
              if (!marker) return;
              const p=visiblePoints[Number(marker.dataset.radarCard)];
              if (p) root.querySelector('.radar-detail').textContent=benchPointText(p);
            };
            ['pointerover','focusin','click'].forEach(event=>root.addEventListener(event,inspect));
          }
          render();
          if (Date.now()-checkedAt>5000) poll(); else schedule();
        }
      };
    })();
