/* 작업: 실행·중지·다운로드·삭제 기록과 로그. */
import { t } from '../i18n.js';
import { $, esc, fmtClock, fmtDuration, hydrateIcons } from '../ui.js';
import { on, store } from '../store.js';
import { dlProgressHtml, jobPill, jobTitle } from '../parts.js';
import { showJob } from '../sheet.js';

let root, offs = [], kind = 'all', last = '';
const ICON = { up: 'play', down: 'stop', pull: 'download', rm: 'trash', setup: 'box' };

function render() {
  const all = store.S?.jobs || [];
  const js = all.filter((j) => kind === 'all' || j.kind === kind);
  const now = Date.now() / 1000;
  const html = js.length ? `<div class="card" style="padding:14px 6px 6px"><div class="table-wrap"><table class="table"><thead><tr><th></th><th>${esc(t('act.job'))}</th><th>${esc(t('act.status'))}</th><th>${esc(t('act.started'))}</th><th class="num">${esc(t('act.took'))}</th></tr></thead><tbody>${
    js.map((j) => `<tr class="click" data-job="${j.id}"><td style="width:1%" class="dim"><span data-icon="${ICON[j.kind] || 'activity'}" data-size="15"></span></td>
      <td><div>${esc(jobTitle(j))}</div>${j.kind === 'pull' && j.status === 'running' ? `<div style="max-width:420px;margin-top:6px">${dlProgressHtml(j)}</div>` : `<div class="faint small mono" style="max-width:60ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(j.last)}</div>`}</td>
      <td>${jobPill(j)}</td><td class="dim nowrap">${esc(fmtClock(j.started))}</td><td class="num dim nowrap">${esc(fmtDuration((j.ended || now) - j.started))}</td></tr>`).join('')
  }</tbody></table></div></div>` : `<div class="empty">${esc(t('jobs.none'))}</div>`;
  if (html !== last) { const el = $('#jobTable', root); el.innerHTML = html; hydrateIcons(el); last = html; }
}

export function mount(el) {
  root = el; last = '';
  el.innerHTML = `<div class="page-head"><p>${esc(t('act.sub'))}</p>
    <div class="seg" id="kindSeg">${['all', 'up', 'down', 'pull', 'rm'].map((k) => `<button data-kind="${k}" class="${k === kind ? 'on' : ''}">${esc(t('act.kind.' + k))}</button>`).join('')}</div></div>
    <div id="jobTable"></div>`;
  el.onclick = (e) => {
    const k = e.target.closest('[data-kind]');
    if (k) { kind = k.dataset.kind; el.querySelectorAll('[data-kind]').forEach((x) => x.classList.toggle('on', x === k)); render(); return; }
    const row = e.target.closest('[data-job]');
    if (row) showJob(+row.dataset.job);
  };
  offs = [on('state', render)];
  render();
}
export function unmount() { offs.forEach((f) => f()); offs = []; }
