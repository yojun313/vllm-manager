/* 모니터링: GPU 와 모델 처리량의 이력 차트, GPU 프로세스 목록. */
import { t } from '../i18n.js';
import { $, api, colorOf, esc, gib, gpuColor } from '../ui.js';
import { legend, lineChart } from '../charts.js';
import { on, store } from '../store.js';

let root, offs = [], timer = null, span = '1h', data = null, lastProcs = '';
const REFRESH = { '15m': 5000, '1h': 10000, '6h': 60000, '24h': 60000 };

function draw() {
  if (!data || !root.isConnected) return;
  const gpuSeries = (field, scale = (v) => v) => Object.keys(data.gpus).sort((a, b) => a - b).map((idx) => ({
    name: 'GPU ' + idx, color: gpuColor(idx), values: (data.gpus[idx][field] || []).map((v) => (v == null ? null : scale(v))) }));
  const names = Object.fromEntries((store.S?.containers || []).map((c) => [c.name, c.model]));
  const modelSeries = (field) => Object.keys(data.models).sort().map((name) => ({
    name: names[name] || name.replace(/^vllm-/, ''), color: colorOf(names[name] || name), values: data.models[name][field] || [] }));
  const charts = [
    ['util', gpuSeries('util'), { max: 100, fmt: (v) => Math.round(v) + '%' }],
    ['mem', gpuSeries('mem', (v) => v / 1024), { max: Math.max(...Object.values(data.gpus).map((g) => Math.max(...(g.total || [0]).filter((v) => v != null), 0)), 1024) / 1024, fmt: (v) => v.toFixed(0) + ' GiB' }],
    ['temp', gpuSeries('temp'), { fmt: (v) => Math.round(v) + '°C' }],
    ['power', gpuSeries('power'), { fmt: (v) => Math.round(v) + ' W' }],
    ['tps', modelSeries('tps'), { fmt: (v) => (v >= 100 ? Math.round(v) : v.toFixed(1)) }],
    ['reqs', modelSeries('running'), { fmt: (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1)) }],
  ];
  charts.forEach(([id, series, opt]) => {
    lineChart($(`#ch-${id}`, root), { t: data.t, series, empty: t('mon.noData'), ...opt });
    $(`#lg-${id}`, root).innerHTML = legend(series.filter((s) => s.values.some((v) => v != null)));
  });
}

async function load() {
  try { data = await api('/api/history?range=' + span); draw(); } catch (e) { /* 다음 주기에 다시 시도 */ }
}
function schedule() { clearInterval(timer); timer = setInterval(load, REFRESH[span]); }

function renderProcs() {
  const rows = [];
  const names = Object.fromEntries((store.S?.containers || []).map((c) => [c.name, c.model]));
  store.G.forEach((g) => {
    g.ours.forEach((o) => rows.push({ gpu: g.idx, name: names[o.name] || o.model, kind: t('mon.managed'), user: '', pid: '', mib: o.mib, color: colorOf(names[o.name] || o.model) }));
    (g.procs || []).forEach((p) => rows.push({ gpu: g.idx, name: p.label, kind: p.container ? t('gpu.container') : t('mon.process'), user: p.user, pid: p.pid, mib: p.mib, cmd: p.cmd }));
  });
  const html = rows.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>GPU</th><th>${esc(t('mon.name'))}</th><th>${esc(t('mon.kind'))}</th><th>${esc(t('mon.user'))}</th><th>PID</th><th class="num">${esc(t('mon.memory'))}</th></tr></thead><tbody>${
    rows.map((r) => `<tr><td class="mono">${esc(r.gpu)}</td><td title="${esc(r.cmd || '')}">${r.color ? `<span class="swatch" style="background:${r.color};margin-right:8px"></span>` : ''}${esc(r.name)}</td><td class="dim">${esc(r.kind)}</td><td class="mono dim">${esc(r.user || '-')}</td><td class="mono dim">${esc(r.pid || '-')}</td><td class="num">${gib(r.mib)} GiB</td></tr>`).join('')
  }</tbody></table></div>` : `<div class="empty">${esc(t('mon.noProcs'))}</div>`;
  if (html !== lastProcs) { $('#procTable', root).innerHTML = html; lastProcs = html; }
}

export function mount(el) {
  root = el; lastProcs = '';
  const card = (id, title, sub) => `<div class="card chart-card"><h3>${esc(title)}</h3><div class="chart-sub">${esc(sub)}</div><div class="chart" id="ch-${id}"></div><div class="chart-legend" id="lg-${id}"></div></div>`;
  el.innerHTML = `
    <div class="page-head"><p>${esc(t('mon.sub'))}</p>
      <div class="seg" id="rangeSeg">${['15m', '1h', '6h', '24h'].map((r) => `<button data-range="${r}" class="${r === span ? 'on' : ''}">${esc(t('mon.range.' + r))}</button>`).join('')}</div></div>
    <div class="grid charts">${card('util', t('mon.util'), t('mon.utilSub'))}${card('mem', t('mon.mem'), t('mon.memSub'))}${card('tps', t('mon.tps'), t('mon.tpsSub'))}${card('reqs', t('mon.reqs'), t('mon.reqsSub'))}${card('temp', t('mon.temp'), t('mon.tempSub'))}${card('power', t('mon.power'), t('mon.powerSub'))}</div>
    <section class="section"><div class="sh"><h2>${esc(t('mon.procs'))}</h2></div><div class="card" style="padding:14px 6px 6px" id="procTable"></div></section>`;
  $('#rangeSeg', el).onclick = (e) => {
    const b = e.target.closest('[data-range]');
    if (!b) return;
    span = b.dataset.range;
    el.querySelectorAll('[data-range]').forEach((x) => x.classList.toggle('on', x === b));
    load(); schedule();
  };
  const ro = new ResizeObserver(() => draw());
  ro.observe(el);
  offs = [on('gpu', renderProcs), on('state', renderProcs), () => ro.disconnect()];
  renderProcs(); load(); schedule();
}
export function unmount() { offs.forEach((f) => f()); offs = []; clearInterval(timer); }
