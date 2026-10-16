import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawn } from 'node:child_process';
import { chromium } from 'playwright';
import https from 'node:https';
import { fileURLToPath } from 'node:url';
import Database from 'better-sqlite3';

const root = fileURLToPath(new URL('../', import.meta.url));
const certDir = path.join(root, 'certs'); fs.mkdirSync(certDir, { recursive: true });
const testDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bastion-browser-'));
const databasePath = path.join(testDir, 'bastion.db');
const configPath = path.join(certDir, 'openssl.cnf'); fs.writeFileSync(configPath, '[req]\ndistinguished_name = dn\n[dn]\n');
const opensslCandidates = process.platform === 'win32'
  ? ['C:/Strawberry/c/bin/openssl.exe', 'openssl']
  : ['openssl'];
const openssl = process.env.BASTION_OPENSSL_BIN ?? opensslCandidates.find(candidate => candidate === 'openssl' || fs.existsSync(candidate));
const browserCandidates = process.platform === 'win32'
  ? [
      path.join(process.env['PROGRAMFILES(X86)'] ?? 'C:/Program Files (x86)', 'Microsoft/Edge/Application/msedge.exe'),
      path.join(process.env.PROGRAMFILES ?? 'C:/Program Files', 'Microsoft/Edge/Application/msedge.exe'),
      path.join(process.env.PROGRAMFILES ?? 'C:/Program Files', 'Google/Chrome/Application/chrome.exe')
    ]
  : process.platform === 'darwin'
    ? ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge']
    : ['/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome', '/opt/google/chrome/chrome', '/opt/microsoft/msedge/msedge'];
const browserExecutable = process.env.BASTION_BROWSER_EXECUTABLE ?? browserCandidates.find(candidate => fs.existsSync(candidate));
const run = args => execFileSync(openssl, args, { cwd: certDir, env: { ...process.env, OPENSSL_CONF: configPath }, stdio: 'pipe' });
run(['req','-x509','-newkey','rsa:2048','-nodes','-keyout','ca-key.pem','-out','ca.pem','-days','1','-subj','/CN=Bastion preview CA','-addext','basicConstraints=critical,CA:TRUE']);
run(['req','-new','-newkey','rsa:2048','-nodes','-keyout','localhost-key.pem','-out','localhost.csr','-subj','/CN=localhost']);
fs.writeFileSync(path.join(certDir,'ext.cnf'),'subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\n');
run(['x509','-req','-in','localhost.csr','-CA','ca.pem','-CAkey','ca-key.pem','-CAcreateserial','-out','localhost.pem','-days','1','-extfile','ext.cnf']);
const child = spawn(process.execPath, ['node_modules/vite/bin/vite.js','preview','--configLoader','native'], { cwd: root, stdio: ['ignore','pipe','pipe'] });
const backend = spawn(process.execPath, ['server.js'], { cwd: root, env: { ...process.env, BASTION_PORT: '3005', BASTION_DB_PATH: databasePath, BASTION_ALLOWED_ORIGINS: 'https://localhost:5175,https://127.0.0.1:5175' }, stdio: ['ignore','pipe','pipe'] });
let log=''; child.stdout.on('data', d => { log += d; }); child.stderr.on('data', d => { log += d; });
let backendLog=''; backend.stdout.on('data', d => { backendLog += d; }); backend.stderr.on('data', d => { backendLog += d; });
const request = (url, opts={}) => new Promise((resolve,reject) => { const req=https.get(url,{ca:fs.readFileSync(path.join(certDir,'ca.pem')),...opts},res=>{const chunks=[];res.on('data',c=>chunks.push(c));res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks).toString()}));});req.on('error',reject); });
let pageBrowser;
try {
  for (let i=0;i<100;i++) { try { const r=await request('https://127.0.0.1:5175/'); if(r.status===200) break; } catch {} await new Promise(r=>setTimeout(r,100)); }
  for (let i=0;i<100;i++) { try { const r=await fetch('http://127.0.0.1:3005/api/messages',{headers:{Origin:'https://127.0.0.1:5175'}}); if(r.ok) break; } catch {} await new Promise(r=>setTimeout(r,100)); }
  const identity=await request('https://127.0.0.1:5175/.well-known/palaco-app.json'); assert.equal(identity.status,200); assert.equal(JSON.parse(identity.body).appId,'bastion');
  pageBrowser=await chromium.launch({headless:true,...(browserExecutable ? { executablePath: browserExecutable } : {})});
  const context=await pageBrowser.newContext({ignoreHTTPSErrors:true}); const page=await context.newPage(); const response=await page.goto('https://127.0.0.1:5175/'); assert.equal(response.status(),200);
  page.on('console', message => { log += `PAGE ${message.type()}: ${message.text()}\n`; });
  page.on('pageerror', error => { log += `PAGE ERROR: ${error.message}\n`; });
  const secondPage=await context.newPage(); await secondPage.goto('https://127.0.0.1:5175/');
  assert.match(await page.locator('.preview-banner').textContent(),/Taakmutaties blijven gesloten/); assert.match(response.headers()['content-security-policy'],/frame-ancestors 'none'/); assert.equal(response.headers()['x-content-type-options'],'nosniff');
  try { await page.locator('.chat-input button:not([disabled])').waitFor({ timeout: 5000 }); }
  catch { throw new Error(`Socket connection failed. Browser: ${log}\nBackend: ${backendLog}`); }
  await secondPage.locator('.chat-input button:not([disabled])').waitFor();
  const liveMessage=`Browser realtime ${Date.now()}`;
  await page.getByRole('textbox',{name:'Lokaal previewbericht'}).fill(liveMessage);
  await page.locator('.chat-input button').click();
  await secondPage.getByText(liveMessage,{exact:true}).waitFor();
  await secondPage.locator('.log-entry').filter({hasText:'MESSAGE_SENT'}).first().waitFor();
  await page.getByRole('checkbox',{name:'Vervalt na 30s'}).check();
  const expiringMessage=`Browser expiry ${Date.now()}`;
  await page.getByRole('textbox',{name:'Lokaal previewbericht'}).fill(expiringMessage);
  await page.locator('.chat-input button').click();
  await secondPage.getByText(expiringMessage,{exact:true}).waitFor();
  const database=new Database(databasePath);
  const messageId=database.prepare('SELECT id FROM messages WHERE text = ?').get(expiringMessage)?.id;
  assert.ok(messageId,'self-destruct message should be stored in SQLite');
  database.prepare('UPDATE messages SET expires_at = ? WHERE id = ?').run(Date.now()-1,messageId);
  await page.getByText(expiringMessage,{exact:true}).waitFor({state:'detached'});
  await secondPage.getByText(expiringMessage,{exact:true}).waitFor({state:'detached'});
  await secondPage.locator('.log-entry').filter({hasText:'MESSAGE_EXPIRED'}).first().waitFor();
  assert.equal(database.prepare('SELECT id FROM messages WHERE id = ?').get(messageId),undefined);
  database.close();
  const original=await page.locator('.task-card').first().locator('.task-desc').textContent(); await page.locator('.task-card').first().getByRole('button',{name:'Afronden'}).click(); assert.equal(await page.getByRole('dialog').count(),1); await page.getByRole('button',{name:'TOON BLOKKERING'}).click(); await page.getByText(/STORAGE_EFFECT_DEADLINE_UNSUPPORTED/).waitFor(); assert.equal(await page.locator('.task-card').first().locator('.task-desc').textContent(),original); await context.close();
  console.log(JSON.stringify({identity:'bastion',preview:'loaded',securityHeaders:'observed',realtimeChat:'broadcast-to-second-client',selfDestruct:'removed-from-ui-and-sqlite',audit:'database-backed',mutation:'blocked-without-local-write'}));
} finally { await pageBrowser?.close(); child.kill(); backend.kill(); fs.rmSync(testDir,{recursive:true,force:true}); }
