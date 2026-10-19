import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {before,after,test} from 'node:test';
import {chromium,expect} from '@playwright/test';

// UI ordering proof only: synthetic responses, no IdP or service authority.
const origin='https://rio-ordering.invalid';
const boundary={mode:'SYNTHETIC_ONLY',account1:'HOLD',accountActive:false,canOpenContact:false,operativeAuthority:'NONE'};
let browser;
let assets;
before(async()=>{
  assets=new Map(await Promise.all([
    ['/','index.html','text/html'],['/app.js','app.js','text/javascript'],['/app.css','app.css','text/css'],
  ].map(async([path,file,contentType])=>[path,{contentType,body:await readFile(new URL('../../services/rio-accounts/src/web/'+file,import.meta.url))}])));
  browser=await chromium.launch({headless:true});
});
after(async()=>{await browser?.close();});

for(const [pollStatus,logoutStatus] of [[503,200],[401,200],[503,503]]) {
  test(`late session read ${pollStatus} cannot replace logout result ${logoutStatus}`,{timeout:15000},async t=>{
    const context=await browser.newContext({serviceWorkers:'block'});
    t.after(()=>context.close());
    const page=await context.newPage();
    await page.clock.install();
    let reads=0;
    let resolvePoll,resolveLogout;
    const pendingPoll=new Promise(resolve=>{resolvePoll=resolve;});
    const pendingLogout=new Promise(resolve=>{resolveLogout=resolve;});
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url());
      if(url.origin!==origin) return route.abort('blockedbyclient');
      if(assets.has(url.pathname)) return route.fulfill({status:200,...assets.get(url.pathname)});
      const json=(status,value)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)});
      if(url.pathname==='/api/me') {
        reads+=1;
        if(reads===1) return json(200,{...boundary,accountId:'TST-alpha',csrfToken:'a'.repeat(43),actorKind:'SYNTHETIC_DEV_ACTOR',credentialControl:'VERIFIED_DEV_OIDC'});
        resolvePoll(route);return;
      }
      if(url.pathname==='/api/consent') return json(200,{...boundary,receipt:{scope:'RIO_SYNTHETIC_SESSION_TEST_V1',revision:0,granted:false,expiresAt:null}});
      if(url.pathname==='/auth/logout') {resolveLogout(route);return;}
      return route.abort('blockedbyclient');
    });
    await page.goto(origin);
    await expect(page.locator('#consent-refresh')).toBeEnabled();
    await page.clock.runFor(10001);
    const poll=await pendingPoll;
    await page.locator('#logout').click();
    const logout=await pendingLogout;
    await poll.fulfill({status:pollStatus,contentType:'application/json',body:'{}'});
    await page.clock.runFor(20);
    await page.evaluate(()=>Promise.resolve());
    await logout.fulfill({status:logoutStatus,contentType:'application/json',body:JSON.stringify(logoutStatus===200 ?
      {loggedOut:true,providerLogout:'NOT_REQUESTED',mode:'SYNTHETIC_ONLY'} : {error:'request_rejected',mode:'SYNTHETIC_ONLY'})});
    if(logoutStatus===200) {
      await expect(page.locator('#start-login')).toBeVisible();
      await expect(page.locator('#feedback')).toHaveText('Lokale testsessie afgemeld. De identity-provider heeft een afzonderlijke sessie.');
    } else {
      await expect(page.locator('#retry-session')).toBeVisible();
      await expect(page.locator('#start-login')).toBeHidden();
    }
    await expect(page.locator('#account-id')).toHaveText('');
    assert.equal(reads,2);
  });
}
