export const metrics = Object.freeze([
  Object.freeze({ id: 'events', label: 'Signalen', value: '1.284', change: '+4,2%', tone: 'cyan' }),
  Object.freeze({ id: 'review', label: 'In beoordeling', value: '03', change: '2 hoog', tone: 'amber' }),
  Object.freeze({ id: 'sources', label: 'Bronnen', value: '12', change: 'fixtures', tone: 'violet' }),
  Object.freeze({ id: 'coverage', label: 'Dekking', value: '96,4%', change: 'demo-indicator', tone: 'green' })
]);

export const events = Object.freeze([
  Object.freeze({ id: 'EVT-1042', time: '14:32:08', source: 'edge-fixture-03', category: 'Verkeer', severity: 'Laag', summary: 'Voorbeeldpatroon binnen normaal fixture-profiel.', status: 'Gesloten' }),
  Object.freeze({ id: 'EVT-1041', time: '14:29:51', source: 'identity-fixture-01', category: 'Identiteit', severity: 'Hoog', summary: 'Synthetische reviewmelding; geen account is gecontroleerd.', status: 'Review' }),
  Object.freeze({ id: 'EVT-1040', time: '14:24:13', source: 'api-fixture-02', category: 'API', severity: 'Middel', summary: 'Voorbeeld van een afwijkende frequentieverdeling.', status: 'Review' }),
  Object.freeze({ id: 'EVT-1039', time: '14:18:46', source: 'edge-fixture-01', category: 'Verkeer', severity: 'Laag', summary: 'Voorbeeldheartbeat uit vaste demodata.', status: 'Gesloten' }),
  Object.freeze({ id: 'EVT-1038', time: '14:11:20', source: 'policy-fixture-04', category: 'Beleid', severity: 'Hoog', summary: 'Synthetische policy-waarschuwing voor interface-demo.', status: 'Review' }),
  Object.freeze({ id: 'EVT-1037', time: '14:06:02', source: 'api-fixture-01', category: 'API', severity: 'Laag', summary: 'Voorbeeldrequest binnen de vaste fixtureset.', status: 'Gesloten' })
]);

export const reviewBreakdown = Object.freeze(
  ['Hoog', 'Middel', 'Laag'].map(severity => Object.freeze({
    severity,
    count: events.filter(event => event.status === 'Review' && event.severity === severity).length
  }))
);

export function reviewBreakdownLabel(items, total) {
  if (total === 0) return 'Geen openstaande reviewmeldingen.';
  return items.map(item => `${item.severity}: ${item.count} ${item.count === 1 ? 'reviewmelding' : 'reviewmeldingen'}, ${Math.round(item.count / total * 100)}%`).join('. ');
}

export function reviewSummaryLabel(total) {
  if (total === 0) return 'Geen reviewmeldingen';
  return `${total} ${total === 1 ? 'reviewmelding' : 'reviewmeldingen'}`;
}

export const trafficSamples = Object.freeze([
  Object.freeze({ time: '14:00', value: 28 }),
  Object.freeze({ time: '14:05', value: 38 }),
  Object.freeze({ time: '14:10', value: 32 }),
  Object.freeze({ time: '14:15', value: 55 }),
  Object.freeze({ time: '14:20', value: 42 }),
  Object.freeze({ time: '14:25', value: 66 }),
  Object.freeze({ time: '14:30', value: 48 }),
  Object.freeze({ time: '14:35', value: 74 }),
  Object.freeze({ time: '14:40', value: 61 }),
  Object.freeze({ time: '14:45', value: 83 }),
  Object.freeze({ time: '14:50', value: 58 }),
  Object.freeze({ time: '14:55', value: 70 })
]);
