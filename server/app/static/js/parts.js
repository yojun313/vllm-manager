/* 여러 화면이 함께 쓰는 조각: 상태 표시, 진행률, 작업 이름. */
import { t } from './i18n.js';
import { esc, fmtBytes, fmtElapsed, fmtEta, gib } from './ui.js';

export const STAGE_KEYS = ['boot', 'engine', 'download', 'weights', 'compile', 'kvcache', 'graphs', 'server'];

export function statusOf(c) {
  if (c.state !== 'running') return ['bad', t('status.stopped')];
  if (c.health) return ['ok', t('status.running')];
  if (c.progress?.error) return ['bad', t('status.error')];
  return ['warn', t('status.starting')];
}
export const engineName = (e) => (e === 'vllm-omni' ? 'vLLM-Omni' : 'vLLM');

export function stageName(p) {
  const name = t('stage.' + p.key);
  return p.sub != null ? `${name} ${p.sub}%` : name;
}
function progressDetail(p) {
  if (p.info?.k === 'weights') return t('stage.info.weights', { v: p.info.v });
  if (p.info?.k === 'kv') return t('stage.info.kv', { v: p.info.v });
  return p.key === 'stopped' ? (p.detail || '') : '';
}
export function progressHtml(p, created, compact) {
  const cur = STAGE_KEYS.indexOf(p.key);
  const steps = STAGE_KEYS.map((k, i) => `<span class="${i < cur ? 'done' : i === cur ? 'cur' : ''}"></span>`).join('');
  return `<div class="prog">
    <div class="prog-top"><span class="stage">${esc(stageName(p))}</span><span class="pct">${Math.floor(p.pct)}%</span></div>
    <div class="prog-track"><i style="width:${p.pct}%"></i></div>
    ${compact ? '' : `<div class="prog-steps">${steps}</div>`}
    <div class="prog-meta"><span>${esc(progressDetail(p))}</span><span>${esc(t('common.elapsed'))} <span data-since="${created || ''}">${created ? fmtElapsed(Date.now() / 1000 - created) : '-'}</span></span></div>
    ${p.error ? `<div class="prog-err">${esc(p.error)}</div>` : ''}
  </div>`;
}

// 다운로드 진행률 (바이트 기준, 서버 계산 → 모든 기기에서 같음)
export function dlProgressHtml(j) {
  const p = j.progress || {};
  const running = j.status === 'running';
  const pct = p.pct ?? (running ? null : 100);
  const label = running ? (p.total ? t('dl.downloading') : t('dl.sizing')) : jobStatusText(j);
  const left = p.total ? `${fmtBytes(p.done)} / ${fmtBytes(p.total)}` : fmtBytes(p.done);
  const speed = running && p.speed ? `${fmtBytes(p.speed)}/s · ${fmtEta(p.eta)}` : '';
  return `<div class="prog">
    <div class="prog-top"><span class="stage">${esc(label)}</span><span class="pct">${pct == null ? '' : Math.floor(pct) + '%'}</span></div>
    <div class="prog-track"><i style="width:${pct == null ? 3 : pct}%"></i></div>
    <div class="prog-meta"><span>${esc(left)}</span><span>${esc(speed) || (running ? `${esc(t('common.elapsed'))} <span data-since="${j.started}">${fmtElapsed(Date.now() / 1000 - j.started)}</span>` : '')}</span></div>
  </div>`;
}

export function jobTitle(j) {
  const where = j.gpus ? `GPU ${j.gpus}` : t('job.autoGpu');
  switch (j.kind) {
    case 'up': return t('job.up', { target: j.target, where });
    case 'down': return t('job.down', { target: j.target });
    case 'pull': return t('job.pull', { target: j.target });
    case 'rm': return j.files ? t('job.rmFiles', { target: j.target }) : t('job.rm', { target: j.target });
    default: return j.title;
  }
}
export const jobKind = (j) => (j.status === 'running' ? 'warn' : j.status === 'done' ? 'ok' : 'bad');
export function jobStatusText(j) {
  if (j.status === 'running') return t('job.running');
  if (j.status === 'done') return t('job.done');
  return j.canceled ? t('job.canceled') : t('job.failed');
}
export const jobPill = (j) => `<span class="pill ${j.canceled && j.status !== 'running' ? '' : jobKind(j)}">${esc(jobStatusText(j))}</span>`;

// 필요 메모리의 구성(가중치·KV 캐시·여유)을 막대와 문구로 보여준다
export function planHtml(m) {
  const b = m.breakdown || { kind: 'text' };
  if (b.kind === 'auto') {
    const total = b.weights + b.kv + b.overhead || 1;
    const pc = (v) => (v / total * 100).toFixed(1);
    return `<div class="split-bar" title="${esc(m.desc)}"><i class="w" style="width:${pc(b.weights)}%"></i><i class="kv" style="width:${pc(b.kv)}%"></i><i class="oh" style="width:${pc(b.overhead)}%"></i></div>
      <div class="split-legend"><span><i style="background:var(--accent)"></i>${esc(t('plan.weights'))} <b>${b.weights.toFixed(1)}</b></span>
        <span><i style="background:var(--accent-2)"></i>${esc(t('plan.kv'))} <b>${b.kv.toFixed(1)}</b></span>
        <span><i style="background:var(--line2)"></i>${esc(t('plan.overhead'))} <b>${b.overhead.toFixed(1)}</b></span></div>
      <div class="desc">${esc(t('plan.tokens', { tokens: b.tokens.toLocaleString(), n: b.concurrency }))}</div>`;
  }
  const text = b.kind === 'manual' ? t('plan.manual', { v: b.util ?? '' })
    : b.kind === 'omni' ? t('plan.omni')
    : b.kind === 'unknown' ? t('plan.unknown') : m.desc;
  return `<div class="desc" title="${esc(m.desc)}">${esc(text)}</div>`;
}

export function endpointOf(c) {
  const raw = c.public_url || `http://${location.hostname}:${c.port}/v1`;
  return /^https?:\/\//.test(raw) ? raw : 'https://' + raw;
}
export { gib };
