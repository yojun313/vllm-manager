/* 의존성 없는 SVG 차트: 작은 추세선(sparkline)과 시간축 선 그래프. */
import { esc } from './ui.js';

const NS = 'http://www.w3.org/2000/svg';

function path(values, x, y) {
  let d = '', pen = false;
  values.forEach((v, i) => {
    if (v == null) { pen = false; return; }
    d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    pen = true;
  });
  return d;
}

// 카드 안에 넣는 작은 추세선. max 를 주면 그 값이 꼭대기.
export function sparkline(el, values, { color = 'var(--accent)', max } = {}) {
  const w = 200, h = 30;
  const pts = values.filter((v) => v != null);
  if (pts.length < 2) { el.innerHTML = ''; return; }
  const top = max ?? Math.max(...pts, 1);
  const x = (i) => (i / (values.length - 1)) * w;
  const y = (v) => h - 1 - (Math.min(v, top) / top) * (h - 2);
  const line = path(values, x, y);
  el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <path d="${line}L${w},${h}L0,${h}Z" fill="${color}" opacity=".13"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
}

function niceMax(v) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}

// el: .chart 요소. t: 초 단위 시각 배열. series: [{ name, color, values }]
export function lineChart(el, { t, series, max, fmt = (v) => String(v), empty = '' }) {
  const usable = series.filter((s) => s.values.some((v) => v != null));
  if (!t.length || !usable.length) { el.innerHTML = `<div class="chart-empty">${esc(empty)}</div>`; return; }
  const W = Math.max(el.clientWidth, 240), H = el.clientHeight || 190;
  const pad = { l: 44, r: 8, t: 8, b: 20 };
  const top = max ?? niceMax(Math.max(...usable.flatMap((s) => s.values.filter((v) => v != null)), 0));
  const n = t.length;
  const x = (i) => pad.l + (n === 1 ? 0 : (i / (n - 1)) * (W - pad.l - pad.r));
  const y = (v) => pad.t + (1 - Math.min(v, top) / top) * (H - pad.t - pad.b);
  const span = t[n - 1] - t[0];
  const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], span > 6 * 3600
    ? { hour: '2-digit', minute: '2-digit' } : { hour: '2-digit', minute: '2-digit' });
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img">`;
  for (let k = 0; k <= 4; k++) {
    const v = (top / 4) * k, yy = y(v);
    svg += `<line class="grid-line" x1="${pad.l}" x2="${W - pad.r}" y1="${yy}" y2="${yy}"/><text class="axis" x="${pad.l - 7}" y="${yy + 3.5}" text-anchor="end">${esc(fmt(v))}</text>`;
  }
  const ticks = Math.min(5, n);
  for (let k = 0; k < ticks; k++) {
    const i = Math.round((k / Math.max(ticks - 1, 1)) * (n - 1));
    svg += `<text class="axis" x="${x(i)}" y="${H - 4}" text-anchor="${k === 0 ? 'start' : k === ticks - 1 ? 'end' : 'middle'}">${esc(clock(t[i]))}</text>`;
  }
  usable.forEach((s) => {
    svg += `<path d="${path(s.values, x, y)}" fill="none" stroke="${s.color}" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"/>`;
  });
  svg += `<line class="cross" y1="${pad.t}" y2="${H - pad.b}" x1="0" x2="0" visibility="hidden"/></svg>`;
  el.innerHTML = svg + '<div class="chart-tip" hidden></div>';
  const cross = el.querySelector('.cross'), tip = el.querySelector('.chart-tip');
  const move = (ev) => {
    const box = el.getBoundingClientRect();
    const px = (ev.touches ? ev.touches[0].clientX : ev.clientX) - box.left;
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - pad.l) / (W - pad.l - pad.r)) * (n - 1))));
    cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
    tip.innerHTML = `<span class="t">${esc(new Date(t[i] * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: span <= 3600 ? '2-digit' : undefined }))}</span>`
      + usable.map((s) => `<span><i class="swatch" style="background:${s.color}"></i>${esc(s.name)}<b>${s.values[i] == null ? '-' : esc(fmt(s.values[i]))}</b></span>`).join('');
    tip.hidden = false;
    const left = x(i) + 12 + tip.offsetWidth > W ? x(i) - tip.offsetWidth - 12 : x(i) + 12;
    tip.style.left = Math.max(0, left) + 'px'; tip.style.top = '4px';
  };
  const leave = () => { cross.setAttribute('visibility', 'hidden'); tip.hidden = true; };
  el.onmousemove = move; el.onmouseleave = leave; el.ontouchstart = move; el.ontouchmove = move; el.ontouchend = leave;
}

export function legend(series) {
  return series.map((s) => `<span><i class="swatch" style="background:${s.color}"></i>${esc(s.name)}</span>`).join('');
}
export { NS };
