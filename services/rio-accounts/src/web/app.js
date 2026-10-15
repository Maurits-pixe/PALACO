'use strict';
(() => {
    const SCOPE = 'RIO_SYNTHETIC_SESSION_TEST_V1';
    const DRAFT_SCHEMA = 'RIO_LOCAL_DRAFT_V1';
    const MAX_DRAFT_BYTES = 12288;
    const $ = (id) => document.getElementById(id);
    const elements = {
        account: $('account'), accountId: $('account-id'), login: $('start-login'), loginDetail: $('login-stage-detail'),
        loginInfo: $('login-info'), feedback: $('feedback'), retry: $('retry-session'),
        sessionState: $('session-state'), logout: $('logout'), logoutAll: $('logout-all'),
        consentPanel: $('consent-panel'), consentGuest: $('consent-guest'),
        consentStatus: $('consent-status'), consentForm: $('consent-form'),
        choice: $('consent-choice'), consentSave: $('consent-save'),
        consentRevoke: $('consent-revoke'), consentRefresh: $('consent-refresh'),
        title: $('studio-title'), note: $('studio-note'), import: $('studio-import'),
        export: $('studio-export'), clear: $('studio-clear'), studioFeedback: $('studio-feedback'),
        titleCount: $('studio-title-count'), noteCount: $('studio-note-count'),
        previewTitle: $('studio-preview-title'), previewNote: $('studio-preview-note'),
        draftState: $('studio-draft-state')
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
    let receiptTimer;
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
        clearTimeout(receiptTimer);
    }

    function renderControls() {
        const nextStep = {
            checking: 'Even wachten. Je testsessie wordt gecontroleerd.',
            anonymous: 'Begin met aanmelden. Daarna zie je je eigen proefaccount.',
            authenticated: 'Je eigen testsessie is zichtbaar. Bekijk nu jouw keuze voor deze oefensessie.',
            unavailable: 'De controle is niet afgerond. Kies Opnieuw controleren zodra de verbinding terug is.'
        };
        if (elements.loginDetail) elements.loginDetail.textContent = nextStep[phase] || nextStep.checking;
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

    function clearPersonal(nextPhase, message, focus = false, forceFocus = false) {
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
        showFeedback(message, focus && (protectedFocus || forceFocus === true));
    }

    function unavailable(message = 'RIO is tijdelijk niet beschikbaar. Controleer je testsessie opnieuw.', forceFocus = false) {
        clearPersonal('unavailable', message, true, forceFocus);
    }

    function sessionExpired(forceFocus = false) {
        clearPersonal('anonymous', 'De testsessie is verlopen of niet meer beschikbaar. Meld je opnieuw aan.', true, forceFocus);
    }

    function responseFailure(response, forceFocus = false) {
        if (response.status === 401) sessionExpired(forceFocus);
        else if (response.status === 503) unavailable(undefined, forceFocus);
        else unavailable('De testsessie kon niet veilig worden gecontroleerd. Probeer opnieuw.', forceFocus);
    }

    async function consumeJson(response) {
        const type = (response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
        if (type !== 'application/json' || !response.body) throw new Error('invalid response');
        const length = response.headers.get('content-length');
        if (length !== null && (!/^[0-9]+$/.test(length) || Number(length) > 16384)) {
            throw new Error('oversized response');
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8', { fatal: true });
        let bytes = 0;
        let content = '';
        try {
            while (true) {
                const chunk = await reader.read();
                if (chunk.done) break;
                bytes += chunk.value.byteLength;
                if (bytes > 16384) throw new Error('oversized response');
                content += decoder.decode(chunk.value, { stream: true });
            }
            content += decoder.decode();
            return JSON.parse(content);
        } catch (error) {
            void reader.cancel().catch(() => {});
            throw error;
        } finally {
            reader.releaseLock();
        }
    }

    async function request(path, options = {}) {
        const controller = new AbortController();
        let timer;
        const deadline = new Promise((resolve, reject) => {
            timer = setTimeout(() => {
                controller.abort();
                reject(new Error('request timed out'));
            }, 8000);
        });
        const operation = (async () => {
            const response = await fetch(path, {
                credentials: 'same-origin', cache: 'no-store', redirect: 'error',
                ...options, signal: controller.signal
            });
            const envelope = { status: response.status, ok: response.ok, headers: response.headers };
            if (response.ok) envelope.payload = await consumeJson(response);
            else if (response.body) void response.body.cancel().catch(() => {});
            return envelope;
        })();
        try {
            return await Promise.race([operation, deadline]);
        } catch (error) {
            controller.abort();
            throw error;
        } finally {
            clearTimeout(timer);
        }
    }

    function readJson(response) {
        return response.payload;
    }

    function validMe(me) {
        return exactKeys(me, [
            'accountId', 'csrfToken', 'actorKind', 'credentialControl', 'accountActive',
            'mode', 'operativeAuthority', 'canOpenContact', 'account1'
        ]) && closedBoundary(me)
            && (me.accountId === 'TST-alpha' || me.accountId === 'TST-beta')
            && me.actorKind === 'SYNTHETIC_DEV_ACTOR'
            && me.credentialControl === 'VERIFIED_DEV_OIDC'
            && typeof me.csrfToken === 'string' && /^[A-Za-z0-9_-]{43}$/.test(me.csrfToken);
    }

    function validatedReceipt(envelope) {
        if (!exactKeys(envelope, [
            'receipt', 'mode', 'account1', 'accountActive', 'canOpenContact', 'operativeAuthority'
        ]) || !closedBoundary(envelope)) throw new Error('invalid receipt boundary');
        const value = envelope.receipt;
        if (!exactKeys(value, ['scope', 'granted', 'revision', 'expiresAt'])
            || value.scope !== SCOPE || typeof value.granted !== 'boolean'
            || !Number.isSafeInteger(value.revision) || value.revision < 0
            || (value.granted
                ? !(Number.isSafeInteger(value.expiresAt) && value.expiresAt > 0)
                : value.expiresAt !== null)) throw new Error('invalid receipt');
        return { scope: SCOPE, granted: value.granted, revision: value.revision, expiresAt: value.expiresAt };
    }

    function displayReceipt(value, response) {
        clearTimeout(receiptTimer);
        receipt = value;
        elements.consentStatus.textContent = value.granted
            ? 'Je toestemming is actief voor deze oefensessie.'
            : 'Je hebt geen actieve toestemming voor deze oefensessie.';
        if (value.granted) {
            const stamp = epoch;
            const expire = () => {
                if (stamp !== epoch || receipt !== value) return;
                receipt = undefined;
                elements.consentStatus.textContent = 'De geldigheid moet opnieuw worden gecontroleerd. Bekijk de huidige keuze opnieuw.';
                renderControls();
            };
            // HTTP Date has second precision. Close conservatively before its possible upper bound.
            const serverDate = Date.parse(response.headers.get('date') || '');
            const observed = Math.max(Date.now(), serverDate + 1000);
            const remaining = Number.isFinite(serverDate)
                ? Math.max(0, Math.min(60000, value.expiresAt - observed)) : 0;
            if (remaining === 0) expire();
            else receiptTimer = setTimeout(expire, remaining);
        }
        renderControls();
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

    async function refreshConsent(message = '', focus = false, forceFocus = false) {
        if (phase !== 'authenticated' || busy || reading) return;
        const stamp = epoch;
        const round = ++receiptRead;
        receipt = undefined;
        clearTimeout(receiptTimer);
        elements.choice.checked = false;
        reading = true;
        elements.consentStatus.textContent = 'Toestemming wordt gecontroleerd.';
        renderControls();
        try {
            const response = await request('/api/consent');
            if (stamp !== epoch || round !== receiptRead) return;
            if (!response.ok) {
                responseFailure(response, forceFocus);
                return;
            }
            const value = validatedReceipt(await readJson(response));
            if (stamp !== epoch || round !== receiptRead) return;
            reading = false;
            displayReceipt(value, response);
            if (message) showFeedback(message, focus);
        } catch {
            if (stamp === epoch && round === receiptRead) unavailable(undefined, forceFocus);
        }
    }

    async function loadAccount(forceFocus = false) {
        clearPersonal('checking', '');
        const stamp = epoch;
        try {
            const response = await request('/api/me');
            if (stamp !== epoch) return;
            if (response.status === 401) {
                if (forceFocus === true) sessionExpired(true);
                else clearPersonal('anonymous', '');
                return;
            }
            if (!response.ok) {
                responseFailure(response, forceFocus);
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
            await refreshConsent('', false, forceFocus);
        } catch {
            if (stamp === epoch) unavailable(undefined, forceFocus);
        }
    }

    async function changeConsent(granted, forceFocus = false) {
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
                await refreshConsent('De keuze is intussen gewijzigd. Bekijk de huidige keuze en kies opnieuw.', true, forceFocus);
                return;
            }
            if (!response.ok) {
                responseFailure(response, forceFocus);
                return;
            }
            const value = validatedReceipt(await readJson(response));
            if (stamp !== epoch) return;
            if (value.granted !== granted || value.revision <= revision) throw new Error('unconfirmed choice');
            busy = false;
            displayReceipt(value, response);
            showFeedback(value.granted
                ? 'Je toestemming voor deze oefensessie is bevestigd. Persoonlijke toegang blijft gesloten.'
                : 'Je toestemming is ingetrokken. Persoonlijke toegang blijft gesloten.', true);
        } catch {
            if (stamp === epoch) unavailable('De uitkomst is nog niet bevestigd. Controleer je testsessie en de huidige toestemming opnieuw.', forceFocus);
        }
    }

    async function logout(all, forceFocus = false) {
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
                responseFailure(response, forceFocus);
                return;
            }
            const value = await readJson(response);
            if (stamp !== epoch) return;
            if (value.loggedOut !== true || value.mode !== 'SYNTHETIC_ONLY'
                || value.providerLogout !== 'NOT_REQUESTED') throw new Error('unconfirmed logout');
            clearPersonal('anonymous', 'Lokale testsessie afgemeld. De identity-provider heeft een afzonderlijke sessie.', true, forceFocus);
        } catch {
            if (stamp === epoch) unavailable('Afmelden kon niet worden bevestigd. Controleer je testsessie opnieuw.', forceFocus);
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

    function renderDraft() {
        elements.titleCount.textContent = `${draft.title.length} / 80`;
        elements.noteCount.textContent = `${draft.note.length} / 2000`;
        elements.previewTitle.textContent = draft.title || 'Jouw titel verschijnt hier';
        elements.previewNote.textContent = draft.note || 'Je notitie krijgt hier de ruimte.';
        elements.draftState.textContent = draft.title.length === 0 && draft.note.length === 0
            ? 'Nog leeg' : 'Alleen in deze pagina';
    }

    function readDraftFields() {
        draft = { title: elements.title.value, note: elements.note.value };
        renderDraft();
        return draft;
    }

    function clearDraft(message = '') {
        importRead += 1;
        draft = { title: '', note: '' };
        elements.title.value = '';
        elements.note.value = '';
        elements.import.value = '';
        renderDraft();
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
            const bytes = await file.arrayBuffer();
            if (bytes.byteLength === 0 || bytes.byteLength > MAX_DRAFT_BYTES) throw new Error('invalid file size');
            const content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
            const value = canonicalDraft(JSON.parse(content));
            if (round !== importRead) return;
            draft = value;
            elements.title.value = value.title;
            elements.note.value = value.note;
            readDraftFields();
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
        void changeConsent(true, event.isTrusted);
    });
    elements.consentRevoke.addEventListener('click', (event) => { void changeConsent(false, event.isTrusted); });
    elements.consentRefresh.addEventListener('click', (event) => { void refreshConsent('De huidige keuze is opnieuw gecontroleerd.', false, event.isTrusted); });
    elements.logout.addEventListener('click', (event) => { void logout(false, event.isTrusted); });
    elements.logoutAll.addEventListener('click', (event) => { void logout(true, event.isTrusted); });
    elements.retry.addEventListener('click', (event) => { void loadAccount(event.isTrusted); });
    window.addEventListener('pagehide', () => {
        clearPersonal('anonymous', '');
        clearDraft();
    });
    window.addEventListener('pageshow', (event) => {
        if (event.persisted) void loadAccount();
    });
    renderDraft();
    void loadAccount();
})();
