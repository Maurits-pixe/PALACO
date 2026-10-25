(function (root) {
  'use strict';

  const services = Object.freeze({
    care: 'Care & wellbeing',
    maintenance: 'Maintenance',
    guide: 'Citadel guide'
  });

  function create() {
    let state = { phase: 'READY', service: null };

    function snapshot() {
      return Object.freeze({...state});
    }

    function prepare(serviceId) {
      if (state.phase !== 'READY' || !Object.hasOwn(services, serviceId)) {
        return Object.freeze({ok: false, state: snapshot()});
      }
      state = {phase: 'PREPARED', service: services[serviceId]};
      return Object.freeze({ok: true, state: snapshot()});
    }

    function showReviewBoundary() {
      if (state.phase !== 'PREPARED') return Object.freeze({ok: false, state: snapshot()});
      state = {...state, phase: 'REVIEW_BOUNDARY'};
      return Object.freeze({ok: true, state: snapshot()});
    }

    function close() {
      if (state.phase !== 'REVIEW_BOUNDARY') return Object.freeze({ok: false, state: snapshot()});
      state = {...state, phase: 'CLOSED'};
      return Object.freeze({ok: true, state: snapshot()});
    }

    function reset() {
      state = {phase: 'READY', service: null};
      return snapshot();
    }

    return Object.freeze({snapshot, prepare, showReviewBoundary, close, reset});
  }

  root.PalacoHaraDemoRuntime = Object.freeze({create});
})(window);
