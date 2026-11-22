/* 첫 페인트 전에 테마와 언어를 정한다. 보안 정책상 인라인 스크립트를 쓰지 않으므로 head 에서 따로 불러온다. */
(function () {
  'use strict';
  var KEY = 'vllm.manager.preferences';
  var p = {};
  try { p = JSON.parse(localStorage.getItem(KEY)) || {}; } catch (_) { p = {}; }
  var root = document.documentElement;
  var light = matchMedia('(prefers-color-scheme: light)').matches;
  var theme = p.theme === 'light' || p.theme === 'dark' ? p.theme : (light ? 'light' : 'dark');
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  var lang = p.lang === 'ko' || p.lang === 'en' ? p.lang : (root.lang === 'ko' ? 'ko' : (navigator.language || '').toLowerCase().indexOf('ko') === 0 ? 'ko' : 'en');
  root.lang = lang;
  if (p.compact) root.classList.add('compact');
  if (p.reduceMotion) root.classList.add('reduce-motion');
  if (p.sidebarCollapsed) root.classList.add('sidebar-collapsed');
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', theme === 'light' ? '#f5f7fb' : '#0a0d14');
})();
