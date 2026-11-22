/* 대시보드: 요약, GPU, 실행 중인 모델, 최근 작업. */
import { t } from '../i18n.js';
import { $, api, colorOf, copy, esc, fmtAgo, fmtBytes, fmtNum, gib, hydrateIcons } from '../ui.js';
import { on, seedUtilHistory, store } from '../store.js';
import { endpointOf, engineName, jobPill, jobTitle, progressHtml, statusOf } from '../parts.js';
import { connectInfo, stop, up } from '../actions.js';
import { showJob, showLogs } from '../sheet.js';
import { renderGpus } from './gpucards.js';

let root, last = {}, disk = null, offs = [];

function setHtml(sel, html) {
  if (last[sel] === html) return;
  last[sel] = html;
  const el = $(sel, root);
  el.innerHTML = html;
  hydrateIcons(el);
}

function renderStats() {
  const G = store.G, S = store.S;
  const used = G.reduce((a, g) => a + g.used, 0), total = G.reduce((a, g) => a + g.total, 0);
  const util = G.length ? G.reduce((a, g) => a + g.util, 0) / G.length : 0;
  const power = G.reduce((a, g) => a + g.power, 0);
  const cs = S?.containers || [];
  const ready = cs.filter((c) => c.health).length, starting = cs.filter((c) => c.state === 'running' && !c.health).length;
  const tps = cs.reduce((a, c) => a + (c.metrics?.gen_tps || 0), 0);
  const reqs = cs.reduce((a, c) => a + (c.metrics?.running || 0), 0);
  const waiting = cs.reduce((a, c) => a + (c.metrics?.waiting || 0), 0);
  const pct = total ? used / total * 100 : 0;
  const tile = (k, ic, v, s, meter) => `<div class="card stat"><div class="k"><span data-icon="${ic}" data-size="15"></span>${esc(k)}</div>
    <div class="v">${v}</div><div class="s">${s}</div>${meter ?? ''}</div>`;
  const dpct = disk ? disk.used / disk.total * 100 : 0;
  setHtml('#stats', [
    tile(t('stat.vram'), 'gpu', `${gib(used)}<small>/ ${gib(total)} GiB</small>`, esc(t('stat.gpus', { n: G.length })),
      `<div class="meter"><i class="${pct > 92 ? 'bad' : pct > 80 ? 'warn' : ''}" style="width:${pct}%"></i></div>`),
    tile(t('stat.util'), 'bolt', `${Math.round(util)}<small>%</small>`, esc(t('stat.power', { w: Math.round(power) }))),
    tile(t('stat.models'), 'models', `${ready}<small>${esc(t('stat.ready'))}</small>`, esc(starting ? t('stat.starting', { n: starting }) : t('stat.library', { n: S?.models.length ?? 0 }))),
    tile(t('stat.tps'), 'activity', `${fmtNum(tps)}<small>tok/s</small>`, esc(t('stat.reqs', { n: reqs, w: waiting }))),
    tile(t('stat.disk'), 'disk', disk ? `${fmtBytes(disk.free)}<small>${esc(t('stat.free'))}</small>` : '-', disk ? esc(t('stat.diskOf', { v: fmtBytes(disk.total) })) : '',
      disk ? `<div class="meter"><i class="${dpct > 92 ? 'bad' : dpct > 80 ? 'warn' : ''}" style="width:${dpct}%"></i></div>` : ''),
  ].join(''));
}

function kpis(m) {
  if (!m) return '';
  const cell = (k, v, u = '') => `<div><div class="k">${esc(k)}</div><div class="v">${v}${u ? `<small>${u}</small>` : ''}</div></div>`;
  return `<div class="kpis">${cell(t('kpi.tps'), fmtNum(m.gen_tps), 'tok/s')}${cell(t('kpi.reqs'), `${m.running}${m.waiting ? ` <small>+${m.waiting}</small>` : ''}`)}${cell(t('kpi.ttft'), m.ttft == null ? '-' : m.ttft < 1 ? Math.round(m.ttft * 1000) : m.ttft.toFixed(1), m.ttft == null ? '' : m.ttft < 1 ? 'ms' : 's')}${cell(t('kpi.kv'), m.kv_usage == null ? '-' : Math.round(m.kv_usage * 100), m.kv_usage == null ? '' : '%')}</div>`;
}

function renderRunning() {
  const S = store.S;
  if (!S) return;
  const cs = S.containers;
  $('#runCount', root).textContent = cs.length ? String(cs.length) : '';
  const html = !cs.length
    ? `<div class="empty">${esc(t('run.none'))}<br><a class="btn" href="#/models">${esc(t('run.goModels'))}</a></div>`
    : cs.map((c) => {
      const [k, label] = statusOf(c);
      const starting = c.state === 'running' && !c.health;
      const url = endpointOf(c);
      return `<div class="card">
        <div class="rc-head"><span class="swatch" style="background:${colorOf(c.model)}"></span>
          <div class="rc-title"><h3>${esc(c.model)}</h3><div class="served">${esc(c.served)}</div></div>
          <span class="pill ${k}"><span class="dot ${k}"></span>${esc(label)}</span></div>
        ${starting ? progressHtml(c.progress, c.created) : kpis(c.metrics)}
        <div class="chips"><span class="chip">${engineName(c.engine)}</span><span class="chip">GPU <b>${esc(c.gpus)}</b></span><span class="chip">:<b>${esc(c.port)}</b></span>
          ${c.mem ? `<span class="chip">${esc(t('run.reserved'))} <b>${gib(c.mem)}</b> GiB</span>` : ''}<span class="chip">${esc(c.status)}</span></div>
        <div class="actions">
          <button class="btn sm" data-copy="${esc(url)}" title="${esc(url)}"><span data-icon="link" data-size="14"></span>${esc(t('run.copyUrl'))}</button>
          <button class="btn sm" data-conn="${esc(c.name)}"><span data-icon="code" data-size="14"></span>${esc(t('run.connect'))}</button>
          ${c.health ? `<a class="btn sm" href="#/playground?m=${encodeURIComponent(c.name)}"><span data-icon="chat" data-size="14"></span>${esc(t('run.test'))}</a>` : ''}
          <button class="btn sm" data-logs="${esc(c.name)}"><span data-icon="logs" data-size="14"></span>${esc(t('run.logs'))}</button>
          <span class="grow"></span>
          <button class="btn sm" data-up="${esc(c.model)}" data-gpus="${esc(c.gpus)}" title="${esc(t('run.restart'))}"><span data-icon="refresh" data-size="14"></span></button>
          <button class="btn sm danger" data-stop="${esc(c.name)}"><span data-icon="stop" data-size="13"></span>${esc(t('common.stop'))}</button>
        </div></div>`;
    }).join('');
  setHtml('#running', html);
}

function renderJobs() {
  const js = (store.S?.jobs || []).slice(0, 5);
  setHtml('#recent', js.length ? `<div class="card" style="padding:6px 6px"><div class="table-wrap"><table class="table"><tbody>${js.map((j) => `<tr class="click" data-job="${j.id}">
    <td style="width:1%">${jobPill(j)}</td><td>${esc(jobTitle(j))}</td><td class="num faint nowrap">${esc(fmtAgo(j.started))}</td></tr>`).join('')}</tbody></table></div></div>`
    : `<div class="empty">${esc(t('jobs.none'))}</div>`);
}

function renderAll() { renderStats(); renderGpus($('#gpus', root)); renderRunning(); renderJobs(); }

export function mount(el) {
  root = el; last = {};
  el.innerHTML = `
    <div class="grid stats" id="stats"></div>
    <section class="section"><div class="sh"><h2>GPU</h2><span class="count" id="gpuRefresh"></span><a class="sh-action link" href="#/monitor">${esc(t('dash.history'))} →</a></div>
      <div class="grid gpus" id="gpus"><div class="skeleton"></div><div class="skeleton"></div></div></section>
    <section class="section"><div class="sh"><h2>${esc(t('run.title'))}</h2><span class="count" id="runCount"></span><a class="sh-action link" href="#/models">${esc(t('dash.allModels'))} →</a></div>
      <div class="grid run" id="running"><div class="skeleton"></div></div></section>
    <section class="section"><div class="sh"><h2>${esc(t('dash.recent'))}</h2><a class="sh-action link" href="#/activity">${esc(t('dash.allJobs'))} →</a></div>
      <div id="recent"></div></section>`;
  el.onclick = (e) => {
    const b = e.target.closest('[data-copy],[data-conn],[data-logs],[data-up],[data-stop],[data-job]');
    if (!b) return;
    if (b.dataset.copy) copy(b.dataset.copy, t('run.urlCopied'));
    else if (b.dataset.conn) connectInfo(b.dataset.conn);
    else if (b.dataset.logs) showLogs(b.dataset.logs);
    else if (b.dataset.up) up(b.dataset.up, b.dataset.gpus);
    else if (b.dataset.stop) stop(b.dataset.stop);
    else if (b.dataset.job) showJob(+b.dataset.job);
  };
  offs = [on('gpu', () => { renderStats(); renderGpus($('#gpus', root)); }), on('state', renderAll)];
  renderAll();
  api('/api/system').then((s) => { disk = s.disks[0] || null; renderStats(); }).catch(() => {});
  if (!Object.keys(store.utilHistory).length) api('/api/history?range=15m').then((h) => { seedUtilHistory(h); renderGpus($('#gpus', root)); }).catch(() => {});
}
export function unmount() { offs.forEach((f) => f()); offs = []; }
