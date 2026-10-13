'use strict';
(() => {
    const SCOPE = 'RIO_SYNTHETIC_SESSION_TEST_V1';
    const DRAFT_SCHEMA = 'RIO_LOCAL_DRAFT_V1';
    const MAX_DRAFT_BYTES = 12288;
    const $ = (id) => document.getElementById(id);
    const elements = {
        account: $('account'), accountId: $('account-id'), login: $('start-login'),
        loginInfo: $('login-info'), feedback: $('feedback'), retry: $('retry-session'),
        sessionState: $('session-state'), logout: $('logout'), logoutAll: $('logout-all'),
        consentPanel: $('consent-panel'), consentGuest: $('consent-guest'),
        consentStatus: $('consent-status'), consentForm: $('consent-form'),
        choice: $('consent-choice'), consentSave: $('consent-save'),
        consentRevoke: $('consent-revoke'), consentRefresh: $('consent-refresh'),
        title: $('studio-title'), note: $('studio-note'), import: $('studio-import'),
        export: $('studio-export'), clear: $('studio-clear'), studioFeedback: $('studio-feedback')
    };
    let epoch = 0;
    let receiptRead = 0;
    let phase = 'checking';
    let csrf;
    let currentAccountId;
    let receipt;
    let busy = false;
    let reading = false;
    let pollTimer;
    let idleTimer;
    let absoluteTimer;
    let draft = { title: '', note: '' };
    let importRead = 0;

    const plainObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
    const exactKeys = (value, keys) => plainObject(value)
        && Object.keys(value).length === keys.length
        && keys.every((key) => Object.prototype.hasOwnProperty.call(value, key));
    const closedBoundary = (value) => value.mode === 'SYNTHETIC_ONLY'
        && value.account1 === 'HOLD' && value.accountActive === false
        && value.canOpenContact === false && value.operativeAuthority === 'NONE';

    function showFeedback(message, focus = false) {
        elements.feedback.textContent = message;
        if (focus) elements.feedback.focus();
    }

    function stopChecks() {
        clearTimeout(pollTimer);
        clearTimeout(idleTimer);
        clearTimeout(absoluteTimer);
    }

    function renderControls() {
        const authenticated = phase === 'authenticated' && typeof csrf === 'string';
        const locked = !authenticated || busy;
        elements.account.hidden = !authenticated;
        elements.loginInfo.hidden = authenticated;
        elements.login.hidden = phase !== 'anonymous';
        elements.retry.hidden = phase !== 'unavailable';
        elements.logout.disabled = locked;
        elements.logoutAll.disabled = locked;
        elements.consentPanel.hidden = !authenticated;
        elements.consentGuest.hidden = authenticated;
        elements.choice.disabled = locked || reading || !receipt;
        elements.consentSave.disabled = locked || reading || !receipt || !elements.choice.checked;
        elements.consentRevoke.disabled = locked || reading || !receipt;
        elements.consentRefresh.disabled = locked || reading;
        if (phase === 'authenticated') elements.sessionState.textContent = 'Eigen testsessie';
        if (phase === 'anonymous') elements.sessionState.textContent = 'Nog niet aangemeld';
        if (phase === 'checking') elements.sessionState.textContent = 'Sessie wordt gecontroleerd';
        if (phase === 'unavailable') elements.sessionState.textContent = 'Tijdelijk niet beschikbaar';
    }

    function clearPersonal(nextPhase, message, focus = false) {
        epoch += 1;
        receiptRead += 1;
        stopChecks();
        csrf = undefined;
        currentAccountId = undefined;
        receipt = undefined;
        busy = false;
        reading = false;
        const active = document.activeElement;
        const protectedFocus = elements.account.contains(active) || elements.consentPanel.contains(active)
            || active === elements.login || active === elements.retry;
        phase = nextPhase;
        elements.accountId.textContent = '';
        elements.choice.checked = false;
        elements.consentStatus.textContent = '';
        renderControls();
        showFeedback(message, focus && protectedFocus);
    }

    function unavailable(message = 'RIO is tijdelijk niet beschikbaar. Controleer je testsessie opnieuw.') {
        clearPersonal('unavailable', message, true);
    }

    function sessionExpired() {
        clearPersonal('anonymous', 'De testsessie is verlopen of niet meer beschikbaar. Meld je opnieuw aan.', true);
    }

    function responseFailure(response) {
        if (response.status === 401) sessionExpired();
        else if (response.status === 503) unavailable();
        else unavailable('De testsessie kon niet veilig worden gecontroleerd. Probeer opnieuw.');
    }

    async function request(path, options = {}) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 8000);
        try {
            return await fetch(path, {
                credentials: 'same-origin', cache: 'no-store', redirect: 'error',
                ...options, signal: controller.signal
            });
        } finally {
            clearTimeout(timeout);
        }
    }

    async function readJson(response) {
        const type = response.headers.get('content-type') || '';
        if (!type.toLowerCase().startsWith('application/json')) throw new Error('invalid response');
        const content = await response.text();
        if (content.length > 16384) throw new Error('oversized response');
        return JSON.parse(content);
    }

    function validMe(me) {
        return exactKeys(me, [
            'accountId', 'csrfToken', 'actorKind', 'credentialControl', 'accountActive',
            'mode', 'operativeAuthority', 'canOpenContact', 'account1'
        ]) && closedBoundary(me)
            && (me.accountId === 'TST-alpha' || me.accountId === 'TST-beta')
            && me.actorKind === 'SYNTHETIC_DEV_ACTOR'
            && me.credentialControl === 'VERIFIED_DEV_OIDC'
            && typeof me.csrfToken === 'string' && /^[A-Za-z0-9_-]{32,128}$/.test(me.csrfToken);
    }

    function validatedReceipt(envelope) {
        if (!exactKeys(envelope, [
            'receipt', 'mode', 'account1', 'accountActive', 'canOpenContact', 'operativeAuthority'
        ]) || !closedBoundary(envelope)) throw new Error('invalid receipt boundary');
        const value = envelope.receipt;
        if (!exactKeys(value, ['scope', 'granted', 'revision', 'expiresAt'])
            || value.scope !== SCOPE || typeof value.granted !== 'boolean'
            || !Number.isSafeInteger(value.revision) || value.revision < 0
            || !(value.expiresAt === null || (Number.isSafeInteger(value.expiresAt) && value.expiresAt > 0))
            || (value.granted && value.expiresAt === null)) throw new Error('invalid receipt');
        return { scope: SCOPE, granted: value.granted, revision: value.revision, expiresAt: value.expiresAt };
    }

    function armIdleDeadline() {
        clearTimeout(idleTimer);
        idleTimer = setTimeout(sessionExpired, 30000);
    }

    function scheduleCheck() {
        clearTimeout(pollTimer);
        if (phase === 'authenticated') pollTimer = setTimeout(checkSession, 10000);
    }

    async function checkSession() {
        if (phase !== 'authenticated') return;
        if (busy || reading) {
            scheduleCheck();
            return;
        }
        const stamp = epoch;
        try {
            const response = await request('/api/me');
            if (stamp !== epoch) return;
            if (!response.ok) {
                responseFailure(response);
                return;
            }
            const me = await readJson(response);
            if (stamp !== epoch) return;
            if (!validMe(me) || me.accountId !== currentAccountId || me.csrfToken !== csrf) {
                unavailable('De testsessie is gewijzigd. Controleer je eigen account opnieuw.');
                return;
            }
            armIdleDeadline();
            scheduleCheck();
        } catch {
            if (stamp === epoch) unavailable();
        }
    }

    async function refreshConsent(message = '', focus = false) {
        if (phase !== 'authenticated' || busy || reading) return;
        const stamp = epoch;
        const round = ++receiptRead;
        receipt = undefined;
        elements.choice.checked = false;
        reading = true;
        elements.consentStatus.textContent = 'Toestemming wordt gecontroleerd.';
        renderControls();
        try {
            const response = await request('/api/consent');
            if (stamp !== epoch || round !== receiptRead) return;
            if (!response.ok) {
                responseFailure(response);
                return;
            }
            const value = validatedReceipt(await readJson(response));
            if (stamp !== epoch || round !== receiptRead) return;
            receipt = value;
            reading = false;
            elements.consentStatus.textContent = value.granted
                ? 'Je toestemming is actief voor deze oefensessie.'
                : 'Je hebt geen actieve toestemming voor deze oefensessie.';
            renderControls();
            if (message) showFeedback(message, focus);
        } catch {
            if (stamp === epoch && round === receiptRead) unavailable();
        }
    }

    async function loadAccount() {
        clearPersonal('checking', '');
        const stamp = epoch;
        try {
            const response = await request('/api/me');
            if (stamp !== epoch) return;
            if (response.status === 401) {
                clearPersonal('anonymous', '');
                return;
            }
            if (!response.ok) {
                responseFailure(response);
                return;
            }
            const me = await readJson(response);
            if (stamp !== epoch) return;
            if (!validMe(me)) throw new Error('invalid account response');
            csrf = me.csrfToken;
            currentAccountId = me.accountId;
            elements.accountId.textContent = me.accountId;
            phase = 'authenticated';
            renderControls();
            armIdleDeadline();
            absoluteTimer = setTimeout(sessionExpired, 60000);
            scheduleCheck();
            await refreshConsent();
        } catch {
            if (stamp === epoch) unavailable();
        }
    }

    async function changeConsent(granted) {
        if (phase !== 'authenticated' || busy || reading || !receipt
            || (granted && !elements.choice.checked)) return;
        const stamp = epoch;
        const revision = receipt.revision;
        busy = true;
        elements.choice.checked = false;
        renderControls();
        showFeedback(granted ? 'Je keuze wordt gecontroleerd.' : 'Je toestemming wordt ingetrokken.');
        try {
            const response = await request('/api/consent', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
                body: JSON.stringify({ scope: SCOPE, granted, revision })
            });
            if (stamp !== epoch) return;
            if (response.status === 409) {
                busy = false;
                await refreshConsent('De keuze is intussen gewijzigd. Bekijk de huidige keuze en kies opnieuw.', true);
                return;
            }
            if (!response.ok) {
                responseFailure(response);
                return;
            }
            const value = validatedReceipt(await readJson(response));
            if (stamp !== epoch) return;
            if (value.granted !== granted || value.revision <= revision) throw new Error('unconfirmed choice');
            receipt = value;
            busy = false;
            elements.consentStatus.textContent = value.granted
                ? 'Je toestemming is actief voor deze oefensessie.'
                : 'Je hebt geen actieve toestemming voor deze oefensessie.';
            renderControls();
            showFeedback(value.granted
                ? 'Je toestemming voor deze oefensessie is bevestigd. Persoonlijke toegang blijft gesloten.'
                : 'Je toestemming is ingetrokken. Persoonlijke toegang blijft gesloten.', true);
        } catch {
            if (stamp === epoch) unavailable('De uitkomst is nog niet bevestigd. Controleer je testsessie en de huidige toestemming opnieuw.');
        }
    }

    async function logout(all) {
        if (phase !== 'authenticated' || busy) return;
        const stamp = epoch;
        busy = true;
        renderControls();
        try {
            const response = await request(all ? '/auth/logout-all' : '/auth/logout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: '{}'
            });
            if (stamp !== epoch) return;
            if (!response.ok) {
                responseFailure(response);
                return;
            }
            const value = await readJson(response);
            if (stamp !== epoch) return;
            if (value.loggedOut !== true || value.mode !== 'SYNTHETIC_ONLY'
                || value.providerLogout !== 'NOT_REQUESTED') throw new Error('unconfirmed logout');
            clearPersonal('anonymous', 'Lokale testsessie afgemeld. De identity-provider heeft een afzonderlijke sessie.', true);
        } catch {
            if (stamp === epoch) unavailable('Afmelden kon niet worden bevestigd. Controleer je testsessie opnieuw.');
        }
    }

    function validDraftText(value, maximum) {
        return typeof value === 'string' && value.length <= maximum
            && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value);
    }

    function canonicalDraft(value) {
        if (!exactKeys(value, ['schema', 'verification', 'authority', 'draft'])
            || value.schema !== DRAFT_SCHEMA || value.verification !== 'UNVERIFIED'
            || !exactKeys(value.authority, ['accountActive', 'canOpenContact', 'operativeAuthority', 'consentGranted'])
            || value.authority.accountActive !== false || value.authority.canOpenContact !== false
            || value.authority.operativeAuthority !== 'NONE' || value.authority.consentGranted !== false
            || !exactKeys(value.draft, ['title', 'note'])
            || !validDraftText(value.draft.title, 80) || !validDraftText(value.draft.note, 2000)) {
            throw new Error('invalid local draft');
        }
        return { title: value.draft.title, note: value.draft.note };
    }

    function draftEnvelope(value) {
        if (!validDraftText(value.title, 80) || !validDraftText(value.note, 2000)) throw new Error('invalid draft');
        return {
            schema: DRAFT_SCHEMA, verification: 'UNVERIFIED',
            authority: { accountActive: false, canOpenContact: false, operativeAuthority: 'NONE', consentGranted: false },
            draft: { title: value.title, note: value.note }
        };
    }

    function studioFeedback(message, focus = false) {
        elements.studioFeedback.textContent = message;
        if (focus) elements.studioFeedback.focus();
    }

    function readDraftFields() {
        draft = { title: elements.title.value, note: elements.note.value };
        return draft;
    }

    function clearDraft(message = '') {
        importRead += 1;
        draft = { title: '', note: '' };
        elements.title.value = '';
        elements.note.value = '';
        elements.import.value = '';
        studioFeedback(message);
    }

    function updateDraftFields() {
        importRead += 1;
        readDraftFields();
    }
    elements.title.addEventListener('input', updateDraftFields);
    elements.note.addEventListener('input', updateDraftFields);

    elements.export.addEventListener('click', () => {
        let objectUrl;
        let link;
        try {
            const content = JSON.stringify(draftEnvelope(readDraftFields()), null, 2) + '\n';
            if (new TextEncoder().encode(content).byteLength > MAX_DRAFT_BYTES) throw new Error('oversized draft');
            objectUrl = URL.createObjectURL(new Blob([content], { type: 'application/json' }));
            link = document.createElement('a');
            link.href = objectUrl;
            link.download = 'rio-lokaal-concept.json';
            link.hidden = true;
            document.body.append(link);
            link.click();
            studioFeedback('Het lokale conceptbestand is klaargezet. Het blijft niet geverifieerd en bevat geen account of toestemming.');
        } catch {
            studioFeedback('Het concept kon niet worden bewaard. Controleer de titel en notitie.', true);
        } finally {
            if (link) link.remove();
            if (objectUrl) setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
        }
    });

    elements.import.addEventListener('change', async () => {
        const file = elements.import.files && elements.import.files[0];
        const round = ++importRead;
        elements.import.value = '';
        if (!file) return;
        try {
            if (file.size > MAX_DRAFT_BYTES || file.size === 0) throw new Error('invalid file size');
            const content = await file.text();
            if (new TextEncoder().encode(content).byteLength > MAX_DRAFT_BYTES) throw new Error('oversized draft');
            const value = canonicalDraft(JSON.parse(content));
            if (round !== importRead) return;
            draft = value;
            elements.title.value = value.title;
            elements.note.value = value.note;
            studioFeedback('Concept geopend, alleen in deze pagina. Het is niet geverifieerd. Je account en toestemming zijn niet gewijzigd.', true);
        } catch {
            if (round === importRead) studioFeedback('Dit is geen geldig lokaal conceptbestand. Er is niets gewijzigd.', true);
        }
    });

    elements.clear.addEventListener('click', () => {
        clearDraft('Je lokale concept is gewist.');
        elements.title.focus();
    });
    elements.choice.addEventListener('change', renderControls);
    elements.consentForm.addEventListener('submit', (event) => {
        event.preventDefault();
        void changeConsent(true);
    });
    elements.consentRevoke.addEventListener('click', () => { void changeConsent(false); });
    elements.consentRefresh.addEventListener('click', () => { void refreshConsent('De huidige keuze is opnieuw gecontroleerd.'); });
    elements.logout.addEventListener('click', () => { void logout(false); });
    elements.logoutAll.addEventListener('click', () => { void logout(true); });
    elements.retry.addEventListener('click', () => { void loadAccount(); });
    window.addEventListener('pagehide', () => {
        clearPersonal('anonymous', '');
        clearDraft();
    });
    window.addEventListener('pageshow', (event) => {
        if (event.persisted) void loadAccount();
    });
    void loadAccount();
})();
