import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync, spawn } from 'node:child_process';
import { chromium } from '../../launcher-candidate/node_modules/playwright/index.mjs';
import https from 'node:https';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const certDir = path.join(root, 'certs'); fs.mkdirSync(certDir, { recursive: true });
const configPath = path.join(certDir, 'openssl.cnf'); fs.writeFileSync(configPath, '[req]\ndistinguished_name = dn\n[dn]\n');
const run = args => execFileSync('C:/Strawberry/c/bin/openssl.exe', args, { cwd: certDir, env: { ...process.env, OPENSSL_CONF: configPath }, stdio: 'pipe' });
run(['req','-x509','-newkey','rsa:2048','-nodes','-keyout','ca-key.pem','-out','ca.pem','-days','1','-subj','/CN=Bastion preview CA','-addext','basicConstraints=critical,CA:TRUE']);
run(['req','-new','-newkey','rsa:2048','-nodes','-keyout','localhost-key.pem','-out','localhost.csr','-subj','/CN=localhost']);
fs.writeFileSync(path.join(certDir,'ext.cnf'),'subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\n');
run(['x509','-req','-in','localhost.csr','-CA','ca.pem','-CAkey','ca-key.pem','-CAcreateserial','-out','localhost.pem','-days','1','-extfile','ext.cnf']);
const child = spawn(process.execPath, ['node_modules/vite/bin/vite.js','preview','--configLoader','native'], { cwd: root, stdio: ['ignore','pipe','pipe'] });
let log=''; child.stdout.on('data', d => { log += d; }); child.stderr.on('data', d => { log += d; });
const request = (url, opts={}) => new Promise((resolve,reject) => { const req=https.get(url,{...opts,rejectUnauthorized:false},res=>{const chunks=[];res.on('data',c=>chunks.push(c));res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks).toString()}));});req.on('error',reject); });
try {
  for (let i=0;i<100;i++) { try { const r=await request('https://127.0.0.1:5175/'); if(r.status===200) break; } catch {} await new Promise(r=>setTimeout(r,100)); }
  const identity=await request('https://127.0.0.1:5175/.well-known/palaco-app.json'); assert.equal(identity.status,200); assert.equal(JSON.parse(identity.body).appId,'bastion');
  const pageBrowser=await chromium.launch({headless:true,executablePath:'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'});
  const context=await pageBrowser.newContext({ignoreHTTPSErrors:true}); const page=await context.newPage(); const response=await page.goto('https://127.0.0.1:5175/'); assert.equal(response.status(),200);
  assert.match(await page.locator('.preview-banner').textContent(),/Mutaties zijn gesloten/); assert.match(response.headers()['content-security-policy'],/frame-ancestors 'none'/); assert.equal(response.headers()['x-content-type-options'],'nosniff');
  const original=await page.locator('.task-card').first().locator('.task-desc').textContent(); await page.locator('.task-card').first().getByRole('button',{name:'Afronden'}).click(); assert.equal(await page.getByRole('dialog').count(),1); await page.getByRole('button',{name:'TOON BLOKKERING'}).click(); assert.match(await page.locator('.blocked-banner').textContent(),/STORAGE_EFFECT_DEADLINE_UNSUPPORTED/); assert.equal(await page.locator('.task-card').first().locator('.task-desc').textContent(),original); await context.close(); await pageBrowser.close();
  console.log(JSON.stringify({identity:'bastion',preview:'loaded',securityHeaders:'observed',mutation:'blocked-without-local-write'}));
} finally { child.kill(); }
