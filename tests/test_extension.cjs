const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {webcrypto} = require('node:crypto');
const root = path.resolve(__dirname, '../browser-extension');
const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

function environment(cookies, responseStatus=204) {
  const store = {repo:'justzoe3/sign_ikuuu',token:'github_pat_fixture_only'};
  const calls=[], tabs=[];
  const noopEvent={addListener() {}};
  const context={console, Uint8Array, Float64Array, Uint32Array, Int32Array, TextEncoder,
    atob,btoa,crypto:webcrypto,AbortSignal,setTimeout,clearTimeout,Date,Map,Error,
    chrome:{storage:{local:{
      get:async keys=> typeof keys==='string' ? {[keys]:store[keys]} : Object.fromEntries(keys.map(k=>[k,store[k]])),
      set:async values=>Object.assign(store,values)}},
      cookies:{getAll:async()=>cookies,onChanged:noopEvent},
      action:{setBadgeText:async()=>{},setBadgeBackgroundColor:async()=>{}},
      tabs:{create:async tab=>tabs.push(tab)},alarms:{create:async()=>{},onAlarm:noopEvent},
      runtime:{onInstalled:noopEvent,onStartup:noopEvent,onMessage:noopEvent}},
    fetch:async(url,options)=>{
      calls.push({url,options});
      const isKey=url.endsWith('/public-key');
      const status=isKey ? (responseStatus===401?401:200) : responseStatus;
      return {ok:status>=200&&status<300,status,
        json:async()=>isKey?{key:fixture.public_key,key_id:'fixture-key'}:{}};
    }};
  context.self=context;
  vm.createContext(context);
  const load = filename=>vm.runInContext(fs.readFileSync(path.join(root,filename),'utf8'),context,{filename});
  context.importScripts=(...files)=>files.forEach(load);
  load('background.js');
  return {context,store,calls,tabs};
}

(async()=>{
  const cookies=[{name:'uid',value:'fixture-user',domain:'.ikuuu.top'},
    {name:'key',value:'fixture-session-key',domain:'ikuuu.top'},
    {name:'other',value:'foreign-secret',domain:'.unrelated.invalid'}];
  const env=environment(cookies);
  const success=await env.context.sync(true,false);
  assert.equal(success.ok,true);
  assert.equal(env.calls.length,4);
  const update=env.calls.find(c=>c.url.endsWith('/secrets/IKUUU_COOKIE'));
  const encrypted=JSON.parse(update.options.body).encrypted_value;
  assert(!encrypted.includes('fixture-session-key'));
  for(const call of env.calls){
    assert(call.url.startsWith('https://api.github.com/repos/justzoe3/sign_ikuuu/'));
    assert.equal(call.options.redirect,'error');
    assert(!String(call.options.body).includes('fixture-session-key'));
    assert(!String(call.options.body).includes('foreign-secret'));
  }
  assert(!JSON.stringify(env.store.status).includes('fixture-session-key'));
  assert(!JSON.stringify(env.store.status).includes('github_pat_'));
  const count=env.calls.length;
  await env.context.sync(false,false);
  assert.equal(env.calls.length,count,'unchanged cookie must not make API requests');

  const missing=environment([]);
  const missingResult=await missing.context.sync(false);
  assert.equal(missingResult.ok,false);
  assert.equal(missing.calls.length,0);
  await missing.context.sync(false);
  assert.equal(missing.tabs.length,1,'login page must not repeatedly open');

  const expired=environment(cookies,401);
  const failed=await expired.context.sync(true);
  assert.equal(failed.ok,false);
  assert.equal(expired.calls.length,1);
  assert(!expired.store.lastHash,'failed synchronization must not mark success');
  fs.writeFileSync(process.argv[3],JSON.stringify({encrypted,
    expected:'key=fixture-session-key; uid=fixture-user'}));
  console.log('Extension: encryption boundary, target host, no plaintext transmission, unchanged-session deduplication, expiry, and rejected-token checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
