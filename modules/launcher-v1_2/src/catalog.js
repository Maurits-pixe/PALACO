// Preserved from the supplied v1.1 configuration. Inclusion is a local policy,
// not evidence of domain ownership, app operation, or formal approval.
export const CATALOG = Object.freeze([
  Object.freeze({
    id: 'aether', name: 'AETHER', expectedId: 'aether', color: '#00ff9d',
    description: 'Cryptografische versleutelingsmachine.',
    origins: Object.freeze(['https://localhost:5174', 'https://aether.hoofdkantoor.info'])
  }),
  Object.freeze({
    id: 'bastion', name: 'BASTION', expectedId: 'bastion', color: '#60a5fa',
    description: 'Tactisch commandocentrum.',
    origins: Object.freeze(['https://localhost:5175', 'https://bastion.hoofdkantoor.info'])
  }),
  Object.freeze({
    id: '5criptie', name: '5CRIPTIE', expectedId: '5criptie', color: '#c084fc',
    description: 'Monitoringdashboard voor netwerkbeveiliging.',
    origins: Object.freeze(['https://localhost:5176', 'https://5criptie.hoofdkantoor.info'])
  })
]);

export function createModuleStates() {
  return CATALOG.map(({ id, name, color, description, origins }) => ({
    id, name, color, description, placeholder: origins[0], inputUrl: '',
    savedUrl: null, status: 'unconfigured', isValid: false, error: '',
    errorCode: null, isVerifying: false, currentCheckId: null, lastCheck: null
  }));
}
