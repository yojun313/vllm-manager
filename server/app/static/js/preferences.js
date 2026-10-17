/* 첫 페인트 전에 테마 적용. 보안 정책에 맞춰 인라인 스크립트를 사용하지 않는다. */
(function () {
  'use strict';
  const KEY = 'vllm.workspace.preferences';
  const defaults = { theme: 'system', compact: false, reduceMotion: false, sidebarCollapsed: false,
    gpuEnabled: true, gpuInterval: 1, stateInterval: 2, gpuDetails: true };
  const media = matchMedia('(prefers-color-scheme: light)');
  function normalize(raw) {
    const p = { ...defaults };
    if (!raw || typeof raw !== 'object') return p;
    if (['system', 'light', 'dark'].includes(raw.theme)) p.theme = raw.theme;
    for (const k of ['compact', 'reduceMotion', 'sidebarCollapsed', 'gpuEnabled', 'gpuDetails']) {
      if (typeof raw[k] === 'boolean') p[k] = raw[k];
    }
    if ([1, 2, 5, 10, 30].includes(Number(raw.gpuInterval))) p.gpuInterval = Number(raw.gpuInterval);
    if ([2, 5, 10, 30].includes(Number(raw.stateInterval))) p.stateInterval = Number(raw.stateInterval);
    return p;
  }
  let current;
  try { current = normalize(JSON.parse(localStorage.getItem(KEY))); } catch (_) { current = normalize(null); }
  function apply() {
    const root = document.documentElement;
    const theme = current.theme === 'system' ? (media.matches ? 'light' : 'dark') : current.theme;
    root.dataset.theme = theme;
    root.classList.toggle('compact', current.compact);
    root.classList.toggle('reduce-motion', current.reduceMotion);
    root.classList.toggle('sidebar-collapsed', current.sidebarCollapsed);
    root.classList.toggle('hide-gpu-details', !current.gpuDetails);
    root.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'light' ? '#f4f6fb' : '#080c16');
  }
  function save(p) {
    current = normalize(p);
    let stored = true;
    try { localStorage.setItem(KEY, JSON.stringify(current)); } catch (_) { stored = false; }
    apply(); sync();
    const status = document.getElementById('settingsStatus');
    if (status) status.textContent = stored ? '저장됨 · 이 브라우저에 즉시 적용했습니다.' : '현재 화면에 적용했습니다. 브라우저 저장소를 사용할 수 없어 새로고침하면 초기화됩니다.';
    window.dispatchEvent(new CustomEvent('vllm:preferences', { detail: { ...current } }));
  }
  window.VllmUI = { get preferences() { return { ...current }; } };
  apply();
  media.addEventListener('change', apply);
  const fields = { prefTheme: 'theme', prefCompact: 'compact', prefMotion: 'reduceMotion',
    prefGpuEnabled: 'gpuEnabled', prefGpuInterval: 'gpuInterval', prefStateInterval: 'stateInterval', prefGpuDetails: 'gpuDetails' };
  function sync() {
    for (const [id, key] of Object.entries(fields)) {
      const el = document.getElementById(id);
      if (!el) continue;
      if (el.type === 'checkbox') el.checked = current[key]; else el.value = current[key];
    }
    const interval = document.getElementById('prefGpuInterval');
    if (interval) interval.disabled = !current.gpuEnabled;
    const label = document.getElementById('gpuRefreshLabel');
    if (label) label.textContent = current.gpuEnabled ? `실시간 · ${current.gpuInterval}초` : '업데이트 일시 정지';
    const toggle = document.getElementById('themeToggle');
    if (toggle) toggle.setAttribute('aria-label', document.documentElement.dataset.theme === 'light' ? '다크 모드로 전환' : '라이트 모드로 전환');
    const collapse = document.getElementById('collapseSidebar');
    if (collapse) {
      collapse.setAttribute('aria-expanded', String(!current.sidebarCollapsed));
      collapse.setAttribute('aria-label', current.sidebarCollapsed ? '사이드바 펼치기' : '사이드바 접기');
    }
  }
  document.addEventListener('DOMContentLoaded', () => {
    sync();
    for (const [id, key] of Object.entries(fields)) {
      const el = document.getElementById(id);
      el?.addEventListener('change', () => save({ ...current, [key]: el.type === 'checkbox' ? el.checked : el.value }));
    }
    document.getElementById('themeToggle')?.addEventListener('click', () => save({ ...current,
      theme: document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark' }));
    document.getElementById('resetPreferences')?.addEventListener('click', () => save(defaults));
    document.getElementById('collapseSidebar')?.addEventListener('click', () => save({ ...current, sidebarCollapsed: !current.sidebarCollapsed }));
    const menu = document.getElementById('menuToggle'), overlay = document.getElementById('navOverlay');
    const sidebar = document.getElementById('sidebar');
    const mobile = matchMedia('(max-width: 900px)');
    function syncDrawer() {
      if (sidebar) sidebar.inert = mobile.matches && !document.documentElement.classList.contains('nav-open');
    }
    function drawer(open) {
      document.documentElement.classList.toggle('nav-open', open);
      syncDrawer();
      menu?.setAttribute('aria-expanded', String(open));
      if (overlay) overlay.hidden = !open;
      if (open) document.querySelector('.side-nav a')?.focus(); else menu?.focus();
    }
    syncDrawer();
    mobile.addEventListener('change', () => { drawer(false); syncDrawer(); });
    menu?.addEventListener('click', () => drawer(!document.documentElement.classList.contains('nav-open')));
    overlay?.addEventListener('click', () => drawer(false));
    document.getElementById('closeSidebar')?.addEventListener('click', () => drawer(false));
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && document.documentElement.classList.contains('nav-open')) drawer(false);
      if (e.key === 'Tab' && document.documentElement.classList.contains('nav-open')) {
        const els = [...document.querySelectorAll('#sidebar a, #sidebar button')].filter(el => el.offsetParent !== null);
        if (e.shiftKey && document.activeElement === els[0]) { e.preventDefault(); els.at(-1)?.focus(); }
        else if (!e.shiftKey && document.activeElement === els.at(-1)) { e.preventDefault(); els[0]?.focus(); }
      }
    });
    function navigate() {
      const hash = location.hash.slice(1) || 'overview';
      const settings = hash === 'settings';
      const dashboard = document.getElementById('dashboardView'), preferences = document.getElementById('settingsView');
      if (!dashboard || !preferences) return;
      dashboard.hidden = settings; preferences.hidden = !settings;
      document.querySelectorAll('[data-nav]').forEach(el => {
        const active = el.dataset.nav === hash;
        el.classList.toggle('active', active);
        if (active) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current');
      });
      if (document.documentElement.classList.contains('nav-open')) drawer(false);
      if (settings) window.scrollTo({ top: 0 });
      else document.getElementById(hash)?.scrollIntoView({ block: 'start' });
    }
    document.querySelectorAll('.side-nav a, .side-bottom a').forEach(el => el.addEventListener('click', () => {
      if (location.hash === el.hash && document.documentElement.classList.contains('nav-open')) drawer(false);
    }));
    window.addEventListener('hashchange', navigate); navigate();
    window.addEventListener('storage', e => {
      if (e.key === KEY) {
        try { current = normalize(JSON.parse(e.newValue)); } catch (_) { current = normalize(null); }
        apply(); sync(); window.dispatchEvent(new CustomEvent('vllm:preferences', { detail: { ...current } }));
      }
    });
  });
})();
