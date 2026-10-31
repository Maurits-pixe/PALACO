export const snapshot = Object.freeze({
  project: 'OR6IT',
  worldId: 'WORLD-EVA-001',
  snapshotId: 'DEMO-FIXTURE-0042',
  capturedAt: '2025-01-15T12:00:00.000Z',
  mode: 'SYNTHETIC / NOT LIVE',
});

export const indicators = Object.freeze([
  Object.freeze({ label: 'Orbital altitude', value: '412', unit: 'km', note: 'illustrative' }),
  Object.freeze({ label: 'Habitat pressure', value: '101.3', unit: 'kPa', note: 'illustrative' }),
  Object.freeze({ label: 'Thermal balance', value: '21.8', unit: '°C', note: 'illustrative' }),
  Object.freeze({ label: 'Power reserve', value: '78', unit: '%', note: 'illustrative' }),
]);

export const events = Object.freeze([
  Object.freeze({ time: 'T+00:00', title: 'Preview frame initialized', detail: 'Synthetic fixture loaded locally.' }),
  Object.freeze({ time: 'T+00:12', title: 'Orbit marker positioned', detail: 'Illustrative 2D placement; not a measured orbit.' }),
  Object.freeze({ time: 'T+00:28', title: 'Scenario note added', detail: 'Static sample event for interface review.' }),
]);
