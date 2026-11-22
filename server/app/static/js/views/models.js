/* 모델: 라이브러리(실행·설정 편집·삭제)와 다운로드. */
import { t } from '../i18n.js';
import { $, colorOf, esc, getPrefs, gib, hydrateIcons, setPrefs } from '../ui.js';
import { on, store } from '../store.js';
import { dlProgressHtml, engineName, jobKind, jobStatusText, planHtml } from '../parts.js';
import { addModel, deleteModel, editConfig, up } from '../actions.js';
import { showJob } from '../sheet.js';

let root, offs = [], lastLib = '', lastDl = '', query = '', filter = 'all', openMenu = null;
const choice = {};  // 모델별 GPU 선택

function combos(n) {
  const ids = store.G.map((g) => g.idx), out = [];
  const rec = (st, a) => { if (a.length === n) { out.push(a); return; } for (let i = st; i < ids.length && out.length < 24; i++) rec(i + 1, [...a, ids[i]]); };
  rec(0, []);
  return out;
}
// 같은 모델+GPU 가 이미 떠 있으면 교체되므로 그 몫은 여유에 다시 더한다 (./vllm up 과 같은 규칙)
function freeFor(ids, m) {
  const key = ids.join(',');
  const existing = store.S.containers.find((c) => c.model === m.alias && c.gpus === key);
  return Math.min(...ids.map((i) => {
    const g = store.G.find((x) => x.idx === i);
    if (!g) return 0;
    const mine = existing ? (g.ours.find((o) => o.name === existing.name)?.mib || 0) : 0;
    return g.free_new + mine;
  }));
}

function renderDownloads() {
  const now = Date.now() / 1000;
  const js = (store.S?.jobs || []).filter((j) => j.kind === 'pull' && (j.status === 'running' || now - (j.ended || 0) < 600)).slice(0, 6);
  const html = js.length ? `<div class="sh"><h2>${esc(t('dl.title'))}</h2></div>` + js.map((j) => `<div class="dl" data-job="${j.id}">
    <div class="dl-top"><span class="dot ${jobKind(j)}"></span><span class="name">${esc(j.target)}</span><span class="pill ${jobKind(j)}">${esc(jobStatusText(j))}</span></div>
    ${dlProgressHtml(j)}</div>`).join('') : '';
  if (html !== lastDl) { $('#downloads', root).innerHTML = html; $('#downloads', root).hidden = !html; lastDl = html; }
}

function renderLibrary() {
  const S = store.S, G = store.G;
  if (!S) return;
  const all = S.models;
  const list = all.filter((m) => {
    const running = S.containers.some((c) => c.model === m.alias);
    if (filter === 'running' && !running) return false;
    if (filter === 'stopped' && running) return false;
    const q = query.toLowerCase();
    return !q || m.alias.toLowerCase().includes(q) || m.served.toLowerCase().includes(q);
  });
  $('#libCount', root).textContent = list.length === all.length ? String(all.length) : `${list.length} / ${all.length}`;
  let html;
  if (!all.length) html = `<div class="empty">${esc(t('lib.none'))}<br><button class="btn primary" data-add><span data-icon="plus" data-size="15"></span>${esc(t('lib.add'))}</button></div>`;
  else if (!list.length) html = `<div class="empty">${esc(t('lib.noMatch'))}</div>`;
  else html = list.map((m) => {
    const opts = combos(m.gpus);
    const sel = choice[m.alias] ?? 'auto';
    const fits = (o) => freeFor(o, m) >= m.need_mib;
    const ranked = opts.map((o) => [o, freeFor(o, m)]).sort((a, b) => b[1] - a[1]);
    let ok, msg;
    if (!opts.length) { ok = false; msg = t('lib.needGpus', { n: m.gpus, have: G.length }); }
    else if (sel === 'auto') {
      ok = opts.some(fits);
      msg = ok ? t('lib.fitAuto', { gpus: ranked[0][0].join('+'), free: gib(ranked[0][1]) }) : t('lib.short', { free: gib(Math.max(0, ranked[0]?.[1] || 0)) });
    } else {
      const f = freeFor(sel.split(','), m);
      ok = f >= m.need_mib;
      msg = ok ? t('lib.fitPick', { free: gib(f), need: gib(m.need_mib) }) : t('lib.short', { free: gib(Math.max(0, f)) });
    }
    if (m.engine_configured === false) { ok = false; msg = t('lib.noOmni'); }
    const running = S.containers.filter((c) => c.model === m.alias);
    const target = sel === 'auto' ? ranked[0]?.[0].join(',') : sel;
    const replacing = running.some((c) => c.gpus === target);
    const ctx = m.ctx ? (m.ctx >= 1024 ? Math.round(m.ctx / 1024) + 'k' : m.ctx) : '';
    const seg = [`<button data-pick="${esc(m.alias)}" data-v="auto" class="${sel === 'auto' ? 'on' : ''} ${opts.some(fits) ? '' : 'nofit'}">${esc(t('lib.auto'))}</button>`]
      .concat(opts.map((o) => { const v = o.join(','); return `<button data-pick="${esc(m.alias)}" data-v="${v}" class="${sel === v ? 'on' : ''} ${fits(o) ? '' : 'nofit'}">GPU ${o.join('+')}</button>`; })).join('');
    return `<div class="card">
      <div class="rc-head"><span class="swatch" style="background:${colorOf(m.alias)}"></span>
        <div class="rc-title"><h3>${esc(m.alias)}${m.embed ? `<span class="tag">${esc(t('lib.embed'))}</span>` : ''}</h3><div class="served">${esc(m.served)}</div></div>
        ${running.length ? `<span class="pill ok"><span class="dot ok"></span>${esc(running.map((c) => 'GPU ' + c.gpus).join(', '))}</span>` : ''}</div>
      <div class="plan"><div class="need"><strong>${gib(m.need_mib)}</strong><span>GiB × ${m.gpus} GPU${ctx ? ` · ${esc(t('lib.ctx', { v: ctx }))}` : ''}</span></div>
        ${planHtml(m)}
        <div class="chips"><span class="chip">${engineName(m.engine)}</span>${m.deploy_config ? `<span class="chip">${esc(m.deploy_config)}</span>` : ''}</div></div>
      <div class="pick"><div class="seg">${seg}</div><div class="fit ${ok ? 'ok' : 'bad'}">${esc(msg)}</div></div>
      <div class="launch">
        <button class="btn primary" data-up="${esc(m.alias)}" data-gpus="${sel === 'auto' ? '' : esc(sel)}" ${ok && S.docker_ok ? '' : 'disabled'}><span data-icon="${replacing ? 'refresh' : 'play'}" data-size="14"></span>${esc(replacing ? t('run.restart') : t('lib.run'))}</button>
        <div class="menu-wrap"><button class="btn icon" data-menu="${esc(m.alias)}" aria-label="${esc(t('lib.more'))}" aria-expanded="${openMenu === m.alias}"><span data-icon="more"></span></button>
          ${openMenu === m.alias ? `<div class="menu"><button data-edit="${esc(m.alias)}"><span data-icon="edit" data-size="15"></span>${esc(t('lib.edit'))}</button>
            <button class="danger" data-del="${esc(m.alias)}"><span data-icon="trash" data-size="15"></span>${esc(t('lib.delete'))}</button></div>` : ''}</div>
      </div></div>`;
  }).join('');
  if (html !== lastLib) { const el = $('#library', root); el.innerHTML = html; hydrateIcons(el); lastLib = html; }
}

function syncToolbar() {
  root.querySelectorAll('[data-filter]').forEach((b) => b.classList.toggle('on', b.dataset.filter === filter));
  root.querySelectorAll('[data-view-mode]').forEach((b) => b.classList.toggle('on', b.dataset.viewMode === getPrefs().viewMode));
}

export function mount(el, params) {
  root = el; lastLib = ''; lastDl = ''; openMenu = null;
  el.innerHTML = `
    <div class="page-head"><div class="toolbar">
        <input class="input" id="libSearch" type="search" placeholder="${esc(t('lib.search'))}" value="${esc(query)}" autocomplete="off">
        <div class="seg"><button data-filter="all">${esc(t('lib.all'))}</button><button data-filter="running">${esc(t('lib.running'))}</button><button data-filter="stopped">${esc(t('lib.stopped'))}</button></div>
        <div class="seg"><button data-view-mode="cards" title="${esc(t('lib.cards'))}"><span data-icon="grid" data-size="15"></span></button><button data-view-mode="list" title="${esc(t('lib.list'))}"><span data-icon="list" data-size="15"></span></button></div>
      </div>
      <button class="btn primary" data-add><span data-icon="plus" data-size="15"></span>${esc(t('lib.add'))}</button></div>
    <div class="card section" id="downloads" hidden></div>
    <section class="section"><div class="sh"><h2>${esc(t('lib.title'))}</h2><span class="count" id="libCount"></span></div>
      <div class="grid lib" id="library"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div></section>`;
  hydrateIcons(el);
  syncToolbar();
  $('#libSearch', el).addEventListener('input', (e) => { query = e.target.value.trim(); renderLibrary(); });
  el.onclick = (e) => {
    const b = e.target.closest('button, [data-job]');
    if (openMenu && !e.target.closest('[data-menu]')) { openMenu = null; if (!b || !(b.dataset.edit || b.dataset.del)) renderLibrary(); }
    if (!b) return;
    if (b.dataset.filter) { filter = b.dataset.filter; syncToolbar(); renderLibrary(); }
    else if (b.dataset.viewMode) { setPrefs({ viewMode: b.dataset.viewMode }); syncToolbar(); }
    else if (b.dataset.add != null) addModel();
    else if (b.dataset.pick) { choice[b.dataset.pick] = b.dataset.v; renderLibrary(); }
    else if (b.dataset.menu) { openMenu = openMenu === b.dataset.menu ? null : b.dataset.menu; renderLibrary(); }
    else if (b.dataset.edit) { renderLibrary(); editConfig(b.dataset.edit); }
    else if (b.dataset.del) { renderLibrary(); deleteModel(b.dataset.del); }
    else if (b.dataset.up) up(b.dataset.up, b.dataset.gpus);
    else if (b.dataset.job) showJob(+b.dataset.job);
  };
  offs = [on('gpu', renderLibrary), on('state', () => { renderLibrary(); renderDownloads(); })];
  renderLibrary(); renderDownloads();
  if (params.get('add') != null) addModel(params.get('add') || '');
}
export function unmount() { offs.forEach((f) => f()); offs = []; }
