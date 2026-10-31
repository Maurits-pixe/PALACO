import Ajv2020 from 'ajv/dist/2020.js';
import schema from '../../../schemas/world-design-manifest.schema.json' with { type: 'json' };

export const EXPECTED_WORLD_ID = 'WORLD-EVA-001';

const ajv = new Ajv2020({ allErrors: true, strict: true });
const validateSchema = ajv.compile(schema);
const expectedStructure = ['HORIZON', 'GATE', 'RING', 'FOUR_REGIONS', 'CORE'];
const expectedRegions = ['MEMORY', 'CREATION', 'LIFE', 'PROOF'];
const expectedLandmarks = [
  'THE_HORIZON',
  'THE_GATE',
  'THE_RING',
  'THE_GARDENS',
  'THE_ATELIER',
  'THE_ARCHIVE',
  'THE_CORE',
];

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function validateWorldManifest(manifest) {
  if (!isRecord(manifest)) {
    return { state: 'INVALID', issues: ['Manifest is not an object.'] };
  }

  if (!validateSchema(manifest)) {
    const errors = validateSchema.errors ?? [];
    return {
      state: errors.some(error => error.keyword === 'required') ? 'INCOMPLETE' : 'INVALID',
      issues: errors.map(error => `${error.instancePath || '/'}: ${error.message}`),
    };
  }

  if (manifest.world.id !== EXPECTED_WORLD_ID) {
    return { state: 'CONFLICT', issues: [`Expected ${EXPECTED_WORLD_ID}; received ${manifest.world.id}.`] };
  }

  if (manifest.world.name !== 'EVA' || manifest.world.class !== 'PALACO_WORLD' ||
      manifest.citadel.binding_id !== 'LA-001' ||
      manifest.citadel.constitutional_reference !== 'EVA-LA-001') {
    return { state: 'CONFLICT', issues: ['World identity differs from the EVA fixture contract.'] };
  }

  if (manifest.object_type !== 'world_design_manifest' ||
      manifest.engine.id !== 'OR6IT' ||
      manifest.engine.authority !== 'NON_AUTHORITATIVE' ||
      manifest.engine.may_activate_world !== false ||
      manifest.engine.may_execute_external_effects !== false ||
      manifest.lifecycle.execution_state !== 'NOT_AUTHORIZED' ||
      manifest.visual_reference.constitutional_authority !== false ||
      manifest.visual_reference.type !== 'CONCEPT_DESIGN_REFERENCE') {
    return { state: 'INVALID', issues: ['Manifest violates the read-only design boundary.'] };
  }

  const sequenceMatches = Array.isArray(manifest.structure.sequence) &&
    manifest.structure.sequence.length === expectedStructure.length &&
    manifest.structure.sequence.every((value, index) => value === expectedStructure[index]);
  const regionsMatch = Array.isArray(manifest.structure.regions) &&
    manifest.structure.regions.length === expectedRegions.length &&
    manifest.structure.regions.every((region, index) => region?.id === expectedRegions[index]);
  const landmarksValid = Array.isArray(manifest.structure.landmarks) &&
    manifest.structure.landmarks.length === expectedLandmarks.length &&
    manifest.structure.landmarks.every((landmark, index) => landmark.id === expectedLandmarks[index]);

  if (!sequenceMatches || !regionsMatch || !landmarksValid) {
    return { state: 'INVALID', issues: ['EVA structure does not match the required ordered fixture.'] };
  }

  const ids = [
    ...manifest.structure.regions.map(region => region.id),
    ...manifest.structure.landmarks.map(landmark => landmark.id),
  ];
  if (new Set(ids).size !== ids.length) {
    return { state: 'INVALID', issues: ['Duplicate region or landmark IDs are not allowed.'] };
  }

  if (manifest.lifecycle.design_state !== 'DESIGN_DRAFT' ||
      manifest.status !== 'DESIGN_DRAFT' ||
      manifest.provenance.evidence_state !== 'DESIGN_EVIDENCE_ONLY' ||
      manifest.provenance.validation_state !== 'UNVALIDATED') {
    return { state: 'INVALID', issues: ['Fixture lifecycle or provenance claims exceed design-only status.'] };
  }

  return { state: 'STRUCTURALLY_VALID', issues: [] };
}

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (!isRecord(value)) return value;
  return Object.fromEntries(
    Object.keys(value).sort().map(key => [key, sortKeys(value[key])]),
  );
}

export function normalizeWorldManifest(manifest) {
  return JSON.stringify(sortKeys(manifest));
}

export function applyFixtureEvent(readModel, event) {
  if (!Number.isSafeInteger(event?.sequence) || typeof event?.eventType !== 'string') {
    return { ...readModel, transportState: 'INVALID', issues: ['Fixture event is malformed.'] };
  }

  if (event.sequence <= readModel.sequence) {
    return { ...readModel, transportState: 'DUPLICATE', issues: ['Repeated fixture event was ignored.'] };
  }

  if (event.sequence !== readModel.sequence + 1) {
    return { ...readModel, transportState: 'CONFLICT', issues: ['Fixture event sequence has a gap.'] };
  }

  return {
    ...readModel,
    sequence: event.sequence,
    validationState: event.validationState,
    traceRef: event.traceRef,
    transportState: 'SYNTHETIC_FIXTURE',
    issues: [],
    events: [...readModel.events, event],
  };
}
