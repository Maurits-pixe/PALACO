import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,extname,sep} from 'node:path';
import {pathToFileURL} from 'node:url';

const modulePath=process.env.PALACO_PLAYWRIGHT_MODULE;
if(!modulePath)throw Error('Set PALACO_PLAYWRIGHT_MODULE to the installed Playwright index.mjs.');
const {chromium,firefox}=await import(pathToFileURL(resolve(modulePath)).href);
const root=resolve('website'),output=resolve(process.env.PALACO_QA_OUTPUT||'artifacts/studio-browser');
await mkdir(output,{recursive:true});
const report={head:process.env.PALACO_EXPECTED_HEAD||null,startedAt:new Date().toISOString(),engines:[],checks:[],errors:[],limitations:['Automated checks and captured evidence require visual review.','Local HTTP test headers are not deployed-host evidence.','Chromium PDF is tested; native OS print dialogs are not automated.']};
const passed=(engine,name)=>{report.checks.push({engine,name,result:'PASS'});console.log(engine+': PASS '+name)};
const server=createServer(async(req,res)=>{
  try{
    const name=decodeURIComponent(new URL(req.url,'http://localhost').pathname),file=resolve(root,'.'+(name==='/'?'/index.html':name));
    if(!file.startsWith(root+sep)||name.startsWith('/tests/')){res.writeHead(404);res.end();return}
    const content=await readFile(file),mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json'}[extname(file)]||'application/octet-stream';
    res.writeHead(200,{'Content-Type':mime+'; charset=utf-8','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; base-uri 'none'; object-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'none'; media-src 'none'; frame-src 'none'; frame-ancestors 'none'; form-action 'self'"});res.end(content);
  }catch{res.writeHead(404);res.end()}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin='http://127.0.0.1:'+server.address().port;
const storage=page=>page.evaluate(()=>JSON.parse(localStorage.getItem('palaco-cx001')));
const save=async(page,revision)=>{await page.locator('.tools [data-action="save"]').click();await page.waitForFunction(rev=>document.querySelector('#doc-state').textContent==='SAVED LOCAL · REV '+rev,revision)};
const view=(page,name)=>page.locator('[data-view="'+name+'"]').click();
const capture=async(page,name)=>{
  // Firefox full-page captures retain the current scroll offset for sticky elements.
  await page.evaluate(()=>window.scrollTo(0,0));await page.waitForFunction(()=>window.scrollY===0);
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.ok(Math.abs((await page.locator('.topbar').boundingBox()).y)<1,'Capture starts with navigation at the page top');
  await page.screenshot({path:resolve(output,name),fullPage:true});
};
const noOverflow=async(page,label)=>{
  const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,overflow:Array.from(document.querySelectorAll('body *')).filter(n=>{const r=n.getBoundingClientRect();return r.width&&r.right>innerWidth+1}).slice(0,12).map(n=>({tag:n.tagName,class:n.className,id:n.id,right:n.getBoundingClientRect().right}))}));
  if(layout.scroll>layout.width+1)await page.screenshot({path:resolve(output,label.replace(/[^a-z0-9]+/gi,'-')+'-overflow.png'),fullPage:true});
  assert.equal(layout.scroll<=layout.width+1,true,label+' '+JSON.stringify(layout));
};
const imageFixture=async page=>Buffer.from((await page.evaluate(()=>{
  const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;const c=canvas.getContext('2d');c.fillStyle='#151513';c.fillRect(0,0,640,360);c.strokeStyle='#a88b54';c.lineWidth=2;
  for(let x=80;x<640;x+=80){c.strokeRect(x,80,35,210)}c.beginPath();c.moveTo(30,320);c.lineTo(610,320);c.stroke();c.fillStyle='#f2eee5';c.font='28px serif';c.fillText('L.A. — test image',32,45);return canvas.toDataURL('image/png').split(',')[1];
})), 'base64');

async function suite(engine,type){
  const browser=await type.launch();report.engines.push({name:engine,version:browser.version()});
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
  const page=await context.newPage(),runtimeErrors=[],policyErrors=[],requests=[];
  page.on('pageerror',e=>runtimeErrors.push(e.message));page.on('console',m=>{if(m.type()==='error'&&/Content Security Policy|Refused to|violat/i.test(m.text()))policyErrors.push(m.text())});
  page.on('request',r=>{if(!r.url().startsWith(origin)&&!r.url().startsWith('data:')&&!r.url().startsWith('blob:'))requests.push(r.url())});
  page.on('dialog',dialog=>dialog.accept());
  try{
    await page.goto(origin+'/studio.html');await page.waitForFunction(()=>!!globalThis.PalacoDocuments&&document.querySelector('#sheet-id').textContent.startsWith('DOC-'));
    await noOverflow(page,'desktop start overflow');await capture(page,engine+'-start.png');
    await page.keyboard.press('Tab');assert.equal(await page.locator('.skip').evaluate(n=>n===document.activeElement),true);await page.keyboard.press('Enter');assert.equal(await page.locator('#main').evaluate(n=>n===document.activeElement),true);
    passed(engine,'keyboard skip link');
    await view(page,'identity');await page.locator('#identity-form [name="name"]').fill('Consumer QA');await page.locator('#identity-form [name="alias"]').fill('LA-maker');await page.locator('#identity-form [name="purpose"]').fill('Build a sober L.A. document');
    await page.locator('#identity-form [type="submit"]').click();await page.waitForFunction(()=>JSON.parse(localStorage.getItem('palaco-cx001')||'{}').identity?.name==='Consumer QA');
    const creator=(await storage(page)).identity.palacoId;assert.equal((await storage(page)).identity.alias,'LA-maker');assert.equal((await storage(page)).identity.purpose,'Build a sober L.A. document');
    passed(engine,'ID retains submitted name, alias and purpose');
    await view(page,'build');await page.locator('#title').fill('L.A. · Consumer document');await page.locator('#citadel').fill('LA-001');await page.locator('[data-add="heading"]').click();await page.locator('.heading-input').fill('A place to begin');
    await page.locator('[data-add="text"]').click();await page.locator('.text-input').fill('One sober sheet.\nCreator, source and revision stay visible.\nThis is an unverified local draft.');
    await page.locator('[data-add="image"]').click();await page.locator('#image-dialog button[value="cancel"]').last().click();assert.equal(await page.locator('#image-dialog').evaluate(n=>n.open),false);
    await page.locator('[data-add="image"]').click();await page.keyboard.press('Escape');assert.equal(await page.locator('#image-dialog').evaluate(n=>n.open),false);
    passed(engine,'image dialog cancels without a file and closes with Escape');
    await page.locator('[data-add="image"]').click();await page.locator('#image-file').setInputFiles({name:'la-test.png',mimeType:'image/png',buffer:await imageFixture(page)});await page.locator('#image-caption').fill('L.A. · image reference');await page.locator('#image-source').fill('Synthetic test fixture');await page.locator('#image-submit').click();
    await page.waitForFunction(()=>document.querySelector('.image-block img')?.complete&&document.querySelector('.image-block img').naturalWidth===640);
    await page.locator('[data-image-edit]').click();await page.locator('#image-role').selectOption('source');await page.locator('#image-caption').fill('Citadel source reference');await page.locator('#image-submit').click();await page.waitForFunction(()=>document.querySelector('.image-block .role').textContent==='source');
    await page.locator('[data-add="provenance"]').click();await save(page,1);let data=await storage(page),first=data.docs[0];assert.equal(first.creatorId,creator);assert.equal(first.blocks.find(b=>b.type==='image').role,'source');
    passed(engine,'image decodes and role/source details remain editable');
    await page.locator('#title').fill('L.A. · Second revision');assert.match(await page.locator('#doc-state').textContent(),/UNSAVED/);await save(page,2);
    await page.locator('.history summary').click();await page.locator('[data-restore="1"]').click();assert.equal(await page.locator('#title').inputValue(),'L.A. · Consumer document');await save(page,3);
    data=await storage(page);assert.equal(data.revisions[first.id].length,3);assert.equal(data.revisions[first.id][1].title,'L.A. · Second revision');assert.equal(data.docs[0].parentDigest,data.revisions[first.id][1].digest);
    passed(engine,'save and restore retain the revision chain');
    await page.reload();await view(page,'build');assert.equal(await page.locator('#title').inputValue(),'L.A. · Consumer document');assert.match(await page.locator('#doc-state').textContent(),/REV 3/);
    await noOverflow(page,'desktop builder overflow');await capture(page,engine+'-build.png');passed(engine,'saved document survives reload');
    await view(page,'rio');await page.locator('[data-action="rio-context"]').click();assert.match(await page.locator('#rio-log article').last().textContent(),/Document summary attached locally/);assert.match(await page.locator('#rio-context-state').textContent(),/L.A. · Consumer document/);await page.locator('#rio-input').fill('Help me continue');await page.locator('#rio-form button').click();assert.match(await page.locator('#rio-log article').last().textContent(),/Attached local context/);await capture(page,engine+'-rio.png');
    await view(page,'build');await page.locator('#title').fill('L.A. · Export current content');await view(page,'rio');assert.equal(await page.locator('#rio-context-state').textContent(),'No document context attached.');passed(engine,'RIO context attaches explicitly and clears after edits');
    await view(page,'build');const downloadPromise=page.waitForEvent('download');await page.locator('.tools [data-action="export"]').click();const download=await downloadPromise,exportPath=resolve(output,engine+'.palaco.json');await download.saveAs(exportPath);const exported=JSON.parse(await readFile(exportPath,'utf8'));assert.equal(exported.document.title,'L.A. · Export current content');assert.equal(exported.pendingChanges,true);
    await view(page,'docs');await page.locator('#import-file').setInputFiles(exportPath);await page.waitForFunction(()=>document.querySelector('#workspace-message').textContent.startsWith('Imported as a new local draft.'));assert.notEqual(await page.locator('#sheet-id').textContent(),first.id);assert.equal((await storage(page)).identity.palacoId,creator);await save(page,1);assert.equal((await storage(page)).docs.length,2);
    const importedId=await page.locator('#sheet-id').textContent();await view(page,'docs');const changed=JSON.parse(JSON.stringify(exported));changed.document.title='Changed without digest update';await page.locator('#import-file').setInputFiles({name:'changed.palaco.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(changed))});await page.waitForFunction(()=>document.querySelector('#workspace-message').textContent.includes('Export digest mismatch'));assert.equal((await storage(page)).docs.length,2);assert.equal(await page.locator('#sheet-id').textContent(),importedId);
    passed(engine,'JSON round-trip forks the document; tampered import is rejected');
    await view(page,'build');await page.evaluate(()=>{Storage.prototype.setItem=function(){throw new DOMException('Quota exceeded','QuotaExceededError')}});await page.locator('#title').fill('Changes kept after failed save');await page.locator('.tools [data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('#workspace-message').textContent.startsWith('Saving failed.'));assert.match(await page.locator('#doc-state').textContent(),/UNSAVED/);assert.equal((await storage(page)).docs.find(d=>d.id===importedId).revision,1);
    passed(engine,'quota failure retains open edits and saved revision');await page.reload();await view(page,'build');
    const other=await context.newPage();other.on('pageerror',e=>runtimeErrors.push(e.message));other.on('dialog',dialog=>dialog.accept());await other.goto(origin+'/studio.html');await view(other,'build');
    await page.evaluate(()=>{const original=PalacoDocuments.prepareRevision;PalacoDocuments.prepareRevision=async(...args)=>{const next=await original(...args);window.__savePaused=true;await new Promise(resolve=>window.__resumeSave=resolve);return next}});
    await page.locator('#title').fill('Pending edit in first tab');await page.locator('.tools [data-action="save"]').click();await page.waitForFunction(()=>window.__savePaused);
    await other.locator('#title').fill('Saved in the other tab');await save(other,2);await page.evaluate(()=>window.__resumeSave());
    await page.waitForFunction(()=>document.querySelector('#workspace-message').textContent.includes('another tab')&&!document.querySelector('#title').disabled);
    assert.equal((await storage(page)).docs.find(d=>d.id===importedId).title,'Saved in the other tab');assert.equal((await storage(page)).docs.find(d=>d.id===importedId).revision,2);
    assert.equal(await page.locator('#title').inputValue(),'Pending edit in first tab');assert.match(await page.locator('#doc-state').textContent(),/UNSAVED/);
    await other.close();await page.reload();await view(page,'build');passed(engine,'a second-tab save during hashing survives; pending edits remain open');
    if(engine==='chromium'){
      const long=Array.from({length:75},(_,i)=>'PRINT-LINE-'+String(i+1).padStart(3,'0')+' — Complete local document text remains readable.').join('\n');
      await page.locator('.text-input').fill(long);await page.emulateMedia({media:'print'});await page.evaluate(()=>window.dispatchEvent(new Event('beforeprint')));
      assert.equal(await page.locator('.print-text').textContent(),long);assert.equal(await page.locator('.tools').isVisible(),false);assert.equal(await page.locator('.text-input').isVisible(),false);assert.equal(await page.locator('.skip').isVisible(),false);
      await page.pdf({path:resolve(output,'studio-print.pdf'),format:'A4',printBackground:true,preferCSSPageSize:true});await page.emulateMedia({media:'screen'});passed(engine,'A4 PDF uses complete multiline content and hides editing tools');
    }
    const mobile=await context.newPage();mobile.on('pageerror',e=>runtimeErrors.push(e.message));mobile.on('dialog',dialog=>dialog.accept());await mobile.setViewportSize({width:390,height:844});await mobile.goto(origin+'/studio.html');
    for(const name of ['start','identity','build','docs','proof','rio']){await view(mobile,name);await noOverflow(mobile,'mobile '+name+' overflow');if(name==='build'){await mobile.waitForFunction(()=>Array.from(document.querySelectorAll('#title,.heading-input,.text-input')).every(n=>n.scrollHeight<=n.clientHeight+2));assert.equal(await mobile.locator('.inspector').evaluate(n=>n.scrollHeight<=n.clientHeight+1),true,'Inspector content must be visible without nested scrolling')}if(name==='build'||name==='rio'||name==='proof')await capture(mobile,engine+'-mobile-'+name+'.png')}
    await mobile.setViewportSize({width:320,height:740});for(const name of ['start','identity','build','docs','proof','rio']){await view(mobile,name);await noOverflow(mobile,'320px '+name+' overflow')}
    passed(engine,'all sections fit 390px and 320px; document text and inspector stay complete');await mobile.close();
    assert.deepEqual(runtimeErrors,[],'runtime errors');assert.deepEqual(policyErrors,[],'CSP violations');assert.deepEqual(requests,[],'unexpected remote requests');passed(engine,'no runtime errors, CSP violations or external requests');
  }catch(error){report.errors.push({engine,message:error.message,stack:error.stack});try{await page.screenshot({path:resolve(output,engine+'-failure.png'),fullPage:true})}catch{}throw error}
  finally{await context.close();await browser.close()}
}
let failure;
try{for(const [name,type] of [['chromium',chromium],['firefox',firefox]])await suite(name,type)}catch(error){failure=error}
finally{report.completedAt=new Date().toISOString();report.result=failure?'FAIL':'PASS';await writeFile(resolve(output,'browser-report.json'),JSON.stringify(report,null,2));await new Promise(resolve=>server.close(resolve))}
if(failure)throw failure;
console.log('PALACO Studio browser validation: PASS ('+report.checks.length+' checks)');
