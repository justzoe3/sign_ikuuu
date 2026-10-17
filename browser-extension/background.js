/* No content scripts, password collection, paid services, or external relay. */
importScripts('vendor/nacl-fast.min.js', 'vendor/blake2b.bundle.js', 'seal.js');
const BASE = 'https://ikuuu.top';
const WORKFLOW = 'sign_ikuuu.yml';
let syncing = false;
let debounce;

function allowedDomain(domain) {
  return String(domain || '').replace(/^\./, '') === 'ikuuu.top';
}

async function state(value) {
  await chrome.storage.local.set({status: value, statusAt: Date.now()});
  await chrome.action.setBadgeText({text: value.ok ? '✓' : '!'});
  await chrome.action.setBadgeBackgroundColor({color: value.ok ? '#15803d' : '#b45309'});
}

async function github(config, path, method = 'GET', body) {
  const url = `https://api.github.com/repos/${config.repo}/${path}`;
  const result = await fetch(url, {
    method, redirect: 'error', credentials: 'omit', cache: 'no-store',
    signal: AbortSignal.timeout(25000),
    headers: {'Authorization': `Bearer ${config.token}`, 'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!result.ok) {
    if (result.status === 401) throw new Error('GitHub 令牌无效或已过期，请在设置中更新。');
    if ([403, 404].includes(result.status)) throw new Error('GitHub 权限不足：请检查指定仓库的 Secrets 写入和 Actions 写入权限。');
    throw new Error(`GitHub 请求失败（HTTP ${result.status}）。`);
  }
  return result.status === 204 ? null : result.json();
}

async function openLoginOnce() {
  const stored = await chrome.storage.local.get('lastLoginOpen');
  if (Date.now() - (stored.lastLoginOpen || 0) < 3600000) return;
  await chrome.storage.local.set({lastLoginOpen: Date.now()});
  await chrome.tabs.create({url: BASE + '/auth/login'});
}

async function sync(force = false, interactive = false) {
  if (syncing) return {ok: false, message: '正在同步，请稍候。'};
  syncing = true;
  try {
    const config = await chrome.storage.local.get(['repo', 'token', 'lastHash']);
    if (!config.token || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(config.repo || '')) {
      return {ok: false, message: '先配置 GitHub 仓库和专用令牌。'};
    }
    const cookies = (await chrome.cookies.getAll({url: BASE + '/user'}))
      .filter(c => allowedDomain(c.domain) && !/[\r\n;]/.test(c.name + c.value));
    const byName = new Map(cookies.map(c => [c.name, c.value]));
    if (!byName.get('uid') || !byName.get('key')) {
      const result = {ok: false, message: 'iKuuu 会话已过期，请在打开的页面正常登录。'};
      await state(result);
      await openLoginOnce();
      return result;
    }
    const cookie = cookies.sort((a, b) => a.name.localeCompare(b.name))
      .map(c => `${c.name}=${c.value}`).join('; ');
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(config.repo + '\n' + cookie));
    const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
    if (!force && hash === config.lastHash) return {ok: true, message: '会话未变化，无需重复同步。'};
    const key = await github(config, 'actions/secrets/public-key');
    const encrypted = sealForGitHub(key.key, cookie);
    await github(config, 'actions/secrets/IKUUU_COOKIE', 'PUT', {
      encrypted_value: encrypted, key_id: key.key_id
    });
    // Enable only this workflow, then dispatch the new session immediately.
    await github(config, `actions/workflows/${WORKFLOW}/enable`, 'PUT');
    await github(config, `actions/workflows/${WORKFLOW}/dispatches`, 'POST', {ref: 'main'});
    await chrome.storage.local.set({lastHash: hash, lastSyncedAt: Date.now()});
    const result = {ok: true, message: '会话已加密同步，已触发 GitHub Actions 签到。请在 Actions 查看网站实际结果。'};
    await state(result);
    if (interactive) await chrome.tabs.create({url: `https://github.com/${config.repo}/actions/workflows/${WORKFLOW}`});
    return result;
  } catch (_error) {
    // Do not persist browser/network errors that could include credentials.
    const message = _error instanceof Error && /^(GitHub|正在)/.test(_error.message)
      ? _error.message : '同步未完成，请检查网络后重试。';
    const result = {ok: false, message};
    await state(result);
    return result;
  } finally { syncing = false; }
}

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.alarms.create('session-check', {periodInMinutes: 30});
});
chrome.runtime.onStartup.addListener(() => sync(false));
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'session-check') sync(false);
});
chrome.cookies.onChanged.addListener(change => {
  if (!allowedDomain(change.cookie.domain)) return;
  clearTimeout(debounce);
  debounce = setTimeout(() => sync(false), 10000);
});
chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  (async () => {
    if (message.type === 'status') {
      const data = await chrome.storage.local.get(['repo', 'token', 'status', 'lastSyncedAt']);
      return {repo: data.repo || 'justzoe3/sign_ikuuu', configured: !!data.token,
        status: data.status, lastSyncedAt: data.lastSyncedAt};
    }
    if (message.type === 'configure') {
      const repo = String(message.repo || '').trim();
      const token = String(message.token || '').trim();
      if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo)) return {ok: false, message: '仓库格式应为 用户名/仓库名。'};
      if (!/^(github_pat_|ghp_)[A-Za-z0-9_]+$/.test(token)) return {ok: false, message: 'GitHub 令牌格式不正确。'};
      await chrome.storage.local.set({repo, token, lastHash: ''});
      return sync(true, true);
    }
    if (message.type === 'sync') return sync(true, true);
    if (message.type === 'login') {
      await chrome.tabs.create({url: BASE + '/auth/login'});
      return {ok: true, message: '已打开 iKuuu，登录完成后会自动同步。'};
    }
    return {ok: false, message: '未知操作。'};
  })().then(reply, () => reply({ok: false, message: '操作未完成，请重试。'}));
  return true;
});
