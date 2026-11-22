/* 공통 도구: DOM, 형식, 알림, API 호출, 창, 환경설정. */
import { t } from './i18n.js';

export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const gib = (mib) => (mib / 1024).toFixed(1);

const PALETTE = ['#7696ff', '#3fd0e8', '#3ddc97', '#f5b84a', '#ff7eb6', '#a78bfa', '#ffa46b', '#b4e05a', '#e879f9', '#2dd4bf', '#fca5a5', '#93c5fd'];
const colors = {};
let colorIdx = 0;
export const colorOf = (k) => colors[k] || (colors[k] = PALETTE[colorIdx++ % PALETTE.length]);
export const gpuColor = (i) => PALETTE[Number(i) % PALETTE.length];

export function fmtBytes(b) {
  if (b == null) return '-';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return (i >= 3 ? b.toFixed(1) : Math.round(b)) + ' ' + u[i];
}
export function fmtNum(n) {
  if (n == null) return '-';
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e4) return (n / 1e3).toFixed(1) + 'k';
  return String(Math.round(n));
}
export function fmtElapsed(sec) {
  sec = Math.max(0, Math.floor(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  return m >= 60 ? t('time.hm', { h: Math.floor(m / 60), m: m % 60 }) : `${m}:${String(s).padStart(2, '0')}`;
}
export function fmtDuration(sec) {
  sec = Math.max(0, Math.round(sec));
  if (sec < 60) return t('time.s', { s: sec });
  if (sec < 3600) return t('time.m', { m: Math.round(sec / 60) });
  if (sec < 86400) return t('time.hm', { h: Math.floor(sec / 3600), m: Math.round((sec % 3600) / 60) });
  return t('time.d', { d: Math.floor(sec / 86400) });
}
export function fmtEta(sec) { return sec == null ? '' : t('time.left', { v: fmtDuration(sec) }); }
export function fmtAgo(ts) { return ts ? t('time.ago', { v: fmtDuration(Date.now() / 1000 - ts) }) : '-'; }
export function fmtClock(ts) {
  return new Date(ts * 1000).toLocaleString(document.documentElement.lang, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/* ------------------------------------------------------------ 아이콘 (선 굵기 1.8, 24px 격자) */
const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  models: '<path d="M12 3 3 7.5l9 4.5 9-4.5L12 3Z"/><path d="m3 12 9 4.5 9-4.5"/><path d="m3 16.5 9 4.5 9-4.5"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z"/>',
  chart: '<path d="M3 3v18h18"/><path d="m7 15 4-5 3 3 5-7"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  system: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.9 2.9l-.1-.1a1.7 1.7 0 0 0-2.8 1.2V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.9l.1-.1A1.7 1.7 0 0 0 3.1 14H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.9-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.9l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  collapse: '<path d="m11 17-5-5 5-5"/><path d="m18 17-5-5 5-5"/>',
  moon: '<path d="M20.8 13A9 9 0 0 1 11 3.2 9 9 0 1 0 20.8 13Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  play: '<path d="M7 4.5v15l13-7.5z" fill="currentColor" stroke="none"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
  download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  more: '<circle cx="5" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="19" cy="12" r="1.4" fill="currentColor"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="m19 6-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  logs: '<path d="M4 6h16M4 12h10M4 18h13"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 4v5h-5"/>',
  send: '<path d="m4 12 16-8-6 16-3-7-7-1Z"/>',
  check: '<path d="m5 12 5 5 9-10"/>',
  alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
  gpu: '<rect x="3" y="6" width="18" height="12" rx="2"/><circle cx="9" cy="12" r="2.5"/><path d="M15 10h2M15 14h2M7 18v2M12 18v2M17 18v2"/>',
  disk: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9"/><path d="m17 6 3 3"/><path d="m14 9 2 2"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z"/>',
  box: '<path d="M21 8 12 3 3 8v8l9 5 9-5V8Z"/><path d="m3 8 9 5 9-5"/><path d="M12 13v8"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  code: '<path d="m8 8-5 4 5 4M16 8l5 4-5 4M14 4l-4 16"/>',
  link: '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
};
export function icon(name, size = 18) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
}
export function hydrateIcons(root = document) {
  $$('[data-icon]', root).forEach((el) => { el.innerHTML = icon(el.dataset.icon, +el.dataset.size || 18); });
}

/* ------------------------------------------------------------ 알림·복사·API */
export function toast(msg, kind) {
  const el = document.createElement('div');
  el.className = 'toast ' + (kind || '');
  el.textContent = msg;
  $('#toasts').append(el);
  setTimeout(() => el.remove(), 4500);
}

export async function copy(text, msg) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = document.createElement('textarea');
    ta.value = text; document.body.append(ta); ta.select(); document.execCommand('copy'); ta.remove();
  }
  toast(msg || t('common.copied'), 'ok');
}

export async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts, credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    body: opts.body && typeof opts.body !== 'string' ? JSON.stringify(opts.body) : opts.body,
  });
  if (res.status === 401) { location.href = '/login'; throw new Error(t('common.signin')); }
  if (!res.ok) {
    let d = res.statusText;
    try { d = (await res.json()).detail || d; } catch (e) { /* 본문 없음 */ }
    throw new Error(typeof d === 'string' ? d : JSON.stringify(d));
  }
  const ct = res.headers.get('content-type') || '';
  return ct.includes('json') ? res.json() : res.text();
}

/* ------------------------------------------------------------ 창 */
// html: 창 내용. setup(el, close): 이벤트 연결. 닫힐 때의 값으로 resolve 한다.
export function modal({ html, wide, setup, dismissable = true }) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal-wrap';
    wrap.innerHTML = `<div class="modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true">${html}</div>`;
    const previous = document.activeElement;
    const close = (value) => {
      document.removeEventListener('keydown', onKey, true);
      wrap.remove();
      previous?.focus?.();
      resolve(value);
    };
    const onKey = (e) => { if (e.key === 'Escape' && dismissable) { e.stopPropagation(); close(null); } };
    document.addEventListener('keydown', onKey, true);
    wrap.addEventListener('mousedown', (e) => { if (e.target === wrap && dismissable) close(null); });
    $('#modalRoot').append(wrap);
    hydrateIcons(wrap);
    $$('[data-close]', wrap).forEach((b) => b.addEventListener('click', () => close(null)));
    setup?.(wrap, close);
    setTimeout(() => (wrap.querySelector('[autofocus]') || wrap.querySelector('input, textarea, button'))?.focus(), 30);
  });
}
export function confirmDialog({ title, html = '', ok, danger = true }) {
  return modal({
    html: `<h3>${esc(title)}</h3><div class="modal-body">${html}</div>
      <div class="modal-actions"><button class="btn ghost" data-close autofocus>${esc(t('common.cancel'))}</button>
      <button class="btn ${danger ? 'danger solid' : 'primary'}" data-ok>${esc(ok)}</button></div>`,
    setup: (el, close) => { $('[data-ok]', el).onclick = () => close(true); },
  }).then(Boolean);
}

/* ------------------------------------------------------------ 환경설정 (브라우저 저장) */
const KEY = 'vllm.manager.preferences';
const DEFAULTS = { theme: 'system', lang: '', compact: false, reduceMotion: false, sidebarCollapsed: false,
  gpuEnabled: true, gpuInterval: 1, stateInterval: 2, sensors: true, viewMode: 'cards' };
let prefs = { ...DEFAULTS };
try { prefs = { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(KEY)) || {}) }; } catch (e) { /* 저장소 사용 불가 */ }
const media = matchMedia('(prefers-color-scheme: light)');

export const getPrefs = () => ({ ...prefs });
export const defaultPrefs = () => ({ ...DEFAULTS, lang: prefs.lang });
export function applyPrefs() {
  const root = document.documentElement;
  const theme = prefs.theme === 'system' ? (media.matches ? 'light' : 'dark') : prefs.theme;
  root.dataset.theme = theme;
  root.dataset.view = prefs.viewMode;
  root.style.colorScheme = theme;
  root.classList.toggle('compact', prefs.compact);
  root.classList.toggle('reduce-motion', prefs.reduceMotion);
  root.classList.toggle('sidebar-collapsed', prefs.sidebarCollapsed);
  root.classList.toggle('hide-sensors', !prefs.sensors);
  $('meta[name="theme-color"]')?.setAttribute('content', theme === 'light' ? '#f5f7fb' : '#0a0d14');
}
export function setPrefs(patch) {
  prefs = { ...prefs, ...patch };
  let stored = true;
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (e) { stored = false; }
  applyPrefs();
  window.dispatchEvent(new CustomEvent('vm:prefs', { detail: { ...prefs, stored } }));
  return stored;
}
media.addEventListener('change', applyPrefs);
window.addEventListener('storage', (e) => {
  if (e.key !== KEY) return;
  try { prefs = { ...DEFAULTS, ...(JSON.parse(e.newValue) || {}) }; } catch (err) { prefs = { ...DEFAULTS }; }
  applyPrefs();
  window.dispatchEvent(new CustomEvent('vm:prefs', { detail: { ...prefs, stored: true } }));
});
window.addEventListener('vm:lang', (e) => { prefs.lang = e.detail; });
