/* GPU 카드 묶음 (대시보드와 모니터링에서 함께 쓴다). 값만 갱신해서 막대가 부드럽게 움직이게 한다. */
import { t } from '../i18n.js';
import { $, colorOf, esc, gib } from '../ui.js';
import { sparkline } from '../charts.js';
import { store } from '../store.js';

function card(wrap, idx) {
  let el = wrap.querySelector(`[data-gpu="${CSS.escape(idx)}"]`);
  if (el) return el;
  el = document.createElement('div');
  el.className = 'card';
  el.dataset.gpu = idx;
  el.innerHTML = `
    <div class="gpu-top"><span class="gpu-idx">GPU ${esc(idx)}</span><span class="gpu-name"></span>
      <div class="gpu-stats"><span><b class="temp">-</b>°C</span><span><b class="pw">-</b>W</span></div></div>
    <div class="gpu-mem"><div class="used">-</div><div class="free">${esc(t('gpu.free'))}<b>-</b></div></div>
    <div class="bar"></div>
    <div class="legend"></div>
    <div class="procs"></div>
    <div class="util"><span>${esc(t('gpu.util'))}</span><div class="spark"></div><span class="v">-</span></div>`;
  wrap.append(el);
  return el;
}

export function renderGpus(wrap) {
  const G = store.G, S = store.S;
  if (!G.length) {
    if (!wrap.querySelector('.skeleton')) wrap.innerHTML = `<div class="empty">${esc(t('gpu.none'))}</div>`;
    return;
  }
  wrap.querySelectorAll('.skeleton, .empty').forEach((x) => x.remove());
  wrap.dataset.count = G.length;
  const names = Object.fromEntries((S?.containers || []).map((c) => [c.name, c.model]));
  const keepCards = new Set(G.map((g) => g.idx));
  [...wrap.children].forEach((x) => { if (!keepCards.has(x.dataset.gpu)) x.remove(); });
  G.forEach((g) => {
    const el = card(wrap, g.idx);
    $('.gpu-name', el).textContent = g.name.replace('NVIDIA ', '');
    $('.temp', el).textContent = Math.round(g.temp);
    $('.pw', el).textContent = Math.round(g.power);
    $('.used', el).innerHTML = `${gib(g.used)}<small>/ ${gib(g.total)} GiB</small>`;
    $('.free b', el).textContent = gib(Math.max(0, g.free_new)) + ' GiB';

    // 막대: 모델별 조각(이름으로 키) + 다른 프로세스
    const bar = $('.bar', el);
    const segs = g.ours.map((o) => ({ key: o.name, label: names[o.name] || o.model, mib: o.mib, color: colorOf(names[o.name] || o.model) }));
    if (g.other > 0) segs.push({ key: '__other', label: t('gpu.other'), mib: g.other, other: true });
    const keep = new Set(segs.map((s) => s.key));
    [...bar.children].forEach((x) => { if (!keep.has(x.dataset.k)) x.remove(); });
    segs.forEach((s) => {
      let seg = bar.querySelector(`[data-k="${CSS.escape(s.key)}"]`);
      if (!seg) {
        seg = document.createElement('i');
        seg.dataset.k = s.key;
        if (s.other) { seg.className = 'other'; bar.append(seg); }
        else { seg.style.background = s.color; bar.insertBefore(seg, bar.querySelector('.other')); }
      }
      seg.style.width = (s.mib / g.total * 100) + '%';
      seg.title = `${s.label} ${gib(s.mib)} GiB`;
    });
    const legend = segs.length
      ? segs.map((s) => `<span><b ${s.other ? 'class="other"' : `style="background:${s.color}"`}></b>${esc(s.label)} <span class="mono">${gib(s.mib)}</span></span>`).join('')
      : `<span>${esc(t('gpu.empty'))}</span>`;
    const lg = $('.legend', el);
    if (lg.dataset.html !== legend) { lg.innerHTML = legend; lg.dataset.html = legend; }

    const procs = g.procs || [];
    const rows = procs.map((p) => `<li title="${esc(p.cmd || '')}"><span class="p-name">${esc(p.label)}${p.container ? ` <span class="p-tag">${esc(t('gpu.container'))}</span>` : ''}</span>
      <span class="p-meta mono">${esc(p.user || '-')} · PID ${esc(p.pid)}</span><span class="p-mib mono">${gib(p.mib)} GiB</span></li>`);
    if (procs.length && g.unlisted >= 512) rows.push(`<li><span class="p-name">${esc(t('gpu.unlisted'))}</span><span class="p-meta"></span><span class="p-mib mono">${gib(g.unlisted)} GiB</span></li>`);
    const html = rows.length ? `<div class="p-head">${esc(t('gpu.other'))}</div><ul>${rows.join('')}</ul>` : '';
    const pb = $('.procs', el);
    if (pb.dataset.html !== html) { pb.innerHTML = html; pb.dataset.html = html; }

    sparkline($('.spark', el), store.utilHistory[g.idx] || [], { max: 100 });
    $('.util .v', el).textContent = Math.round(g.util) + '%';
  });
}
