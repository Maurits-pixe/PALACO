import {readFile,realpath,writeFile} from 'node:fs/promises';
import {resolve,relative,sep} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
import {sha256,encodeDocument,decodeDocument,REPOSITORIES} from './document-exchange.mjs';
const here=fileURLToPath(new URL('.',import.meta.url));
const args=process.argv.slice(2),prepare=args.includes('--prepare');
const workspaceArg=args.find(a=>a.startsWith('--workspace='));
if(!workspaceArg||args.some(a=>a!=='--prepare'&&!a.startsWith('--workspace='))) throw Error('WORKSPACE_ARGUMENT_REQUIRED');
const workspace=await realpath(resolve(workspaceArg.slice('--workspace='.length)));
const lock=JSON.parse(await readFile(new URL('./workspace.lock.json',import.meta.url),'utf8'));
const git=(root,...args)=>execFileSync('git',args,{cwd:root,encoding:'utf8',maxBuffer:1024*1024}).trim();
const blob=(root,revision,path)=>execFileSync('git',['show',`${revision}:${path}`],{cwd:root,maxBuffer:1024*1024});
const codec=await readFile(new URL('./document-exchange.mjs',import.meta.url));
assert.equal(await sha256(codec),lock.codecSha256);
assert.equal(lock.schema,'PALACO_ECOSYSTEM_WORKSPACE_V1');assert.equal(lock.participants.length,6);
assert.deepEqual([...lock.participants.map(p=>p.repository)].sort(),[...REPOSITORIES].sort());
const modules=new Map(), roots=new Map(), cases=[];
for(const item of lock.participants) {
 assert.match(item.folder,/^[A-Za-z0-9_-]+$/);assert.match(item.sourceCommit,/^[a-f0-9]{40}$/);
 const root=await realpath(resolve(workspace,item.folder)),rel=relative(workspace,root);
 assert.ok(rel&&!rel.startsWith('..'+sep)&&rel!=='..'&&!rel.startsWith(sep));
 assert.equal(git(root,'remote','get-url','origin').replace(/\.git$/,''),`https://github.com/${item.repository}`);
 const revision=item.revision==='SELF'?git(root,'rev-parse','HEAD'):item.revision;
 assert.match(revision,/^[a-f0-9]{40}$/);assert.equal(git(root,'rev-parse','HEAD'),revision);
 assert.equal(git(root,'rev-parse',`${item.sourceCommit}:${item.sourcePath}`),item.sourceBlobSha);
 if(item.mode==='PARTICIPANT') {
   const local=await readFile(resolve(root,'ecosystem/document-exchange.mjs'));
   assert.deepEqual(local,codec);
   for(const path of ['ecosystem/document-exchange.mjs','ecosystem/participant.mjs']) {
     if(!(prepare&&item.revision==='SELF')) assert.deepEqual(await readFile(resolve(root,path)),blob(root,revision,path));
   }
   const record=JSON.parse(await readFile(resolve(root,'ecosystem/integration.json'),'utf8'));
   assert.equal(record.codec_sha256,lock.codecSha256);assert.equal(record.repository,item.repository);
   assert.equal(record.production_release_enabled,false);assert.equal(record.shared_login,false);
   const module=await import(pathToFileURL(resolve(root,'ecosystem/participant.mjs')));
   assert.equal(module.REPOSITORY,item.repository);modules.set(item.repository,module);
 } else {
   assert.equal(item.mode,'UPSTREAM_READ_ONLY');assert.equal(item.repository,'III6V9-Architect/local-qa');
   assert.equal(git(root,'rev-parse',`${revision}:rio/local-qa.mjs`),lock.qaGitBlobSha);
 }
 roots.set(item.repository,root);
 const content=new TextDecoder('utf-8',{fatal:true}).decode(blob(root,item.sourceCommit,item.sourcePath)).split(/\r?\n/).slice(0,12).join('\n').trim();
 assert.ok(content.length>0);
 cases.push({item,document:{documentId:`exchange-${cases.length+1}`,title:`${item.repository} reference`,content,status:'draft'}});
}
const qaRoot=roots.get('III6V9-Architect/local-qa'),qaRevision=lock.participants.find(p=>p.mode==='UPSTREAM_READ_ONLY').revision;
const qa=await import(pathToFileURL(resolve(qaRoot,'rio/local-qa.mjs')));
const qaBytes=blob(qaRoot,qaRevision,'rio/local-qa.mjs');
assert.deepEqual(await readFile(resolve(roots.get('Maurits-pixe/PALACO-Citadel'),'rio/vendor/local-qa.mjs')),qaBytes);
const citadel=modules.get('Maurits-pixe/PALACO-Citadel'),book=modules.get('Maurits-pixe/PALACO-BOOK-1');
const packets=[];
for(const {item,document} of cases) {
 const reference={repository:item.repository,commitSha:item.sourceCommit,path:item.sourcePath};
 const bytes=item.mode==='PARTICIPANT'?await modules.get(item.repository).exportDocument(document,reference):await encodeDocument(reference,document);
 for(const consumer of modules.values()) {
   const result=await consumer.readDocument(bytes);assert.deepEqual(result.document,document);
   assert.equal(result.boundary.operativeAuthority,'NONE');assert.equal(result.boundary.sourceVerified,false);
 }
 const parsed=await decodeDocument(bytes);
 const original=qa.createDocument({...document,origin:parsed.origin});
 const imported=await citadel.readForQa(bytes);assert.deepEqual(imported,original);
 const quote=document.content.split('\n').find(line=>line.trim()).trim();
 assert.deepEqual(await citadel.quoteDocument(bytes,quote),qa.createQuote(original,quote));
 await assert.rejects(citadel.quoteDocument(bytes,'NOT_PRESENT_RANDOM_SYNTHETIC_QUOTE'));
 const draft=await book.knowledgeDraft(bytes,{caseId:'synthetic-local-case',createdAt:'2026-10-19T00:00:00.000Z'});
 assert.equal(draft.knowledge.status,'CONCEPT');assert.equal(draft.knowledge.sources[0].provenance,'UNKNOWN');
 assert.equal(draft.sourceMetadata.verified,false);
 packets.push({repository:item.repository,documentId:document.documentId,base64:Buffer.from(bytes).toString('base64')});
}
const fixture=JSON.stringify({schema:'PALACO_ECOSYSTEM_FIXTURE_V1',packets},null,2)+'\n';
const fixturePath=new URL('../verification/rio-accounts/ecosystem-document-fixture.json',import.meta.url);
if(prepare) await writeFile(fixturePath,fixture);else assert.equal(await readFile(fixturePath,'utf8'),fixture);
console.log(JSON.stringify({schema:'PALACO_ECOSYSTEM_EVIDENCE_V1',status:prepare?'PREPARED':'PASS',
 participants:lock.participants.map(p=>({repository:p.repository,revision:p.revision==='SELF'?git(roots.get(p.repository),'rev-parse','HEAD'):p.revision,sourceCommit:p.sourceCommit,sourceBlobSha:p.sourceBlobSha})),
 codecSha256:lock.codecSha256,documentCases:packets.length,decoderPairs:packets.length*modules.size,
 actualUpstreamQaComparisons:packets.length,bookConceptImports:packets.length,
 productionReleaseEnabled:false,sharedLogin:false,operativeAuthority:'NONE'}));
