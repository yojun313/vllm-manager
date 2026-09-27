/* vLLM Control 대시보드.
 * 데이터는 전부 WebSocket(/ws)으로 받는다: gpu(1초), state(3초·변경 시), job/logs(구독한 것만 실시간).
 * 버튼 동작(켜기/끄기/다운로드)만 fetch 로 /api 를 부른다.
 */
(function () {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const gib = (mib) => (mib / 1024).toFixed(1);
  const PALETTE = ['#8b7bff', '#3fd0e8', '#3ddc97', '#f5b84a', '#ff7eb6', '#6aa8ff', '#ffa46b', '#b4e05a', '#e879f9', '#2dd4bf', '#fca5a5', '#a5b4fc'];
  const colors = {};
  let colorIdx = 0;
  const colorOf = (k) => colors[k] || (colors[k] = PALETTE[colorIdx++ % PALETTE.length]);
  const STAGE_KEYS = ['boot', 'engine', 'download', 'weights', 'compile', 'kvcache', 'graphs', 'server'];

  let S = null;          // 마지막 state
  let G = [];            // 마지막 gpu
  const choice = {};     // 모델별 GPU 선택
  let armed = null;      // '끄기' 두 번 눌러 확인
  const jobStatus = {};  // 작업 완료 토스트용

  /* ------------------------------------------------------------ 공통 */
  function toast(msg, kind) {
    const t = document.createElement('div');
    t.className = 'toast ' + (kind || '');
    t.textContent = msg;
    $('#toasts').append(t);
    setTimeout(() => t.remove(), 4500);
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      ...opts, credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      body: opts.body && typeof opts.body !== 'string' ? JSON.stringify(opts.body) : opts.body,
    });
    if (res.status === 401) { location.href = '/login'; throw new Error('로그인이 필요합니다'); }
    if (!res.ok) {
      let d = res.statusText;
      try { d = (await res.json()).detail || d; } catch (e) { /* noop */ }
      throw new Error(d);
    }
    const ct = res.headers.get('content-type') || '';
    return ct.includes('json') ? res.json() : res.text();
  }

  async function copy(text, msg) {
    try { await navigator.clipboard.writeText(text); }
    catch (e) {
      const t = document.createElement('textarea');
      t.value = text; document.body.append(t); t.select(); document.execCommand('copy'); t.remove();
    }
    toast(msg, 'ok');
  }

  function fmtBytes(b) {
    if (b == null) return '-';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return (i >= 3 ? b.toFixed(1) : Math.round(b)) + ' ' + u[i];
  }
  function fmtEta(sec) {
    if (sec == null) return '';
    if (sec < 60) return `${sec}초 남음`;
    if (sec < 3600) return `${Math.round(sec / 60)}분 남음`;
    return `${Math.floor(sec / 3600)}시간 ${Math.round((sec % 3600) / 60)}분 남음`;
  }

  function fmtElapsed(sec) {
    sec = Math.max(0, Math.floor(sec));
    const m = Math.floor(sec / 60), s = sec % 60;
    return m >= 60 ? `${Math.floor(m / 60)}시간 ${m % 60}분` : `${m}:${String(s).padStart(2, '0')}`;
  }

  /* ------------------------------------------------------------ WebSocket */
  let ws = null, wsBackoff = 500, sub = { sub: null };

  function connect() {
    ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
    ws.onopen = () => {
      wsBackoff = 500;
      setLive('ok', '실시간');
      ws.send(JSON.stringify({ ...sub, refresh: true }));
    };
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === 'gpu') { G = m.gpus; renderGpus(); if (S) renderLibrary(); }
      else if (m.type === 'state') { S = m; renderState(); }
      else if (m.type === 'job') onJobLines(m);
      else if (m.type === 'logs') onContainerLogs(m);
    };
    ws.onclose = (ev) => {
      if (ev.code === 1008) { location.href = '/login'; return; }
      setLive('bad', '재연결 중');
      setTimeout(connect, wsBackoff);
      wsBackoff = Math.min(wsBackoff * 2, 8000);
    };
  }
  function subscribe(msg) {
    sub = msg;
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg));
  }
  function setLive(kind, text) { $('#liveDot').className = 'dot ' + kind; $('#liveTxt').textContent = text; }

  /* ------------------------------------------------------------ GPU (값만 갱신해서 막대가 부드럽게 움직이게) */
  function gpuCard(idx) {
    let card = document.getElementById('gpu-' + idx);
    if (card) return card;
    card = document.createElement('div');
    card.className = 'card';
    card.id = 'gpu-' + idx;
    card.innerHTML = `
      <div class="gpu-top"><span class="gpu-idx">GPU ${esc(idx)}</span><span class="gpu-name"></span>
        <div class="gpu-stats"><span><b class="temp">-</b>°C</span><span><b class="pw">-</b>W</span></div></div>
      <div class="gpu-mem"><div class="used">-<small>/ - GiB</small></div>
        <div class="free">새 모델용 여유<b>-</b></div></div>
      <div class="bar"></div>
      <div class="legend"></div>
      <div class="util"><span>사용률</span><div class="track"><i></i></div><span class="v">-</span></div>`;
    return card;
  }

  function renderGpus() {
    const wrap = $('#gpus');
    if (wrap.querySelector('.skeleton')) wrap.innerHTML = '';
    const names = Object.fromEntries((S?.containers || []).map((c) => [c.name, c.model]));
    G.forEach((g) => {
      const card = gpuCard(g.idx);
      if (!card.parentNode) wrap.append(card);
      $('.gpu-name', card).textContent = g.name.replace('NVIDIA ', '');
      $('.temp', card).textContent = Math.round(g.temp);
      $('.pw', card).textContent = Math.round(g.power);
      $('.used', card).innerHTML = `${gib(g.used)}<small>/ ${gib(g.total)} GiB</small>`;
      $('.free b', card).textContent = gib(Math.max(0, g.free_new)) + ' GiB';

      // 막대: 모델별 조각(이름으로 키) + 다른 프로세스
      const bar = $('.bar', card);
      const segs = g.ours.map((o) => ({ key: o.name, label: names[o.name] || o.model, mib: o.mib, color: colorOf(names[o.name] || o.model) }));
      if (g.other > 0) segs.push({ key: '__other', label: '다른 프로세스', mib: g.other, other: true });
      const keep = new Set(segs.map((s) => s.key));
      [...bar.children].forEach((el) => { if (!keep.has(el.dataset.k)) el.remove(); });
      segs.forEach((s) => {
        let el = bar.querySelector(`[data-k="${CSS.escape(s.key)}"]`);
        if (!el) {
          el = document.createElement('i');
          el.dataset.k = s.key;
          if (s.other) el.className = 'other'; else el.style.background = s.color;
          if (s.other) bar.append(el); else bar.insertBefore(el, bar.querySelector('.other'));
        }
        el.style.width = (s.mib / g.total * 100) + '%';
        el.title = `${s.label} ${gib(s.mib)} GiB`;
      });
      $('.legend', card).innerHTML = segs.length
        ? segs.map((s) => `<span><b style="background:${s.other ? '#3a3f4d' : s.color}"></b>${esc(s.label)} <span class="mono">${gib(s.mib)}</span></span>`).join('')
        : '<span>비어 있음</span>';
      $('.util .track i', card).style.width = g.util + '%';
      $('.util .v', card).textContent = Math.round(g.util) + '%';
    });
  }

  /* ------------------------------------------------------------ 진행률 블록 */
  function progressHtml(p, created, compact) {
    const cur = STAGE_KEYS.indexOf(p.key);
    const steps = STAGE_KEYS.map((k, i) => `<span class="${i < cur ? 'done' : i === cur ? 'cur' : ''}"></span>`).join('');
    return `<div class="prog">
      <div class="prog-top"><span class="stage">${esc(p.stage)}</span><span class="pct">${Math.floor(p.pct)}%</span></div>
      <div class="prog-track"><i style="width:${p.pct}%"></i></div>
      ${compact ? '' : `<div class="prog-steps">${steps}</div>`}
      <div class="prog-meta"><span>${esc(p.detail || '')}</span><span>경과 <span data-since="${created || ''}">${created ? fmtElapsed(Date.now() / 1000 - created) : '-'}</span></span></div>
      ${p.error ? `<div class="prog-err">${esc(p.error)}</div>` : ''}
    </div>`;
  }
  // 다운로드 진행률 (바이트 기준, 서버 계산 → 모든 기기에서 같음)
  function dlProgressHtml(j) {
    const p = j.progress || {};
    const running = j.status === 'running';
    const pct = p.pct ?? (running ? null : 100);
    const label = running ? (p.total ? '다운로드 중' : '크기 확인 중') : j.status === 'done' ? '완료' : '실패';
    const right = pct == null ? '' : `${Math.floor(pct)}%`;
    const left = p.total ? `${fmtBytes(p.done)} / ${fmtBytes(p.total)}` : fmtBytes(p.done);
    const speed = running && p.speed ? `${fmtBytes(p.speed)}/s · ${fmtEta(p.eta)}` : '';
    return `<div class="prog">
      <div class="prog-top"><span class="stage">${label}</span><span class="pct">${right}</span></div>
      <div class="prog-track"><i style="width:${pct == null ? 3 : pct}%"></i></div>
      <div class="prog-meta"><span>${left}</span><span>${speed || (running ? `경과 <span data-since="${j.started}">${fmtElapsed(Date.now() / 1000 - j.started)}</span>` : '')}</span></div>
    </div>`;
  }

  let lastDlHtml = '';
  function renderDownloads() {
    const now = Date.now() / 1000;
    const js = S.jobs.filter((j) => j.kind === 'pull' && (j.status === 'running' || now - (j.ended || 0) < 600)).slice(0, 6);
    const html = js.map((j) => `<div class="dl ${j.status}" data-job="${j.id}">
        <div class="dl-top"><span class="dot ${j.status === 'running' ? 'warn' : j.status === 'done' ? 'ok' : 'bad'}"></span>
          <span class="name">${esc(j.target)}</span><span class="pill ${j.status === 'running' ? 'warn' : j.status === 'done' ? 'ok' : 'bad'}">${j.status === 'running' ? '진행 중' : j.status === 'done' ? '완료' : '실패'}</span></div>
        ${dlProgressHtml(j)}</div>`).join('');
    if (html !== lastDlHtml) { $('#downloads').innerHTML = html; lastDlHtml = html; }
  }

  setInterval(() => {
    document.querySelectorAll('[data-since]').forEach((el) => {
      const t = +el.dataset.since;
      if (t) el.textContent = fmtElapsed(Date.now() / 1000 - t);
    });
  }, 1000);

  /* ------------------------------------------------------------ state 렌더 */
  function renderState() {
    $('#image').textContent = S.image;
    $('#banner').innerHTML = S.docker_ok ? '' : `<div class="banner"><b>docker 에 접근할 수 없습니다.</b>
      이 관리 서버를 실행한 사용자에게 docker 권한이 없어요.<br>
      <code>sudo usermod -aG docker $USER</code> 후 다시 로그인하고 서버를 재시작하세요.
      <div class="mono" style="opacity:.7;margin-top:6px">${esc(S.docker_error)}</div></div>`;
    $('#connSec').hidden = !S.api_key;
    renderRunning();
    renderLibrary();
    renderDownloads();
    renderJobsFab();
    if (delModel) refreshDeleteModal();
    if (sheet.mode === 'list') renderJobList();
    if (sheet.mode === 'job') renderSheetProgress();
  }

  function statusOf(c) {
    if (c.state !== 'running') return ['bad', '중지됨'];
    if (c.health) return ['ok', '실행 중'];
    if (c.progress?.error) return ['bad', '오류'];
    return ['warn', '기동 중'];
  }

  let lastRunHtml = '';
  function renderRunning() {
    const cs = S.containers;
    $('#runCount').textContent = cs.length ? cs.length + '개' : '';
    let html;
    if (!cs.length) html = '<div class="empty">실행 중인 모델이 없습니다. 아래 목록에서 켜보세요.</div>';
    else html = cs.map((c) => {
      const [k, t] = statusOf(c);
      const url = `http://${location.hostname}:${c.port}/v1`;
      const starting = c.state === 'running' && !c.health;
      return `<div class="card">
        <div class="rc-head"><span class="swatch" style="background:${colorOf(c.model)}"></span>
          <div class="rc-title"><h3>${esc(c.model)}</h3><div class="served">${esc(c.served)}</div></div>
          <span class="pill ${k}"><span class="dot ${k}"></span>${t}</span></div>
        ${starting ? progressHtml(c.progress, c.created) : ''}
        <div class="chips"><span class="chip">GPU <b>${esc(c.gpus)}</b></span><span class="chip">:<b>${esc(c.port)}</b></span>
          ${c.mem ? `<span class="chip">예약 <b>${gib(c.mem)}</b> GiB</span>` : ''}<span class="chip">${esc(c.status)}</span></div>
        <div class="actions">
          <button class="btn sm" data-copy="${esc(url)}" title="${esc(url)}">주소 복사</button>
          <button class="btn sm" data-logs="${esc(c.name)}">${starting ? '실시간 로그' : '로그'}</button>
          <button class="btn sm" data-up="${esc(c.model)}" data-gpus="${esc(c.gpus)}">재시작</button>
          <span class="grow"></span>
          <button class="btn sm danger ${armed === c.name ? 'armed' : ''}" data-stop="${esc(c.name)}">${armed === c.name ? '정말 끌까요?' : '끄기'}</button>
        </div></div>`;
    }).join('');
    if (html !== lastRunHtml) { $('#running').innerHTML = html; lastRunHtml = html; }
  }

  function combos(n) {
    const ids = G.map((g) => g.idx), out = [];
    const rec = (st, a) => { if (a.length === n) { out.push(a); return; } for (let i = st; i < ids.length; i++) rec(i + 1, [...a, ids[i]]); };
    rec(0, []);
    return out;
  }
  // 같은 모델+GPU 가 이미 떠 있으면 교체되므로 그 몫은 여유에 다시 더한다 (./vllm up 과 같은 규칙)
  function freeFor(ids, m) {
    const key = ids.join(',');
    const existing = S.containers.find((c) => c.model === m.alias && c.gpus === key);
    return Math.min(...ids.map((i) => {
      const g = G.find((x) => x.idx === i);
      if (!g) return 0;
      const mine = existing ? (g.ours.find((o) => o.name === existing.name)?.mib || 0) : 0;
      return g.free_new + mine;
    }));
  }

  let lastLibHtml = '';
  function renderLibrary() {
    if (!S || !G.length) return;
    $('#libCount').textContent = S.models.length + '개';
    const html = S.models.map((m) => {
      const opts = combos(m.gpus);
      const sel = choice[m.alias] ?? 'auto';
      const fits = (o) => freeFor(o, m) >= m.need_mib;
      const ranked = opts.map((o) => [o, freeFor(o, m)]).sort((a, b) => b[1] - a[1]);
      let ok, msg;
      if (!opts.length) {
        ok = false;
        msg = `GPU ${m.gpus}장이 필요하지만 사용 가능한 GPU 는 ${G.length}장입니다 (vllm.env 의 GPU_COUNT)`;
      } else if (sel === 'auto') {
        ok = opts.some(fits);
        msg = ok ? `GPU ${ranked[0][0].join('+')} 에 들어갑니다 · 여유 ${gib(ranked[0][1])} GiB`
          : `공간 부족 · 가장 큰 여유 ${gib(Math.max(0, ranked[0]?.[1] || 0))} GiB`;
      } else {
        const f = freeFor(sel.split(','), m);
        ok = f >= m.need_mib;
        msg = ok ? `여유 ${gib(f)} GiB 중 ${gib(m.need_mib)} GiB 사용` : `공간 부족 · 여유 ${gib(Math.max(0, f))} GiB`;
      }
      const running = S.containers.filter((c) => c.model === m.alias);
      const target = sel === 'auto' ? ranked[0]?.[0].join(',') : sel;
      const replacing = running.some((c) => c.gpus === target);
      const ctx = m.ctx ? (m.ctx >= 1024 ? Math.round(m.ctx / 1024) + 'k' : m.ctx) : '';
      const seg = [`<button data-pick="${esc(m.alias)}" data-v="auto" class="${sel === 'auto' ? 'on' : ''} ${opts.some(fits) ? '' : 'nofit'}">자동</button>`]
        .concat(opts.map((o) => { const v = o.join(','); return `<button data-pick="${esc(m.alias)}" data-v="${v}" class="${sel === v ? 'on' : ''} ${fits(o) ? '' : 'nofit'}">GPU ${o.join('+')}</button>`; }))
        .join('');
      return `<div class="card">
        <div class="rc-head"><span class="swatch" style="background:${colorOf(m.alias)}"></span>
          <div class="rc-title"><h3>${esc(m.alias)}${m.embed ? '<span class="tag">embed</span>' : ''}</h3><div class="served">${esc(m.served)}</div></div>
          ${running.length ? `<span class="pill ok"><span class="dot ok"></span>${esc(running.map((c) => 'GPU ' + c.gpus).join(', '))}</span>` : ''}
          <button class="icon-btn" data-del="${esc(m.alias)}" title="모델 삭제" aria-label="${esc(m.alias)} 삭제">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg></button></div>
        <div class="need"><strong>${gib(m.need_mib)}</strong><span>GiB × ${m.gpus} GPU${ctx ? ` · 컨텍스트 ${ctx}` : ''}</span></div>
        <div class="desc">${esc(m.desc)}</div>
        <div class="seg">${seg}</div>
        <div class="fit ${ok ? 'ok' : 'bad'}">${esc(msg)}</div>
        <button class="btn primary" data-up="${esc(m.alias)}" data-gpus="${sel === 'auto' ? '' : esc(sel)}" ${ok && S.docker_ok ? '' : 'disabled'}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l13-7.5z"/></svg>${replacing ? '재시작' : '켜기'}</button>
      </div>`;
    }).join('');
    if (html !== lastLibHtml) { $('#library').innerHTML = html; lastLibHtml = html; }
  }

  function renderJobsFab() {
    const running = S.jobs.filter((j) => j.status === 'running').length;
    $('#fabN').textContent = running ? running + ' 진행 중' : S.jobs.length;
    $('#fabDot').className = 'dot ' + (running ? 'warn' : S.jobs[0]?.status === 'failed' ? 'bad' : S.jobs.length ? 'ok' : '');
    S.jobs.forEach((j) => {
      if (jobStatus[j.id] === 'running' && j.status !== 'running') {
        toast(`${j.title} — ${j.status === 'done' ? '완료' : '실패'}`, j.status === 'done' ? 'ok' : 'bad');
      }
      jobStatus[j.id] = j.status;
    });
  }

  /* ------------------------------------------------------------ 시트: 작업 목록 / 작업 로그 / 컨테이너 로그 */
  const sheet = { mode: null, job: null, name: null, lines: 0, follow: true };
  const body = $('#sheetBody');

  function openSheet() { $('#sheet').classList.add('open'); $('#scrim').classList.add('open'); $('#sheet').setAttribute('aria-hidden', 'false'); }
  function closeSheet() {
    $('#sheet').classList.remove('open'); $('#scrim').classList.remove('open'); $('#sheet').setAttribute('aria-hidden', 'true');
    sheet.mode = null;
    subscribe({ sub: null });
  }

  function renderJobList() {
    sheet.mode = 'list';
    subscribe({ sub: null });
    $('#sheetTitle').textContent = '작업';
    $('#sheetBack').hidden = true; $('#followBtn').hidden = true; $('#sheetProgress').hidden = true;
    const js = S?.jobs || [];
    body.innerHTML = js.length ? js.map((j) => {
      const k = j.status === 'running' ? 'warn' : j.status === 'done' ? 'ok' : 'bad';
      const t = j.status === 'running' ? '진행 중' : j.status === 'done' ? '완료' : '실패';
      return `<div class="job" data-job="${j.id}"><div class="t"><span class="dot ${k}"></span><span class="title">${esc(j.title)}</span>
        <span class="pill ${k}">${t}</span></div>${j.kind === 'pull' ? `<div style="margin-top:10px">${dlProgressHtml(j)}</div>` : `<div class="l">${esc(j.last)}</div>`}</div>`;
    }).join('') : '<div class="empty">아직 작업이 없습니다.</div>';
  }

  function openTerm(title, back) {
    $('#sheetTitle').textContent = title;
    $('#sheetBack').hidden = !back;
    $('#followBtn').hidden = true;
    body.innerHTML = '<div class="term" id="term"></div>';
    sheet.lines = 0;
    sheet.follow = true;
    openSheet();
  }

  function lineClass(l) {
    if (/❌|Traceback|Error|ERROR|out of memory|failed/.test(l)) return 'e';
    if (/✅/.test(l)) return 'o';
    if (/^▶/.test(l)) return 'i';
    if (/⚠️|WARNING/.test(l)) return 'w';
    if (/\d+%\|/.test(l)) return 'p';
    return '';
  }
  function makeLine(text) {
    const d = document.createElement('div');
    d.textContent = text || ' ';
    const c = lineClass(text);
    if (c) d.className = c;
    return d;
  }
  // from: 이 묶음의 첫 줄 번호. 이미 받은 줄과 겹치면(진행률 덮어쓰기) 그 줄부터 바꿔 끼운다.
  function applyLines(from, lines) {
    const term = $('#term');
    if (!term) return;
    const base = sheet.base ?? from;
    if (sheet.base == null) sheet.base = from;
    let idx = from - base;
    while (term.childElementCount > idx && idx >= 0) term.lastElementChild.remove();
    const frag = document.createDocumentFragment();
    lines.forEach((l) => frag.append(makeLine(l)));
    term.append(frag);
    while (term.childElementCount > 5000) { term.firstElementChild.remove(); sheet.base++; }
    if (sheet.follow) body.scrollTop = body.scrollHeight;
  }

  function showJob(id) {
    sheet.mode = 'job'; sheet.job = id; sheet.base = null;
    openTerm('작업 로그', true);
    renderSheetProgress();
    subscribe({ sub: 'job', id });
  }
  function onJobLines(m) {
    if (sheet.mode !== 'job' || sheet.job !== m.id) return;
    $('#sheetTitle').textContent = m.title;
    applyLines(m.from, m.lines);
    renderSheetProgress();
  }
  // 켜기 작업이면 시트 위에 그 모델의 기동 진행률을 띄운다
  function renderSheetProgress() {
    const el = $('#sheetProgress');
    const job = S?.jobs.find((j) => j.id === sheet.job);
    if (job && job.kind === 'pull') { el.hidden = false; el.innerHTML = dlProgressHtml(job); return; }
    if (!job || job.kind !== 'up') { el.hidden = true; return; }
    const c = S.containers.filter((x) => x.model === job.target).sort((a, b) => b.created - a.created)[0];
    if (job.status === 'running' && (!c || c.created < job.started - 5)) {
      el.hidden = false;
      el.innerHTML = progressHtml({ key: 'boot', stage: '용량 확인 · 이미지 준비', pct: 1, detail: '', error: '' }, job.started, true);
    } else if (c && c.state === 'running') {
      el.hidden = false;
      el.innerHTML = progressHtml(c.progress, c.created, false);
    } else el.hidden = true;
  }

  function showLogs(name) {
    sheet.mode = 'logs'; sheet.name = name; sheet.base = null;
    openTerm(name + ' · 실시간 로그', false);
    $('#sheetProgress').hidden = true;
    subscribe({ sub: 'logs', name });
  }
  function onContainerLogs(m) {
    if (sheet.mode !== 'logs' || sheet.name !== m.name) return;
    const term = $('#term');
    if (m.reset) { term.innerHTML = ''; sheet.base = 0; return; }
    // partial: 줄바꿈 전의 진행 중인 줄(진행률 막대). 항상 마지막 한 줄로만 유지한다.
    term.querySelector('.partial')?.remove();
    applyLines(sheet.base + term.childElementCount, m.lines);
    if (m.partial) {
      const d = makeLine(m.partial);
      d.classList.add('partial');
      term.append(d);
      if (sheet.follow) body.scrollTop = body.scrollHeight;
    }
  }

  body.addEventListener('scroll', () => {
    if (sheet.mode !== 'job' && sheet.mode !== 'logs') return;
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 60;
    sheet.follow = atBottom;
    $('#followBtn').hidden = atBottom;
  });
  $('#followBtn').onclick = () => { sheet.follow = true; body.scrollTop = body.scrollHeight; $('#followBtn').hidden = true; };

  /* ------------------------------------------------------------ 삭제 모달 */
  let delModel = null;
  function openDeleteModal(alias) {
    delModel = alias;
    $('#delConfirm').value = '';
    $('#delFiles').checked = false;
    refreshDeleteModal();
    $('#delModal').hidden = false;
    setTimeout(() => $('#delConfirm').focus(), 50);
  }
  function closeDeleteModal() { $('#delModal').hidden = true; delModel = null; }
  function refreshDeleteModal() {
    const m = S.models.find((x) => x.alias === delModel);
    if (!m) { closeDeleteModal(); return; }
    const running = S.containers.filter((c) => c.model === m.alias);
    $('#delSwatch').style.background = colorOf(m.alias);
    $('#delAlias').textContent = m.alias;
    $('#delAlias2').textContent = m.alias;
    $('#delServed').textContent = m.served;
    $('#delRunning').hidden = !running.length;
    $('#delRunning').textContent = running.length ? `실행 중입니다 (${running.map((c) => 'GPU ' + c.gpus).join(', ')}). 먼저 끄세요.` : '';
    const canFiles = m.files_bytes > 0 && !m.files_shared.length;
    $('#delFiles').disabled = !canFiles;
    $('#delFilesRow').classList.toggle('disabled', !canFiles);
    if (!canFiles) $('#delFiles').checked = false;
    $('#delSize').textContent = m.files_bytes ? `· ${fmtBytes(m.files_bytes)} 확보` : '';
    $('#delPath').textContent = m.files_dir || '';
    $('#delFilesNote').textContent = m.files_shared.length ? `다른 설정(${m.files_shared.join(', ')})이 같은 가중치를 써서 파일은 지울 수 없습니다.`
      : !m.files_bytes ? '디스크에 받아둔 가중치가 없습니다. 설정만 지웁니다.'
      : '체크하지 않으면 설정만 지우고 가중치는 남깁니다 (나중에 ./vllm pull 로 설정만 다시 만들 수 있음).';
    $('#delOk').disabled = !!running.length || $('#delConfirm').value.trim() !== m.alias;
    $('#delOk').textContent = $('#delFiles').checked ? `가중치까지 삭제` : '설정 삭제';
  }
  $('#delConfirm').addEventListener('input', refreshDeleteModal);
  $('#delFiles').addEventListener('change', refreshDeleteModal);
  $('#delConfirm').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !$('#delOk').disabled) $('#delOk').click(); });
  $('#delCancel').onclick = closeDeleteModal;
  $('#delModal').addEventListener('click', (e) => { if (e.target.id === 'delModal') closeDeleteModal(); });
  $('#delOk').onclick = async () => {
    const alias = delModel, files = $('#delFiles').checked;
    $('#delOk').disabled = true;
    try {
      const j = await api(`/api/models/${encodeURIComponent(alias)}?files=${files}`, { method: 'DELETE' });
      closeDeleteModal();
      jobStatus[j.id] = 'running';
      showJob(j.id);
    } catch (e) { toast(e.message, 'bad'); refreshDeleteModal(); }
  };

  /* ------------------------------------------------------------ 확인 창 (Promise<boolean>) */
  function confirmDialog({ title, html, ok }) {
    return new Promise((resolve) => {
      $('#confirmTitle').textContent = title;
      $('#confirmBody').innerHTML = html;
      $('#confirmOk').textContent = ok;
      $('#confirmModal').hidden = false;
      const done = (v) => {
        $('#confirmModal').hidden = true;
        $('#confirmOk').onclick = $('#confirmCancel').onclick = $('#confirmModal').onclick = null;
        document.removeEventListener('keydown', onKey, true);
        resolve(v);
      };
      const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); done(false); } };
      document.addEventListener('keydown', onKey, true);
      $('#confirmOk').onclick = () => done(true);
      $('#confirmCancel').onclick = () => done(false);
      $('#confirmModal').onclick = (e) => { if (e.target.id === 'confirmModal') done(false); };
      setTimeout(() => $('#confirmCancel').focus(), 30);
    });
  }

  // 받기 전에 이 서버 GPU 로 띄울 수 있는지 확인 → 못 띄우면(또는 계산 불가면) 물어본다
  async function checkBeforePull(repo) {
    const r = await api(`/api/pull/check?repo=${encodeURIComponent(repo)}`);
    if (r.fit === 'ok') { toast(r.message, 'ok'); return { go: true, force: false }; }
    const gpus = r.gpus || G.length;
    const html = r.fit === 'no'
      ? `<div class="fit-box no"><b>GPU ${gpus}장(${esc((G[0]?.name || 'GPU').replace('NVIDIA ', ''))})을 모두 써도 띄울 수 없는 모델입니다.</b><br>
           가장 가볍게 띄워도(컨텍스트 4k, 동시 1) GPU 한 장에 들어가지 않아요.</div>
         <dl class="fit-grid">
           <dt>모델</dt><dd>${esc(r.repo)}</dd>
           <dt>GPU ${gpus}장일 때 필요 (GPU당)</dt><dd class="bad">${gib(r.need_all_mib)} GiB</dd>
           <dt>GPU 한 장에 쓸 수 있는 양</dt><dd>${gib(r.cap_mib)} GiB</dd>
         </dl>
         <p class="dim small">${esc(r.message)}</p>
         <p class="small">받아도 이 서버에서는 켤 수 없고 디스크만 차지합니다. 그래도 다운로드할까요?</p>`
      : `<div class="fit-box unknown"><b>필요한 메모리를 계산할 수 없습니다.</b><br>
           HF 에서 config.json 이나 가중치(safetensors) 크기를 읽지 못했어요. GGUF 처럼 vLLM 이 잘 쓰지 않는 형식일 수 있습니다.</div>
         <p class="dim small">${esc(r.message)}</p><p class="small">그래도 다운로드할까요?</p>`;
    const yes = await confirmDialog({ title: r.fit === 'no' ? '띄울 수 없는 모델' : '용량 확인 불가', html, ok: '그래도 다운로드' });
    return { go: yes, force: yes };
  }

  /* ------------------------------------------------------------ 동작 */
  async function up(model, gpus) {
    try {
      const j = await api(`/api/models/${encodeURIComponent(model)}/up`, { method: 'POST', body: { gpus: gpus || '' } });
      jobStatus[j.id] = 'running';
      showJob(j.id);
    } catch (e) { toast(e.message, 'bad'); }
  }

  document.addEventListener('click', async (e) => {
    const b = e.target.closest('button, [data-job]');
    if (!b) return;
    if (b.dataset.pick) { choice[b.dataset.pick] = b.dataset.v; renderLibrary(); return; }
    if (b.dataset.del) { openDeleteModal(b.dataset.del); return; }
    if (b.dataset.up) { b.disabled = true; await up(b.dataset.up, b.dataset.gpus); b.disabled = false; return; }
    if (b.dataset.stop) {
      const n = b.dataset.stop;
      if (armed !== n) {
        armed = n; renderRunning();
        setTimeout(() => { if (armed === n) { armed = null; renderRunning(); } }, 3500);
        return;
      }
      armed = null;
      try { await api(`/api/containers/${encodeURIComponent(n)}/down`, { method: 'POST' }); toast(n + ' 끄는 중'); }
      catch (err) { toast(err.message, 'bad'); }
      return;
    }
    if (b.dataset.logs) { showLogs(b.dataset.logs); return; }
    if (b.dataset.copy) { copy(b.dataset.copy, '주소를 복사했습니다'); return; }
    if (b.dataset.job) { showJob(+b.dataset.job); }
  });

  $('#fab').onclick = () => { renderJobList(); openSheet(); };
  $('#sheetClose').onclick = closeSheet;
  $('#scrim').onclick = closeSheet;
  $('#sheetBack').onclick = renderJobList;
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { if (delModel) closeDeleteModal(); else closeSheet(); } });
  $('#logoutBtn').onclick = async () => { await fetch('/api/logout', { method: 'POST' }); location.href = '/login'; };
  $('#copyKeyBtn').onclick = async () => {
    try { copy(await api('/api/key'), 'API 키를 복사했습니다'); } catch (e) { toast(e.message, 'bad'); }
  };
  $('#pullForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const repo = $('#repo').value.trim();
    if (!repo) return;
    const btn = $('#pullForm button[type=submit]');
    const label = btn.innerHTML;
    btn.disabled = true;
    btn.textContent = '용량 확인 중…';
    try {
      const { go, force } = await checkBeforePull(repo);
      if (!go) { toast('다운로드를 취소했습니다'); return; }
      const j = await api('/api/pull', { method: 'POST', body: { repo, alias: $('#alias').value.trim(), force } });
      $('#repo').value = ''; $('#alias').value = '';
      jobStatus[j.id] = 'running';
      showJob(j.id);
    } catch (err) { toast(err.message, 'bad'); }
    finally { btn.disabled = false; btn.innerHTML = label; }
  });

  connect();
})();
