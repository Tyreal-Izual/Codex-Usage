    const CodexRadar = (() => {
      const models = {
        "gpt-6-astra": ["GPT-6 Astra", "#f97316"],
        "gpt-6.1-sol": ["GPT-6.1 Sol", "#fde047"],
        "gpt-6-sol": ["GPT-6 Sol", "#facc15"], "gpt-6-luna": ["GPT-6 Luna", "#a5b4fc"],
        "gpt-5.6-sol": ["GPT-5.6 Sol", "#eab308"],
        "gpt-5.6-terra": ["GPT-5.6 Terra", "#60a5fa"], "gpt-5.6-luna": ["GPT-5.6 Luna", "#c7d2e0"],
        "gpt-5.5": ["GPT-5.5", "#00e5ff"]
      };
      const efforts = ["low", "medium", "high", "xhigh", "max", "ultra"];
      const generationModels = __RADAR_GENERATIONS__;
      const modelEfforts = __RADAR_MODEL_EFFORTS__;
      const thresholdModels = __RADAR_THRESHOLD_MODELS__;
      const words = {
        en: { comprehensive: "Composite", software: "Software engineering", visual: "Visual-spatial",
          coverage: "distinct tasks", generation: "Model generation", benchmark: "Benchmark", insufficient: "Insufficient data", softwareOnly: "Software only",
          lowCoverage: "Task coverage <60%", unknownCoverage: "Coverage unavailable", samples: "Samples SWE / visual",
          noPlot: "No plottable values for this metric in this group.", median: "Median cost", mean: "Mean cost", weighted: "Weighted cost", unknown: "Cost",
          threshold: "GPT-6.1 Sol and GPT-6 Sol/Luna need 30 valid software samples for composite IQ. Visual contributes only at 30 samples; missing scores are never zero. Task coverage is a separate quality measure.",
          title: "Codex Radar", subtitle: "Model benchmarks · Cost × IQ", metric: "Metric",
          combined: "Combined cost × IQ", time: "Time cost × IQ", price: "Price cost × IQ",
          efficient: "Upper-left is more efficient", source: "Source: Codex Radar ↗",
          sync: "Synced", through: "Source data", next: "Next check", cadence: "Sync every 4 hours",
          loading: "Fetching the first benchmark snapshot…", unavailable: "Benchmark data is temporarily unavailable.",
          stale: "Showing the last successful snapshot; the next sync will retry automatically.",
          failed: "Could not read the local Radar cache. Retrying automatically.",
          cache: "The latest data could not be saved to disk.", refreshing: "Syncing…",
          combinedAxis: "Relative combined cost index (log scale)", timeAxis: "Average duration · minutes (log scale)",
          priceAxis: "Cost · USD (log scale)", table: "View all data", model: "Model", effort: "Effort",
          cost: "Cost index", minutes: "Minutes", usd: "USD", hint: "Hover, tap, or focus a point to inspect its values.",
          formula: "Community benchmark scores. Composite scores use eligible component samples. Source costs may be medians; the composite is weighted. Cost ∝ price × (minutes / 10)^3.053; the largest cost in the selected generation and benchmark is normalized to 100. A // mark indicates a compressed gap on the log axis." },
        zh: { comprehensive: "综合智能", software: "软件工程能力", visual: "视觉空间推理",
          coverage: "独立题", generation: "模型代际", benchmark: "评测维度", insufficient: "数据不足", softwareOnly: "仅软件工程",
          lowCoverage: "独立题覆盖 <60%", unknownCoverage: "覆盖率未知", samples: "样本数 SWE / 视觉",
          noPlot: "当前分组在此指标下暂无可绘制的数据。", median: "费用中位数", mean: "平均费用", weighted: "加权费用", unknown: "费用",
          threshold: "GPT-6.1 Sol 和 GPT-6 Sol/Luna 的软件工程样本达到 30 份后可显示综合分；视觉样本达到 30 份才参与加权，缺失不计零。独立题覆盖率是另外的质量指标。",
          title: "Codex Radar", subtitle: "模型评测 · 成本 × IQ", metric: "切换指标",
          combined: "综合成本 × IQ", time: "时间成本 × IQ", price: "费用成本 × IQ",
          efficient: "越靠左上越高效", source: "来源：Codex Radar ↗",
          sync: "上次同步", through: "源数据截至", next: "下次检查", cadence: "每 4 小时同步",
          loading: "正在获取首次评测快照…", unavailable: "评测数据暂时不可用。",
          stale: "正在显示上次成功的快照；下次同步将自动重试。",
          failed: "暂时无法读取本地 Radar 缓存，将自动重试。",
          cache: "最新数据暂未保存到磁盘。", refreshing: "正在同步…",
          combinedAxis: "相对综合成本指数（对数刻度）", timeAxis: "平均耗时 · 分钟（对数刻度）",
          priceAxis: "费用 · USD（对数刻度）", table: "查看完整数据", model: "模型", effort: "推理档位",
          cost: "成本指数", minutes: "分钟", usd: "USD", hint: "悬停、点击或用键盘聚焦数据点查看数值。",
          formula: "社区评测分数。综合指标按符合门槛的有效样本加权；源费用可能为中位数。综合成本 ∝ 费用 × (分钟 / 10)^3.053，所选代际及评测维度内最高成本归一为 100。横轴 // 表示压缩的对数区间。" }
      };
      let generation = "gpt6", mode = "comprehensive", visiblePoints = [];
      let root = null, lang = "en", metric = "combined", payload = null, formatAge = null;
      let pending = false, checkedAt = 0, timer = null, localError = false, tableOpen = false, signature = "";
      const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
      const t = (key) => words[lang][key];
      const fmt = (v) => v == null ? "—" : Number(v).toLocaleString(lang === "zh" ? "zh-CN" : "en-GB", {maximumSignificantDigits: 4});
      const tick = (v) => v >= 10 ? String(Math.round(v)) : v >= 1 ? v.toFixed(1)
        : v >= .01 ? v.toFixed(2) : v >= .0001 ? v.toFixed(4) : v.toExponential(1);
      const date = (v) => v ? new Date(v).toLocaleString(lang === "zh" ? "zh-CN" : "en-GB", {month:"short", day:"numeric", hour:"2-digit", minute:"2-digit", timeZoneName:"short"}) : "—";
      function coverageText(p) {
        if (!generationModels.gpt6.includes(p.model)) return '';
        const ratio=(n,total)=>n==null||total==null||total<=0?'—':`${fmt(n)}/${fmt(total)}`;
        const parts=[];
        if(mode!=='visual') parts.push(`SWE ${t('coverage')} ${ratio(p.software_covered_tasks,p.software_benchmark_tasks)}`);
        if(mode!=='software') parts.push(`${t('visual')} ${t('coverage')} ${ratio(p.visual_samples,p.visual_benchmark_tasks)}`);
        return parts.join(' · ');
      }
      const pointText = (p) => `${models[p.model][0]} · ${p.effort} · IQ ${fmt(p.iq)} · ${t("cost")} ${fmt(p.combined_cost_index)} · ${t(p.price_aggregation || "unknown")} $${fmt(p.average_price_usd)} · ${fmt(p.average_minutes)} ${t("minutes")} · ${t("samples")} ${fmt(p.software_samples)} / ${fmt(p.visual_samples)}${mode === "comprehensive" && p.score_basis === "software" ? " · " + t("softwareOnly") : ""}${coverageText(p) ? " · " + coverageText(p) : ""}`;
      function quality(p) {
        if (!generationModels.gpt6.includes(p.model)) return '';
        const components = [];
        if (mode !== 'visual') components.push([p.software_covered_tasks, p.software_benchmark_tasks]);
        if (mode !== 'software') components.push([p.visual_samples, p.visual_benchmark_tasks]);
        if (components.some(([n,total]) => n == null || total == null || total <= 0 || n > total)) return t('unknownCoverage');
        return components.some(([n,total]) => n / total < .6) ? t('lowCoverage') : '';
      }
      function cards(points, data) {
        return Object.entries(models).filter(([model]) => generationModels[generation].includes(model)).map(([model,[name,color]]) => {
          const rows=points.filter(p => p.model===model);
          const expected=thresholdModels.includes(model)
            ? modelEfforts[model] : rows.map(p=>p.effort);
          if (!expected.length) return '';
          return `<div class="radar-family"><h3>${name}</h3><div class="radar-scores">${expected.slice().reverse().map(effort=>{
            const p=rows.find(p=>p.effort===effort);
            const sample=(data?.samples||[]).find(p=>p.model===model&&p.effort===effort);
            if (!p) return `<div class="radar-score" style="--series-color:${color}">${effort}<strong>—</strong><small>${t('insufficient')}</small><small>SWE ${fmt(sample?.software_samples)} / ${fmt(sample?.visual_samples)}</small></div>`;
            const note=quality(p);
            return `<button type="button" class="radar-score" style="--series-color:${color}" data-radar-card="${points.indexOf(p)}" aria-label="${esc(pointText(p))}">${effort}<strong>${fmt(p.iq)}</strong><small>$${fmt(p.average_price_usd)} · ${fmt(p.average_minutes)} ${t('minutes')}</small>${mode==='comprehensive'&&p.score_basis==='software'?`<small>${t('softwareOnly')}</small>`:''}${note?`<small class="radar-quality">${note}</small>`:''}</button>`;
          }).join('')}</div></div>`;
        }).join('');
      }
      const shape = (effort, color) => {
        const attrs = `fill="var(--panel)" stroke="${color}" stroke-width="2.5"`;
        if (effort === "low") return `<circle r="5" ${attrs}/>`;
        if (effort === "high") return `<rect x="-5" y="-5" width="10" height="10" rx="1" ${attrs}/>`;
        const counts = {medium:3, xhigh:4, max:6, ultra:10};
        const count = counts[effort], offset = -Math.PI / 2;
        const pts = Array.from({length:count}, (_,i) => {
          const r = effort === "ultra" && i % 2 ? 3 : 6;
          const angle = offset + i * Math.PI * 2 / count;
          return `${(Math.cos(angle)*r).toFixed(2)},${(Math.sin(angle)*r).toFixed(2)}`;
        }).join(" ");
        return `<polygon points="${pts}" ${attrs}/>`;
      };
      function chart(points) {
        const width = Math.max(300, Math.min(1080, root.clientWidth));
        const compact = width < 620, height = compact ? 340 : 440;
        const left = 44, right = 20, top = 26, bottom = 54, pw = width-left-right, ph = height-top-bottom;
        const field = {combined:"combined_cost_index", time:"average_minutes", price:"average_price_usd"}[metric];
        points = points.filter(p => Number.isFinite(p[field]) && p[field] > 0 && Number.isFinite(p.iq));
        if (!points.length) return `<div class="empty">${t('noPlot')}</div>`;
        const values = [...new Set(points.map(p => p[field]))].sort((a,b) => a-b);
        const min = values[0], max = values.at(-1), second = values[1];
        // A broken axis needs a non-degenerate range after the isolated minimum.
        const broken = values.length > 2 && second / min >= 4, gap = compact ? .19 : .14;
        const logShare = (v,a,b) => a === b ? .5 : Math.log(v/a)/Math.log(b/a);
        const x = (v) => left + pw * (broken ? (v < second ? 0 : gap + (1-gap)*logShare(v,second,max)) : logShare(v,min,max));
        const yMax = Math.min(150, Math.max(20, Math.ceil(Math.max(...points.map(p => p.iq))/20)*20));
        const y = (v) => top + ph * (1-v/yMax);
        const tickMin = broken ? second : min;
        const count = compact ? 3 : 5;
        const ticks = min === max ? [min] : (broken ? [min] : []).concat(Array.from({length:count+1}, (_,i) => tickMin * (max/tickMin)**(i/count)));
        let svg = `<svg viewBox="0 0 ${width} ${height}" role="group" aria-label="${esc(t(metric))}"><title>${esc(t(metric))}</title>`;
        ticks.forEach(v => { svg += `<line class="radar-grid" x1="${x(v)}" y1="${top}" x2="${x(v)}" y2="${height-bottom}"/><text class="radar-tick" text-anchor="middle" x="${x(v)}" y="${height-bottom+22}">${esc(tick(v))}</text>`; });
        for (let i=0; i<=6; i++) {
          const v=yMax*i/6;
          svg += `<line class="radar-grid" x1="${left}" y1="${y(v)}" x2="${width-right}" y2="${y(v)}"/><text class="radar-tick" text-anchor="end" x="${left-9}" y="${y(v)+4}">${Math.round(v)}</text>`;
        }
        svg += `<path class="radar-axis" d="M${left} ${top}V${height-bottom}H${width-right}"/>`;
        if (broken) {
          const bx=left+pw*gap/2, by=height-bottom;
          svg += `<path class="radar-axis" stroke-width="2" d="M${bx-6} ${by+4}l5 -8 M${bx} ${by+4}l5 -8"/>`;
        }
        Object.entries(models).forEach(([model, [name,color]], familyIndex) => {
          const series=points.filter(p => p.model===model).sort((a,b) => efforts.indexOf(a.effort)-efforts.indexOf(b.effort));
          if (!series.length) return;
          svg += `<path d="${series.map((p,i) => `${i?'L':'M'}${x(p[field])},${y(p.iq)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2"/>`;
          series.forEach((p,i) => {
            const index=visiblePoints.indexOf(p), px=x(p[field]), py=y(p.iq);
            svg += `<g class="radar-point" data-radar-point="${index}" tabindex="0" role="img" aria-label="${esc(pointText(p))}" transform="translate(${px},${py})"><circle class="radar-hit" r="13" fill="transparent"/>${shape(p.effort,color)}</g>`;
            if (!compact) svg += `<text class="radar-label" pointer-events="none" text-anchor="middle" x="${px}" y="${py+((familyIndex+i)%2?20:-12)}">${esc(p.effort)}</text>`;
          });
        });
        return svg + `<text class="radar-tick" text-anchor="middle" x="${left+pw/2}" y="${height-6}">${esc(t(metric+'Axis'))}</text><text class="radar-tick" x="10" y="16">IQ</text></svg>`;
      }
      function render() {
        if (!root?.isConnected) return;
        const age = root.closest('section')?.querySelector('[data-radar-age]');
        if (age) {
          const syncedAt = Date.parse(payload?.fetched_at || '');
          age.textContent = Number.isFinite(syncedAt) && formatAge ? formatAge(syncedAt) : '—';
          age.title = `${t("sync")}: ${date(payload?.fetched_at)} · ${t("through")}: ${date(payload?.data?.source_updated_at)}`;
          age.closest('.panel-heading-extra')?.classList.toggle('panel-heading-extra--warn', Boolean(payload?.stale || localError));
        }
        const key=JSON.stringify([payload,lang,metric,mode,generation,localError,Math.round(root.clientWidth)]);
        if (signature===key) return;
        signature=key;
        const focused=document.activeElement;
        const activePoint=root.contains(focused) ? focused.getAttribute('data-radar-point') : null;
        const activeCard=root.contains(focused) ? focused.getAttribute('data-radar-card') : null;
        const activeMode=root.contains(focused) ? focused.getAttribute('data-radar-mode') : null;
        const activeGeneration=root.contains(focused) ? focused.getAttribute('data-radar-generation') : null;
        const activeSelector=root.contains(focused) && focused.matches('[data-radar-metric]');
        const activeSummary=root.contains(focused) && focused.matches('summary');
        const p=payload, data=p?.data;
        const view=data?.views?.[mode];
        const points=(view?.points || (mode==='comprehensive' ? data?.points : []) || []).filter(p=>generationModels[generation].includes(p.model));
        visiblePoints=points;
        const warning=localError ? t("failed") : p?.stale ? t("stale") : p?.cache_warning ? t("cache") : "";
        const meta=p ? `${t("cadence")} · ${t("sync")}: ${date(p.fetched_at)} · ${t("through")}: ${date(view?.source_updated_at || data?.source_updated_at)} · ${t("next")}: ${date(p.next_attempt_at)}` : t("cadence");
        const tabs=`<div class="radar-tabs" role="group" aria-label="${t('benchmark')}">${['comprehensive','software','visual'].map(k=>`<button type="button" data-radar-mode="${k}" aria-pressed="${k===mode}">${t(k)}</button>`).join('')}</div><div class="radar-tabs" role="group" aria-label="${t('generation')}">${['gpt6','gpt5'].map(k=>`<button type="button" data-radar-generation="${k}" aria-pressed="${k===generation}">${k==='gpt6'?'GPT-6':'GPT-5'}</button>`).join('')}</div>`;
        const toolbar=tabs+`<div class="radar-toolbar"><label>${t("metric")}<select aria-label="${t("metric")}" data-radar-metric>${["combined","time","price"].map(k=>`<option value="${k}" ${k===metric?'selected':''}>${t(k)}</option>`).join('')}</select></label><a class="radar-source" href="https://codexradar.com/" target="_blank" rel="noopener noreferrer">${t("source")}</a></div><div class="radar-meta">${esc(meta)}${p?.refreshing?' · '+t("refreshing"):''}</div>${warning?`<p class="radar-warning" role="status">${warning}</p>`:''}`;
        if (!data) {
          root.innerHTML=toolbar+`<div class="empty" role="status">${p?.last_error || localError ? t("unavailable") : t("loading")}</div>`;
          return;
        }
        // Build the chart before replacing DOM: measuring a temporarily empty
        // panel can clamp the page scroll position during a background refresh.
        root.innerHTML=toolbar+`${generation==='gpt6'?`<p class="radar-formula">${t('threshold')}</p>`:''}${cards(points,data)}<div class="radar-legend">${Object.entries(models).filter(([m])=>points.some(p=>p.model===m)).map(([, [name,color]])=>`<span><i style="background:${color}"></i>${name}</span>`).join('')}<span>${t("efficient")}</span></div><div class="radar-chart">${chart(points)}</div><div class="radar-detail" aria-live="polite">${t("hint")}</div><p class="radar-formula">${t("formula")}</p><details class="radar-table" ${tableOpen?'open':''}><summary>${t("table")} · ${points.length}</summary><div class="table-wrap"><table><thead><tr>${[t("model"),t("effort"),"IQ",t("cost"),t("usd"),t("minutes"),t("samples")].map(v=>`<th>${v}</th>`).join('')}</tr></thead><tbody>${points.map(p=>`<tr>${[models[p.model][0],p.effort,fmt(p.iq),fmt(p.combined_cost_index),fmt(p.average_price_usd),fmt(p.average_minutes),`${fmt(p.software_samples)} / ${fmt(p.visual_samples)}`].map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
        root.querySelector("details").addEventListener("toggle", e => {tableOpen=e.target.open;});
        if (activePoint!==null) root.querySelector(`[data-radar-point="${activePoint}"]`)?.focus({preventScroll:true});
        else if (activeCard!==null) root.querySelector(`[data-radar-card="${activeCard}"]`)?.focus({preventScroll:true});
        else if (activeMode!==null) root.querySelector(`[data-radar-mode="${activeMode}"]`)?.focus({preventScroll:true});
        else if (activeGeneration!==null) root.querySelector(`[data-radar-generation="${activeGeneration}"]`)?.focus({preventScroll:true});
        else if (activeSelector) root.querySelector('select').focus({preventScroll:true});
        else if (activeSummary) root.querySelector('summary').focus({preventScroll:true});
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
            root.addEventListener("change", e=>{
              if (e.target.matches('[data-radar-metric]')) {
                metric=e.target.value; render(); root.querySelector('select').focus();
              }
            });
            root.addEventListener('click', e=>{
              const button=e.target.closest('[data-radar-mode], [data-radar-generation]');
              if (!button) return;
              const attr=button.hasAttribute('data-radar-mode')?'data-radar-mode':'data-radar-generation';
              const value=button.getAttribute(attr);
              if (attr==='data-radar-mode') mode=value; else generation=value;
              render(); root.querySelector(`[${attr}="${value}"]`)?.focus({preventScroll:true});
            });
            const inspect=e=>{
              const marker=e.target.closest('[data-radar-point], [data-radar-card]');
              if (!marker) return;
              const p=visiblePoints[Number(marker.dataset.radarPoint ?? marker.dataset.radarCard)];
              if (p) root.querySelector('.radar-detail').textContent=pointText(p);
            };
            ['pointerover','focusin','click'].forEach(event=>root.addEventListener(event,inspect));
          }
          render();
          if (Date.now()-checkedAt>5000) poll(); else schedule();
        }
      };
    })();
