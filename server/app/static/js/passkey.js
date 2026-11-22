/* 패스키(WebAuthn): 로그인 화면의 로그인과 환경설정의 추가. 휴대폰의 패스키로 데스크톱에 로그인하는 것(QR 코드)은
 * 브라우저와 운영체제가 처리하고, 이 파일은 요청을 시작하기만 한다. */
import { t } from './i18n.js';

export const supported = () => !!(window.PublicKeyCredential && navigator.credentials && window.isSecureContext);

// base64url ⇄ 바이트 (서버는 JSON 을, WebAuthn 은 ArrayBuffer 를 쓴다)
const toBytes = (text) => {
  const pad = '='.repeat((4 - (text.length % 4)) % 4);
  const raw = atob((text + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
};
const toText = (buffer) => {
  let raw = '';
  new Uint8Array(buffer).forEach((b) => { raw += String.fromCharCode(b); });
  return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};

async function post(url, body) {
  const res = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : t('pk.failed'));
  return data;
}

// 창을 닫았거나 시간이 지났을 때 브라우저가 주는 문구는 알아보기 어려워 바꿔서 보여준다
const friendly = (error) => {
  if (error?.name === 'NotAllowedError') return new Error(t('pk.cancelled'));
  if (error?.name === 'InvalidStateError') return new Error(t('pk.exists'));
  if (error?.name === 'SecurityError') return new Error(t('pk.address'));
  return error instanceof Error ? error : new Error(String(error));
};

export async function register(password, name) {
  if (!supported()) throw new Error(t('pk.unsupported'));
  const { ticket, options } = await post('/api/auth/passkeys/options', { password });
  options.challenge = toBytes(options.challenge);
  options.user.id = toBytes(options.user.id);
  (options.excludeCredentials || []).forEach((item) => { item.id = toBytes(item.id); });
  let credential;
  try { credential = await navigator.credentials.create({ publicKey: options }); }
  catch (error) { throw friendly(error); }
  const r = credential.response;
  return post('/api/auth/passkeys', {
    ticket, name: name || '',
    credential: {
      id: credential.id, rawId: toText(credential.rawId), type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment || undefined,
      response: {
        clientDataJSON: toText(r.clientDataJSON), attestationObject: toText(r.attestationObject),
        transports: r.getTransports ? r.getTransports() : undefined,
      },
      clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
    },
  });
}

export async function login() {
  if (!supported()) throw new Error(t('pk.unsupported'));
  const { ticket, options } = await post('/api/auth/passkey/login/options');
  options.challenge = toBytes(options.challenge);
  (options.allowCredentials || []).forEach((item) => { item.id = toBytes(item.id); });
  let credential;
  try { credential = await navigator.credentials.get({ publicKey: options }); }
  catch (error) { throw friendly(error); }
  const r = credential.response;
  return post('/api/auth/passkey/login', {
    ticket,
    credential: {
      id: credential.id, rawId: toText(credential.rawId), type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment || undefined,
      response: {
        clientDataJSON: toText(r.clientDataJSON), authenticatorData: toText(r.authenticatorData),
        signature: toText(r.signature), userHandle: r.userHandle ? toText(r.userHandle) : undefined,
      },
      clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
    },
  });
}
