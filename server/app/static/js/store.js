/* 실시간 상태. 데이터는 WebSocket(/ws)으로 받는다: gpu(기본 1초), state(기본 2초·변경 시), job/logs(구독한 것만). */
import { getPrefs } from './ui.js';

export const store = {
  S: null,        // 마지막 state
  G: [],          // 마지막 gpu
  live: 'connecting',
  utilHistory: {},  // GPU 별 최근 사용률 (카드의 추세선)
};
const listeners = { gpu: new Set(), state: new Set(), job: new Set(), logs: new Set(), live: new Set() };
export function on(type, fn) { listeners[type].add(fn); return () => listeners[type].delete(fn); }
function emit(type, payload) { listeners[type].forEach((fn) => { try { fn(payload); } catch (e) { console.error(e); } }); }

let ws = null, backoff = 500, sub = { sub: null };
const SPARK_POINTS = 90;

function configure() {
  const p = getPrefs();
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ configure: {
    gpu_interval: Number(p.gpuInterval), state_interval: Number(p.stateInterval), gpu_enabled: !!p.gpuEnabled,
  } }));
}
window.addEventListener('vm:prefs', configure);

function setLive(v) { store.live = v; emit('live', v); }

export function seedUtilHistory(history) {
  Object.entries(history.gpus || {}).forEach(([idx, s]) => {
    store.utilHistory[idx] = (s.util || []).slice(-SPARK_POINTS);
  });
}

export function connect() {
  ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
  ws.onopen = () => {
    backoff = 500;
    setLive('ok');
    configure();
    ws.send(JSON.stringify({ ...sub, refresh: true }));
  };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === 'gpu') {
      store.G = m.gpus;
      m.gpus.forEach((g) => {
        const h = store.utilHistory[g.idx] || (store.utilHistory[g.idx] = []);
        h.push(g.util);
        if (h.length > SPARK_POINTS) h.shift();
      });
      emit('gpu', m.gpus);
    } else if (m.type === 'state') { store.S = m; emit('state', m); }
    else if (m.type === 'job') emit('job', m);
    else if (m.type === 'logs') emit('logs', m);
  };
  ws.onclose = (ev) => {
    if (ev.code === 1008) { location.href = '/login'; return; }
    setLive('bad');
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 8000);
  };
}

export function subscribe(msg) {
  sub = msg;
  if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg));
}
export function refresh() {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ refresh: true }));
}
