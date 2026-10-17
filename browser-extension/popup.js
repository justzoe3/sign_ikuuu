const el = id => document.getElementById(id);
async function run(message) {
  const result = await chrome.runtime.sendMessage(message);
  el('status').textContent = result.message || '等待同步';
  return result;
}
chrome.runtime.sendMessage({type:'status'}).then(data => {
  el('repo').value = data.repo;
  el('status').textContent = data.status?.message || (data.configured ? '已配置，可立即同步。' : '先完成 GitHub 配置，再正常登录 iKuuu。');
  el('token').placeholder = data.configured ? '已保存；需要更新时重新输入' : 'github_pat_…';
});
const tokenUrl = new URL('https://github.com/settings/personal-access-tokens/new');
tokenUrl.search = new URLSearchParams({name:'iKuuu 会话同步',description:'仅供本机扩展更新 iKuuu 签到会话',
  target_name:'justzoe3',expires_in:'90',secrets:'write',actions:'write'});
el('create-token').href = tokenUrl.href;
el('save').addEventListener('click',async () => {
  const token = el('token').value;
  el('token').value = '';
  await run({type:'configure',repo:el('repo').value,token});
});
el('sync').addEventListener('click',() => run({type:'sync'}));
el('login').addEventListener('click',() => run({type:'login'}));
