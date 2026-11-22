/* vLLM Manager 화면의 뼈대: 메뉴, 주소(#/…)에 따른 화면 전환, 상단 알림. */
import { applyI18n, setLang, t } from './i18n.js';
import { $, $$, api, applyPrefs, esc, fmtElapsed, getPrefs, hydrateIcons, icon, setPrefs, toast } from './ui.js';
import { connect, on, store } from './store.js';
import { closeSheet, initSheet, sheetOpen } from './sheet.js';
import { jobTitle } from './parts.js';
import * as dashboard from './views/dashboard.js';
import * as models from './views/models.js';
import * as playground from './views/playground.js';
import * as monitor from './views/monitor.js';
import * as activity from './views/activity.js';
import * as system from './views/system.js';
import * as settings from './views/settings.js';

const ROUTES = {
  '': { view: dashboard, icon: 'dashboard', key: 'nav.dashboard' },
  models: { view: models, icon: 'models', key: 'nav.models' },
  playground: { view: playground, icon: 'chat', key: 'nav.playground' },
  monitor: { view: monitor, icon: 'chart', key: 'nav.monitor' },
  activity: { view: activity, icon: 'activity', key: 'nav.activity' },
  system: { view: system, icon: 'system', key: 'nav.system', bottom: true },
  settings: { view: settings, icon: 'settings', key: 'nav.settings', bottom: true },
};
const TABS = ['', 'models', 'playground', 'monitor', 'system'];
let current = null;
const jobStatus = {};

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [path, query = ''] = raw.split('?');
  return { name: ROUTES[path] ? path : '', query: new URLSearchParams(query) };
}

function buildNav() {
  const link = (name, r) => `<a class="nav-link" href="#/${name}" data-nav="${name}" title="${esc(t(r.key))}"><span class="nav-icon">${icon(r.icon)}</span><span class="side-label">${esc(t(r.key))}</span>${name === 'activity' ? '<span class="badge" data-jobs hidden></span>' : ''}</a>`;
  $('#sideNav').innerHTML = Object.entries(ROUTES).filter(([, r]) => !r.bottom).map(([n, r]) => link(n, r)).join('');
  $('#sideNavBottom').innerHTML = Object.entries(ROUTES).filter(([, r]) => r.bottom).map(([n, r]) => link(n, r)).join('');
  $('#tabbar').innerHTML = TABS.map((n) => `<a href="#/${n}" data-nav="${n}">${icon(ROUTES[n].icon, 20)}<span>${esc(t(ROUTES[n].key))}</span></a>`).join('');
}

function drawer(open) {
  document.documentElement.classList.toggle('nav-open', open);
  $('#navOverlay').hidden = !open;
  $('#menuToggle').setAttribute('aria-expanded', String(open));
}

function navigate() {
  const { name, query } = parseHash();
  current?.view.unmount?.();
  current = ROUTES[name];
  $$('[data-nav]').forEach((a) => {
    const active = a.dataset.nav === name;
    a.classList.toggle('active', active);
    if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  $('#pageTitle').textContent = t(current.key);
  document.title = `${t(current.key)} · vLLM Manager`;
  drawer(false);
  const view = $('#view');
  view.innerHTML = '';
  view.onclick = view.onchange = view.onsubmit = null;
  window.scrollTo({ top: 0 });
  current.view.mount(view, query);
}

function renderShell() {
  const S = store.S;
  const p = getPrefs();
  $('#liveDot').className = 'dot ' + (store.live === 'ok' ? 'ok' : store.live === 'bad' ? 'bad' : 'warn');
  $('#liveTxt').textContent = store.live === 'ok' ? (p.gpuEnabled ? t('live.on', { n: p.gpuInterval }) : t('live.paused')) : store.live === 'bad' ? t('live.reconnect') : t('live.connecting');
  $('#themeToggle').innerHTML = icon(document.documentElement.dataset.theme === 'light' ? 'moon' : 'sun');
  $('#themeToggle').title = t('top.theme');
  $('#langBtn').textContent = document.documentElement.lang === 'ko' ? 'EN' : '한';
  $('#langBtn').title = t('top.lang');
  $('#logoutBtn').title = t('acct.signOut');
  $('#menuToggle').setAttribute('aria-label', t('top.menu'));
  if (!S) return;
  $('#pageSub').textContent = S.image || '';
  const running = S.jobs.filter((j) => j.status === 'running').length;
  $$('#jobsBadge, [data-jobs]').forEach((b) => { b.hidden = !running; b.textContent = running; });
  const banners = [];
  if (S.demo) banners.push(`<div class="notice info"><span>${icon('info')}</span><div class="grow"><b>${esc(t('banner.demo'))}</b> ${esc(t('banner.demoBody'))}</div></div>`);
  if (!S.docker_ok) banners.push(`<div class="notice bad"><span>${icon('alert')}</span><div class="grow"><b>${esc(t('banner.docker'))}</b> ${t('banner.dockerBody')}<div class="mono small" style="opacity:.75;margin-top:4px">${esc(S.docker_error)}</div></div></div>`);
  if (S.prepare?.state === 'running') banners.push(`<div class="notice info"><span>${icon('box')}</span><div class="grow"><b>${esc(t('banner.prepare'))}</b> ${esc(t('banner.prepareBody'))}<div class="mono small" style="opacity:.75;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(S.prepare.last)}</div></div></div>`);
  if (S.prepare?.state === 'failed' && S.docker_ok) banners.push(`<div class="notice warn"><span>${icon('alert')}</span><div class="grow"><b>${esc(t('banner.prepareFail'))}</b><div class="mono small" style="opacity:.8;margin-top:4px;overflow-wrap:anywhere">${esc(S.prepare.error)}</div></div><button class="btn sm" id="prepareRetry">${esc(t('banner.retry'))}</button></div>`);
  const html = banners.join('');
  if ($('#banners').dataset.html !== html) { $('#banners').innerHTML = html; $('#banners').dataset.html = html; }
}

function watchJobs() {
  (store.S?.jobs || []).forEach((j) => {
    if (jobStatus[j.id] === 'running' && j.status !== 'running') {
      toast(`${jobTitle(j)} — ${j.status === 'done' ? t('job.done') : j.canceled ? t('job.canceled') : t('job.failed')}`, j.status === 'done' ? 'ok' : 'bad');
    }
    jobStatus[j.id] = j.status;
  });
}

function init() {
  applyPrefs();
  applyI18n();
  hydrateIcons();
  buildNav();
  initSheet();
  $('#menuToggle').onclick = () => drawer(!document.documentElement.classList.contains('nav-open'));
  $('#navOverlay').onclick = () => drawer(false);
  $('#collapseSidebar').onclick = () => setPrefs({ sidebarCollapsed: !getPrefs().sidebarCollapsed });
  $('#themeToggle').onclick = () => setPrefs({ theme: document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark' });
  $('#langBtn').onclick = () => setLang(document.documentElement.lang === 'ko' ? 'en' : 'ko');
  $('#banners').onclick = (e) => { if (e.target.closest('#prepareRetry')) api('/api/system/prepare', { method: 'POST' }).catch((err) => toast(err.message, 'bad')); };
  $('#jobsBtn').onclick = () => { location.hash = '#/activity'; };
  $('#logoutBtn').onclick = async () => { await fetch('/api/logout', { method: 'POST' }); location.href = '/login'; };
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (document.documentElement.classList.contains('nav-open')) drawer(false);
    else if (sheetOpen()) closeSheet();
  });
  // 경과 시간 표시는 1초마다 스스로 갱신한다
  setInterval(() => {
    $$('[data-since]').forEach((el) => { const ts = +el.dataset.since; if (ts) el.textContent = fmtElapsed(Date.now() / 1000 - ts); });
  }, 1000);
  on('state', () => { renderShell(); watchJobs(); });
  on('live', renderShell);
  window.addEventListener('vm:prefs', renderShell);
  window.addEventListener('vm:lang', () => { applyI18n(); buildNav(); renderShell(); navigate(); });
  window.addEventListener('hashchange', navigate);
  renderShell();
  navigate();
  connect();
}
init();
