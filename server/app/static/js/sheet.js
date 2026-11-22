/* 오른쪽에서 열리는 로그 창: 작업 로그와 컨테이너 실시간 로그. */
import { t } from './i18n.js';
import { $, api, toast } from './ui.js';
import { on, store, subscribe } from './store.js';
import { dlProgressHtml, jobTitle, progressHtml } from './parts.js';

const sheet = { mode: null, job: null, name: null, base: null, follow: true };
const body = () => $('#sheetBody');

function open() {
  $('#sheet').classList.add('open'); $('#scrim').classList.add('open');
  $('#sheet').setAttribute('aria-hidden', 'false');
}
export function closeSheet() {
  $('#sheet').classList.remove('open'); $('#scrim').classList.remove('open');
  $('#sheet').setAttribute('aria-hidden', 'true');
  sheet.mode = null;
  subscribe({ sub: null });
}
export const sheetOpen = () => sheet.mode != null;

function openTerm(title) {
  $('#sheetTitle').textContent = title;
  $('#followBtn').hidden = true;
  $('#sheetAction').hidden = true;
  body().innerHTML = '<div class="term" id="term"></div>';
  sheet.follow = true;
  open();
}

function lineClass(l) {
  if (/❌|Traceback|Error|ERROR|out of memory|failed/.test(l)) return 'e';
  if (/✅/.test(l)) return 'o';
  if (/^▶/.test(l)) return 'i';
  if (/⚠️|WARNING/.test(l)) return 'w';
  if (/\d+%\s*(Completed\s*)?\|/.test(l)) return 'p';
  return '';
}
function makeLine(text) {
  const d = document.createElement('div');
  d.textContent = text || ' ';
  const c = lineClass(text);
  if (c) d.className = c;
  return d;
}
// from: 이 묶음의 첫 줄 번호. 이미 받은 줄과 겹치면(진행률 덮어쓰기) 그 줄부터 바꿔 끼운다.
function applyLines(from, lines) {
  const term = $('#term');
  if (!term) return;
  if (sheet.base == null) sheet.base = from;
  const idx = from - sheet.base;
  while (term.childElementCount > idx && idx >= 0) term.lastElementChild.remove();
  const frag = document.createDocumentFragment();
  lines.forEach((l) => frag.append(makeLine(l)));
  term.append(frag);
  while (term.childElementCount > 5000) { term.firstElementChild.remove(); sheet.base++; }
  if (sheet.follow) body().scrollTop = body().scrollHeight;
}

export function showJob(id) {
  sheet.mode = 'job'; sheet.job = id; sheet.base = null;
  const job = store.S?.jobs.find((j) => j.id === id);
  openTerm(job ? jobTitle(job) : t('sheet.jobLog'));
  renderProgress();
  subscribe({ sub: 'job', id });
}
export function showLogs(name) {
  sheet.mode = 'logs'; sheet.name = name; sheet.base = null;
  openTerm(t('sheet.liveLog', { name }));
  $('#sheetProgress').hidden = true;
  subscribe({ sub: 'logs', name });
}

// 켜기 작업이면 그 모델의 기동 진행률, 다운로드면 받은 양을 로그 위에 보여준다
function renderProgress() {
  const el = $('#sheetProgress'), action = $('#sheetAction');
  const S = store.S;
  const job = sheet.mode === 'job' ? S?.jobs.find((j) => j.id === sheet.job) : null;
  action.hidden = !(job && job.kind === 'pull' && job.status === 'running');
  if (!action.hidden) action.textContent = t('job.cancel');
  if (job && job.kind === 'pull') { el.hidden = false; el.innerHTML = dlProgressHtml(job); return; }
  if (!job || job.kind !== 'up') { el.hidden = true; return; }
  const c = S.containers.filter((x) => x.model === job.target).sort((a, b) => b.created - a.created)[0];
  if (job.status === 'running' && (!c || c.created < job.started - 5)) {
    el.hidden = false;
    el.innerHTML = progressHtml({ key: 'prepare', pct: 1, error: '' }, job.started, true);
  } else if (c && c.state === 'running' && job.status === 'running') {
    el.hidden = false;
    el.innerHTML = progressHtml(c.progress, c.created, false);
  } else el.hidden = true;
}

export function initSheet() {
  $('#sheetClose').onclick = closeSheet;
  $('#scrim').onclick = closeSheet;
  $('#followBtn').onclick = () => { sheet.follow = true; body().scrollTop = body().scrollHeight; $('#followBtn').hidden = true; };
  $('#sheetAction').onclick = async () => {
    try { await api(`/api/jobs/${sheet.job}/cancel`, { method: 'POST' }); toast(t('job.cancelSent')); }
    catch (e) { toast(e.message, 'bad'); }
  };
  body().addEventListener('scroll', () => {
    if (!sheet.mode) return;
    const atBottom = body().scrollHeight - body().scrollTop - body().clientHeight < 60;
    sheet.follow = atBottom;
    $('#followBtn').hidden = atBottom;
    $('#followBtn').textContent = '↓ ' + t('sheet.follow');
  });
  on('job', (m) => {
    if (sheet.mode !== 'job' || sheet.job !== m.id) return;
    $('#sheetTitle').textContent = jobTitle(m);
    applyLines(m.from, m.lines);
    renderProgress();
  });
  on('logs', (m) => {
    if (sheet.mode !== 'logs' || sheet.name !== m.name) return;
    const term = $('#term');
    if (!term) return;
    if (m.reset) { term.innerHTML = ''; sheet.base = 0; return; }
    // partial: 줄바꿈 전의 진행 중인 줄(진행률 막대). 항상 마지막 한 줄로만 유지한다.
    term.querySelector('.partial')?.remove();
    applyLines(sheet.base + term.childElementCount, m.lines);
    if (m.partial) {
      const d = makeLine(m.partial);
      d.classList.add('partial');
      term.append(d);
      if (sheet.follow) body().scrollTop = body().scrollHeight;
    }
  });
  on('state', () => { if (sheet.mode === 'job') renderProgress(); });
}
