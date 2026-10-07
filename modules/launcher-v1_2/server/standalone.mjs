import { createGuardServer } from './mutation-guard.mjs';

// Local only. An ephemeral port avoids taking over an existing application.
const server = createGuardServer();
server.listen(0, '127.0.0.1', () => {
  console.log(JSON.stringify({
    status: 'LOCAL_GUARD_ONLY',
    url: `http://127.0.0.1:${server.address().port}`,
    code: 'STORAGE_EFFECT_DEADLINE_UNSUPPORTED',
  }));
});
