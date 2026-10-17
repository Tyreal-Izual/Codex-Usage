    const CodexRadar = (() => {
      const models = {
        "gpt-6-astra": ["GPT-6 Astra", "#f97316"],
        "gpt-6.1-sol": ["GPT-6.1 Sol", "#fde047"],
        "gpt-6-sol": ["GPT-6 Sol", "#facc15"], "gpt-6-luna": ["GPT-6 Luna", "#a5b4fc"],
        "gpt-5.6-sol": ["GPT-5.6 Sol", "#eab308"], "gpt-5.6-luna": ["GPT-5.6 Luna", "#c7d2e0"]
      };
      const efforts = ["low", "medium", "high", "xhigh", "max", "ultra"];
      const benchEfforts = __RADAR_BENCH_EFFORTS__;
      const words = {
        en: {title:"Codex Radar", subtitle:"RadarBench · Score / 150",
          source:"Source: Codex Radar ↗", sync:"Synced", through:"Source data", next:"Next check", cadence:"Sync every 4 hours",
          loading:"Fetching the first benchmark snapshot…", unavailable:"Benchmark data is temporarily unavailable.",
          stale:"Showing the last successful snapshot; the next sync will retry automatically.",
          failed:"Could not read the local Radar cache. Retrying automatically.",
          cache:"The latest data could not be saved to disk.", refreshing:"Syncing…",
          table:"View all data", model:"Model", effort:"Effort", hint:"Hover, tap, or focus a card to inspect its score."},
        zh: {title:"Codex Radar", subtitle:"RadarBench · 雷达分 / 150",
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
      const fmt = (v) => v == null ? "—" : Number(v).toLocaleString(lang === "zh" ? "zh-CN" : "en-GB", {maximumSignificantDigits: 4});
      const date = (v) => v ? new Date(v).toLocaleString(lang === "zh" ? "zh-CN" : "en-GB", {month:"short", day:"numeric", hour:"2-digit", minute:"2-digit", timeZoneName:"short"}) : "—";
      const benchWords = {
        en: { score:'Radar score', provisional:'Provisional', complete:'Complete', missing_current_result:'Not graded',
          scale:'Score and bar = Radar score / 150', records:'grades',
          coverage:'Task coverage', runs:'Scoring records',
          note:'RadarBench · 64 tasks · 0–150. Latest three valid grades per task, with equal weight among covered tasks. Missing tasks are not zero. These scores are separate from legacy IQ.',
          through:'Latest grading day · UTC', status:'Status'},
        zh: { score:'雷达分', provisional:'暂定', complete:'覆盖完整', missing_current_result:'待测',
          scale:'分数和条 = 雷达分 / 满分 150', records:'题次',
          coverage:'题目覆盖', runs:'计分记录',
          note:'RadarBench · 64 道题 · 0–150 分。每题最近三次有效判分，已覆盖题目等权；缺失题目不计零。与旧基准 IQ 分开解读。',
          through:'最近判分日 · UTC', status:'状态'}
      };
      const bt = key => benchWords[lang][key];
      const scoreText = value => Number.isFinite(value) ? value.toFixed(1) : '—';
      function scoreMeter(value) {
        const known=Number.isFinite(value);
        const percent=known?Math.max(0,Math.min(100,value/150*100)):0;
        return `<span class="radar-meter${known?'':' radar-meter--missing'}" aria-hidden="true">${known?`<span class="radar-meter-fill" style="width:${percent.toFixed(4)}%"></span>`:''}</span>`;
      }
      const benchPointText = p => `${models[p.model][0]} · ${p.effort} · ${bt('score')} ${scoreText(p.iq)} / 150 · ${bt(p.score_status)} · ${bt('coverage')} ${p.coverage}/64 · ${bt('runs')} ${fmt(p.graded_runs_count)}`;
      function benchCards(points) {
        return Object.entries(benchEfforts).map(([model, supported])=>{
          const family=points.filter(p=>p.model===model);
          return `<div class="radar-family"><h3>${models[model][0]}</h3><div class="radar-scores">${supported.slice().reverse().map(effort=>{
            const p=family.find(p=>p.effort===effort);
            if(!p) return '';
            return `<button type="button" class="radar-score" style="--series-color:${models[model][1]};--score-column:${efforts.length-efforts.indexOf(effort)}" data-radar-card="${points.indexOf(p)}" aria-label="${esc(benchPointText(p))}"><span class="radar-score-heading"><span>${effort}</span><span class="radar-count">${fmt(p.graded_runs_count)} ${bt('records')}</span></span><strong>${scoreText(p.iq)}</strong>${scoreMeter(p.iq)}<small>${bt(p.score_status)} · ${p.coverage}/64</small></button>`;
          }).join('')}</div></div>`;
        }).join('');
      }
      function renderBench() {
        const data=payload?.data?.benchmark_kind==='radar-bench-v2-150'?payload.data:null, points=data?.points||[];
        visiblePoints=points;
        const key=JSON.stringify([payload,lang,localError,Math.round(root.clientWidth)]);
        if(signature===key) return;
        signature=key;
        const focused=document.activeElement;
        const focusAttr=['data-radar-card'].find(attr=>root.contains(focused)&&focused.hasAttribute(attr));
        const focusValue=focusAttr?focused.getAttribute(focusAttr):null;
        const focusSummary=root.contains(focused)&&focused.matches('summary');
        const warning=localError?t('failed'):payload?.stale?t('stale'):payload?.cache_warning?t('cache'):'';
        const toolbar=`<div class="radar-toolbar"><strong>RadarBench · ${bt('score')}</strong><a class="radar-source" href="https://codexradar.com/#intelligence-efficiency" target="_blank" rel="noopener noreferrer">${t('source')}</a></div><div class="radar-meta">${t('cadence')} · ${t('sync')}: ${date(payload?.fetched_at)} · ${bt('through')}: ${data?.source_updated_at?esc(data.source_updated_at.slice(0,10)):'—'} · ${t('next')}: ${date(payload?.next_attempt_at)}${payload?.refreshing?' · '+t('refreshing'):''}</div>${warning?`<p class="radar-warning" role="status">${warning}</p>`:''}`;
        if(!data) {root.innerHTML=toolbar+`<div class="empty" role="status">${payload?.last_error||localError?t('unavailable'):t('loading')}</div>`;return;}
        const rows=points.map(p=>[models[p.model][0],p.effort,scoreText(p.iq),`${p.coverage}/64`,bt(p.score_status),fmt(p.graded_runs_count)]);
        const table=(headers,rows)=>`<div class="table-wrap"><table><thead><tr>${headers.map(v=>`<th>${esc(v)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
        root.innerHTML=toolbar+`<p class="radar-formula">${bt('scale')}</p>${benchCards(points)}<div class="radar-detail" aria-live="polite">${t('hint')}</div><details class="radar-table" ${tableOpen?'open':''}><summary>${t('table')} · ${points.length}</summary>${table([t('model'),t('effort'),bt('score'),bt('coverage'),bt('status'),bt('runs')],rows)}<p class="radar-formula">${bt('note')}</p></details>`;
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
          age.title = `${t("sync")}: ${date(payload?.fetched_at)} · ${payload?.data?.benchmark_kind?bt("through"):t("through")}: ${payload?.data?.benchmark_kind?(payload.data.source_updated_at?.slice(0,10)||"—"):date(payload?.data?.source_updated_at)}`;
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
