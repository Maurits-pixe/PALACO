// Native-catalog adapter for the original private PALACO Hoofdkantoor Site.
// Pure functions: no network, DOM mutations, user/session data or deployment.
export const TILE_ID = 'palaco-phone-testlab';
export const LANGUAGE_CODES = Object.freeze(['nl','en','de','fr','es','it','pt','ru','eo','pl','ar','zh']);

const translations = Object.freeze({
  nl: ['PALACO Phone — Testlab','Lokale browsertest geslaagd','Productie geblokkeerd','Open lokale app','Broncode','Testbewijzen','Alleen dit apparaat; start eerst de lokale server'],
  en: ['PALACO Phone — Test Lab','Local browser test passed','Production on hold','Open local app','Source code','Test evidence','This device only; start the local server first'],
  de: ['PALACO Phone — Testlabor','Lokaler Browsertest bestanden','Produktion gesperrt','Lokale App öffnen','Quellcode','Testnachweise','Nur dieses Gerät; zuerst den lokalen Server starten'],
  fr: ['PALACO Phone — Laboratoire','Test local du navigateur réussi','Production bloquée','Ouvrir l’application locale','Code source','Preuves de test','Sur cet appareil uniquement ; démarrez le serveur local'],
  es: ['PALACO Phone — Laboratorio','Prueba local del navegador superada','Producción bloqueada','Abrir aplicación local','Código fuente','Pruebas','Solo en este dispositivo; inicia el servidor local'],
  it: ['PALACO Phone — Laboratorio','Test locale del browser superato','Produzione bloccata','Apri app locale','Codice sorgente','Prove di test','Solo su questo dispositivo; avvia il server locale'],
  pt: ['PALACO Phone — Laboratório','Teste local do navegador aprovado','Produção bloqueada','Abrir aplicação local','Código-fonte','Evidências de teste','Apenas neste dispositivo; inicie o servidor local'],
  ru: ['PALACO Phone — Лаборатория','Локальный браузерный тест пройден','Продакшен заблокирован','Открыть локальное приложение','Исходный код','Результаты теста','Только на этом устройстве; запустите локальный сервер'],
  eo: ['PALACO Phone — Testejo','Loka retumila testo sukcesis','Produktado blokita','Malfermi lokan aplikaĵon','Fontkodo','Testpruvoj','Nur en ĉi tiu aparato; unue lanĉu la lokan servilon'],
  pl: ['PALACO Phone — Laboratorium','Lokalny test przeglądarki zaliczony','Produkcja zablokowana','Otwórz aplikację lokalną','Kod źródłowy','Dowody testów','Tylko na tym urządzeniu; uruchom serwer lokalny'],
  ar: ['PALACO Phone — مختبر الاختبار','نجح اختبار المتصفح المحلي','الإنتاج معلّق','فتح التطبيق المحلي','الشيفرة المصدرية','أدلة الاختبار','على هذا الجهاز فقط؛ شغّل الخادم المحلي أولاً'],
  zh: ['PALACO Phone — 测试实验室','本地浏览器测试通过','生产环境暂缓','打开本地应用','源代码','测试证据','仅限本设备；请先启动本地服务器']
});
export function phoneTileForLanguage(language = 'nl') {
  const code = LANGUAGE_CODES.includes(language) ? language : 'nl';
  const [name,proof,hold,localLabel,sourceLabel,evidenceLabel,localNote] = translations[code];
  return Object.freeze({
    id: TILE_ID, order: 15, name, visibility:'private', type:'testlab',
    status: 'LOCAL_BROWSER_CI_PASS', production: 'HOLD',
    statusLabel: proof, productionLabel: hold,
    sourceEvidence: Object.freeze({runId:41620060773,commit:'81e4dd22c672e09bc3624573331001c88618aa61'}),
    links: Object.freeze([
      Object.freeze({id:'local',label:localLabel,href:'http://127.0.0.1:8765/',note:localNote,external:false}),
      Object.freeze({id:'source',label:sourceLabel,href:'https://github.com/Maurits-pixe/palaco-pp',external:true}),
      Object.freeze({id:'evidence',label:evidenceLabel,href:'https://github.com/Maurits-pixe/palaco-pp/pull/2',external:true})
    ])
  });
}
// Call this once in the original Site's single source-of-truth app catalog,
// *before* the native search/favorites/count pipeline runs. Keep original entries.
export function appendPhoneTestlab(existingTiles, language = 'nl') {
  if (!Array.isArray(existingTiles)) throw new TypeError('Expected a catalog array');
  if (existingTiles.some(tile => tile?.id === TILE_ID)) throw new Error('Duplicate P.P. testlab tile');
  if (existingTiles.length !== 14) throw new Error('Expected 14 original entries; review Site version before integrating');
  if (!existingTiles.some(tile => /palaco.phone/i.test(String(tile?.name ?? '')))) {
    throw new Error('Original PALACO PHONE tile missing; fail closed');
  }
  const ids=existingTiles.map(tile=>tile?.id);
  if (new Set(ids).size !== ids.length) throw new Error('Existing catalog contains duplicate IDs');
  return [...existingTiles, phoneTileForLanguage(language)];
}
