//! Native TLS dump/restore proof, with live markers checked before recovery.
//! These ignored tests operate only inside the owned disposable TLS fixture.
use super::*;
use crate::tls_database::{SyntheticTlsDbConfig, SyntheticTlsRestoreDbConfig, TlsConnectionParts};
use axum::{
    body::Body,
    http::{Request, StatusCode, header},
};
use std::net::{IpAddr, Ipv4Addr};
use tower::ServiceExt;

const ALPHA_COOKIE: &str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
const BETA_COOKIE: &str = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB";
const REVOKED_COOKIE: &str = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC";
const PENDING: Key = [0xa4; 32];
const PENDING_STATE: Key = [0xa5; 32];
const ALPHA_SUBJECT: &str = "11111111-1111-4111-8111-111111111111";
const BETA_SUBJECT: &str = "22222222-2222-4222-8222-222222222222";
const CMV_MARKER: Key = [0xc7; 32];
const CMV_TERMINAL_MARKER: Key = [0xc8; 32];

fn alpha() -> Key {
    crate::hash(ALPHA_COOKIE)
}
fn beta() -> Key {
    crate::hash(BETA_COOKIE)
}
fn revoked() -> Key {
    crate::hash(REVOKED_COOKIE)
}

struct RawConnection {
    client: Client,
    connection: AbortHandle,
}
impl From<TlsConnectionParts> for RawConnection {
    fn from(parts: TlsConnectionParts) -> Self {
        Self {
            client: parts.client,
            connection: parts.connection,
        }
    }
}
impl Drop for RawConnection {
    fn drop(&mut self) {
        self.connection.abort();
    }
}

async fn bounded<T>(
    work: impl Future<Output = Result<T, tokio_postgres::Error>>,
) -> Result<T, StoreError> {
    timeout(Duration::from_secs(5), work)
        .await
        .map_err(|_| StoreError::Unavailable)?
        .map_err(|_| StoreError::Unavailable)
}

fn configs() -> Result<(SyntheticTlsDbConfig, SyntheticTlsRestoreDbConfig), StoreError> {
    let password = std::env::var("RIO_PG_TLS_PASSWORD").map_err(|_| StoreError::Invalid)?;
    let ca_path = std::env::var("RIO_PG_TLS_CA_DER").map_err(|_| StoreError::Invalid)?;
    let ca = std::fs::read(ca_path).map_err(|_| StoreError::Invalid)?;
    Ok((
        SyntheticTlsDbConfig::for_test(
            "localhost",
            IpAddr::V4(Ipv4Addr::LOCALHOST),
            8091,
            &password,
            &ca,
        )?,
        SyntheticTlsRestoreDbConfig::for_test(&password, &ca)?,
    ))
}

async fn count(raw: &Client, sql: &str) -> Result<i64, StoreError> {
    bounded(raw.query_one(sql, &[]))
        .await?
        .try_get(0)
        .map_err(|_| StoreError::Unavailable)
}

// Complete rows stay in private test memory. No Debug implementation or row values in assertions.
#[derive(PartialEq)]
pub(crate) struct Snapshot(Vec<String>);
pub(crate) async fn primary_snapshot() -> Result<Snapshot, StoreError> {
    let (primary_config, _) = configs()?;
    let primary: RawConnection = primary_config.connect().await?.into();
    snapshot(&primary.client).await
}

async fn snapshot(raw: &Client) -> Result<Snapshot, StoreError> {
    let mut rows = Vec::new();
    for (table, key) in [
        ("store_guard", "id"),
        ("accounts", "account_id"),
        ("auth_bindings", "account_id"),
        ("auth_transactions", "transaction_hash"),
        ("sessions", "token_hash"),
        ("enrollment_requests", "account_id"),
        ("provisional_id_bindings", "account_id"),
        ("consent_receipts", "account_id"),
        ("audit_events", "id"),
        ("outbox", "audit_id"),
        ("cmv_objects", "account_id,t.object_id"),
        ("cmv_events", "account_id,t.object_id,t.phase"),
    ] {
        // Both identifiers come exclusively from the fixed list above.
        let sql = format!(
            "SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY t.{key})::text,'[]') FROM rio_synthetic.{table} t"
        );
        let row = bounded(raw.query_one(&sql, &[])).await?;
        let value: String = row.try_get(0).map_err(|_| StoreError::Unavailable)?;
        if value.len() > 1_048_576 {
            return Err(StoreError::Unavailable);
        }
        rows.push(value);
    }
    Ok(Snapshot(rows))
}

async fn issue(
    store: &PgStore,
    marker: Key,
    account: &'static str,
) -> Result<SessionRecord, StoreError> {
    let transaction: Key = Sha256::digest([marker.as_slice(), b":transaction"].concat()).into();
    let state: Key = Sha256::digest([marker.as_slice(), b":state"].concat()).into();
    store.begin_login(transaction, state, None).await?;
    let permit = store.consume_login(transaction, state).await?;
    store
        .replace_session_bound(
            permit,
            account,
            crate::ISSUER,
            if account == "TST-alpha" {
                ALPHA_SUBJECT
            } else {
                BETA_SUBJECT
            },
            marker,
            "r".repeat(43),
        )
        .await
}

async fn assert_live_input(raw: &Client) -> Result<(), StoreError> {
    let live: i64 = bounded(raw.query_one(
        "SELECT count(*) FROM rio_synthetic.sessions s JOIN rio_synthetic.accounts a \
         ON (s.account_id,s.owner_id,s.tenant_id)=(a.account_id,a.owner_id,a.tenant_id) \
         WHERE ((s.token_hash=$1 AND s.account_id='TST-alpha') OR (s.token_hash=$2 AND s.account_id='TST-beta')) \
         AND NOT s.rotated AND s.version=a.version AND a.status='SYNTHETIC_ENABLED' \
         AND s.idle_expires_ms>floor(extract(epoch FROM clock_timestamp())*1000)::bigint \
         AND s.absolute_expires_ms>floor(extract(epoch FROM clock_timestamp())*1000)::bigint",
        &[&alpha().to_vec(), &beta().to_vec()],
    )).await?.try_get(0).map_err(|_| StoreError::Unavailable)?;
    assert_eq!(
        live, 2,
        "both restored marker sessions must still be valid before fencing; expiry is not proof"
    );
    let revoked: i64 = bounded(raw.query_one(
        "SELECT count(*) FROM rio_synthetic.sessions WHERE token_hash=$1",
        &[&revoked().to_vec()],
    ))
    .await?
    .try_get(0)
    .map_err(|_| StoreError::Unavailable)?;
    assert_eq!(
        revoked, 0,
        "the revoked marker was absent from the native backup input"
    );
    let pending: i64 = bounded(raw.query_one(
        "SELECT count(*) FROM rio_synthetic.auth_transactions t CROSS JOIN rio_synthetic.accounts a \
         CROSS JOIN rio_synthetic.accounts b WHERE t.transaction_hash=$1 AND t.state_hash=$2 \
         AND t.predecessor_hash=$3 AND a.account_id='TST-alpha' AND b.account_id='TST-beta' \
         AND t.alpha_version=a.version AND t.beta_version=b.version \
         AND t.expires_ms>floor(extract(epoch FROM clock_timestamp())*1000)::bigint",
        &[&PENDING.to_vec(), &PENDING_STATE.to_vec(), &alpha().to_vec()],
    )).await?.try_get(0).map_err(|_| StoreError::Unavailable)?;
    assert_eq!(
        pending, 1,
        "the native snapshot includes the live unconsumed login fence"
    );
    let granted = count(
        raw,
        "SELECT count(*) FROM rio_synthetic.consent_receipts c JOIN rio_synthetic.accounts a \
         ON (c.account_id,c.owner_id,c.tenant_id)=(a.account_id,a.owner_id,a.tenant_id) \
         WHERE c.account_id='TST-alpha' AND c.scope='RIO_SYNTHETIC_SESSION_TEST_V1' \
         AND c.granted AND c.version=a.version AND c.revision>0 \
         AND c.expires_ms>floor(extract(epoch FROM clock_timestamp())*1000)::bigint",
    )
    .await?;
    assert_eq!(
        granted, 1,
        "the native snapshot includes effective alpha consent"
    );
    Ok(())
}

#[tokio::test]
#[ignore = "requires the owned TLS fixture and its existing empty restore database, immediately before native dump"]
async fn postgres_tls_prepare_restore_contract() -> Result<(), StoreError> {
    let (primary_config, restore_config) = configs()?;
    let empty: RawConnection = restore_config.connect().await?.into();
    assert_eq!(
        count(
            &empty.client,
            "SELECT count(*) FROM pg_catalog.pg_namespace WHERE nspname='rio_synthetic'"
        )
        .await?,
        0,
        "restore proof starts from an existing database with no synthetic namespace"
    );
    let source: RawConnection = primary_config.connect().await?.into();
    let unchanged = snapshot(&source.client).await?;
    let rejected = crate::AppState::discover_tls_synthetic_restore(
        "SYNTHETIC_ONLY",
        &"a".repeat(64),
        &restore_config,
    )
    .await
    .err()
    .ok_or(StoreError::Invalid)?;
    assert_eq!(
        rejected.to_string(),
        "synthetic TLS restore database unavailable",
        "restore service constructor must reject an empty existing database"
    );
    assert_eq!(
        count(
            &empty.client,
            "SELECT count(*) FROM pg_catalog.pg_namespace WHERE nspname='rio_synthetic'"
        )
        .await?,
        0,
        "restore constructor cannot initialize the empty clone"
    );
    assert!(
        snapshot(&source.client).await? == unchanged,
        "rejecting an empty restore clone cannot mutate the primary database"
    );
    eprintln!("CASE T05_TLS_RESTORE_EMPTY_REJECTED");
    let store = PgStore::connect_tls_synthetic(&primary_config).await?;
    store.recover_after_restore().await?;
    let alpha_session = issue(&store, alpha(), "TST-alpha").await?;
    store.initialize_cmv_storage().await?;
    store
        .put_cmv_object(
            alpha(),
            &alpha_session.csrf,
            CMV_MARKER,
            b"native snapshot object",
            cmv::MAX_RETENTION_MS,
        )
        .await?;
    let terminal_digest = store
        .put_cmv_object(
            alpha(),
            &alpha_session.csrf,
            CMV_TERMINAL_MARKER,
            b"native deleted object",
            cmv::MAX_RETENTION_MS,
        )
        .await?;
    store
        .delete_cmv_object_checked(
            alpha(),
            &alpha_session.csrf,
            CMV_TERMINAL_MARKER,
            terminal_digest,
        )
        .await?;
    issue(&store, beta(), "TST-beta").await?;
    let revoked_session = issue(&store, revoked(), "TST-alpha").await?;
    store.logout(revoked(), &revoked_session.csrf).await?;
    let receipt = store.read_consent(alpha()).await?;
    let consent = store
        .set_consent(
            alpha(),
            &alpha_session.csrf,
            CONSENT_SCOPE,
            true,
            receipt.revision,
        )
        .await?;
    assert!(
        consent.granted,
        "prepare records actual alpha consent through the store API"
    );
    store
        .begin_login(PENDING, PENDING_STATE, Some(alpha()))
        .await?;
    assert_live_input(&source.client).await?;
    eprintln!("CASE T05_TLS_NATIVE_BACKUP_INPUT_LIVE");
    Ok(())
}

#[tokio::test]
#[ignore = "requires the owned TLS fixture immediately after native TLS pg_dump/pg_restore, before any recovery fence"]
async fn postgres_tls_verify_restore_contract() -> Result<(), StoreError> {
    let (primary_config, restore_config) = configs()?;
    let source: RawConnection = primary_config.connect().await?.into();
    let clone: RawConnection = restore_config.connect().await?.into();
    assert_eq!(count(&clone.client,
        "SELECT count(*) FROM pg_stat_ssl WHERE pid=pg_backend_pid() AND ssl AND version IN ('TLSv1.2','TLSv1.3')").await?, 1);
    let source_before = snapshot(&source.client).await?;
    let clone_before = snapshot(&clone.client).await?;
    assert!(
        source_before == clone_before,
        "the native clone contains complete primary table data before fencing"
    );
    assert_live_input(&clone.client).await?;
    let generation = count(
        &clone.client,
        "SELECT recovery_generation FROM rio_synthetic.store_guard WHERE id=1",
    )
    .await?;
    let epochs = bounded(clone.client.query(
        "SELECT version FROM rio_synthetic.accounts ORDER BY account_id",
        &[],
    ))
    .await?;
    let revisions = bounded(clone.client.query(
        "SELECT revision FROM rio_synthetic.consent_receipts ORDER BY account_id",
        &[],
    ))
    .await?;
    assert_eq!(epochs.len(), 2);
    assert_eq!(revisions.len(), 2);
    eprintln!("CASE T05_TLS_NATIVE_RESTORED_INPUT_LIVE");

    // Invalid service configuration must fail before touching this still-live clone.
    // Discovery is public; this format-valid secret is not used for a token exchange.
    let client_secret = "a".repeat(64);
    for (mode, secret) in [
        ("PRODUCTION", client_secret.as_str()),
        ("SYNTHETIC_ONLY", "PRIVATE_CANARY"),
    ] {
        let rejected =
            crate::AppState::discover_tls_synthetic_restore(mode, secret, &restore_config)
                .await
                .err()
                .ok_or(StoreError::Invalid)?;
        assert_eq!(
            rejected.to_string(),
            "invalid synthetic development configuration"
        );
        assert!(
            snapshot(&clone.client).await? == clone_before,
            "invalid service credentials cannot mutate or fence the clone"
        );
    }

    // Privileged fixture-only deletion: malformed identity state must be rejected
    // before the constructor can perform a recovery fence or repair a binding.
    let removed = bounded(clone.client.execute(
        "DELETE FROM rio_synthetic.auth_bindings WHERE account_id='TST-alpha' AND issuer=$1 AND subject=$2",
        &[&crate::ISSUER, &ALPHA_SUBJECT],
    )).await?;
    let missing = snapshot(&clone.client).await?;
    let rejected = crate::AppState::discover_tls_synthetic_restore(
        "SYNTHETIC_ONLY",
        &client_secret,
        &restore_config,
    )
    .await
    .err()
    .ok_or(StoreError::Invalid)?;
    let after_rejection = snapshot(&clone.client).await?;
    let restored = bounded(clone.client.execute(
        "INSERT INTO rio_synthetic.auth_bindings(account_id,issuer,subject) VALUES('TST-alpha',$1,$2)",
        &[&crate::ISSUER, &ALPHA_SUBJECT],
    )).await?;
    assert_eq!(removed, 1);
    assert_eq!(restored, 1);
    assert_eq!(
        rejected.to_string(),
        "synthetic TLS restore database unavailable",
        "missing clone binding rejects recovery"
    );
    assert!(
        missing == after_rejection,
        "rejected restore cannot repair identity or fence any state"
    );
    assert!(
        snapshot(&clone.client).await? == clone_before,
        "fixture restores only the exact original binding"
    );
    assert_live_input(&clone.client).await?;
    eprintln!("CASE T05_TLS_RESTORE_MISSING_BINDING_REJECTED");

    // A schema-valid maximum generation fails at the final counter update, after
    // recovery has attempted epoch changes, session/flow deletion and consent reset.
    // Only this owned clone is faulted, and no row values enter diagnostics.
    assert_eq!(
        bounded(clone.client.execute(
            "UPDATE rio_synthetic.store_guard SET recovery_generation=$1 \
             WHERE id=1 AND recovery_generation=$2",
            &[&i64::MAX, &generation],
        ))
        .await?,
        1
    );
    let faulted = snapshot(&clone.client).await?;
    // Prove the injected state passes the exact bootstrap validation used by
    // the constructor; an early validation refusal cannot satisfy this case.
    let validated = PgStore::from_tls_connection(restore_config.connect().await?);
    validated.initialize_or_validate(true).await?;
    drop(validated);
    assert!(
        snapshot(&clone.client).await? == faulted,
        "validation accepts the injected counter without mutation"
    );
    assert_live_input(&clone.client).await?;
    let rejected = crate::AppState::discover_tls_synthetic_restore(
        "SYNTHETIC_ONLY",
        &client_secret,
        &restore_config,
    )
    .await
    .err()
    .ok_or(StoreError::Invalid)?;
    assert_eq!(
        rejected.to_string(),
        "synthetic TLS restore database unavailable",
        "a late recovery SQL failure cannot return service state"
    );
    // Waiting for this row lock in an implicit transaction proves the failed
    // recovery transaction has ended. Query completion also releases our lock.
    let barrier = bounded(clone.client.query_one(
        "SELECT recovery_generation FROM rio_synthetic.store_guard WHERE id=1 FOR UPDATE",
        &[],
    ))
    .await?;
    assert_eq!(barrier.try_get::<_, i64>(0)?, i64::MAX);
    assert!(
        snapshot(&clone.client).await? == faulted,
        "late failure rolls back every recovery change across all ten tables"
    );
    assert_live_input(&clone.client).await?;
    assert!(
        snapshot(&source.client).await? == source_before,
        "failed clone recovery never mutates the primary database"
    );
    assert_eq!(
        bounded(clone.client.execute(
            "UPDATE rio_synthetic.store_guard SET recovery_generation=$1 \
             WHERE id=1 AND recovery_generation=$2",
            &[&generation, &i64::MAX],
        ))
        .await?,
        1
    );
    assert!(
        snapshot(&clone.client).await? == clone_before,
        "fixture restores only the exact original recovery counter"
    );
    assert_live_input(&clone.client).await?;
    eprintln!("CASE T05_TLS_RESTORE_LATE_FAILURE_ROLLED_BACK");

    let state = crate::AppState::discover_tls_synthetic_restore(
        "SYNTHETIC_ONLY",
        &client_secret,
        &restore_config,
    )
    .await
    .map_err(|_| StoreError::Unavailable)?;
    // Observe deletion before any store method can purge rows or consume the old flow.
    assert_eq!(count(&clone.client,
        "SELECT (SELECT count(*) FROM rio_synthetic.sessions)+(SELECT count(*) FROM rio_synthetic.auth_transactions)").await?, 0);
    assert!(state.store.lock().await.sessions.is_empty());
    assert!(state.store.lock().await.flows.is_empty());
    assert_eq!(state.endpoints.origin(), crate::ORIGIN);
    assert_eq!(state.endpoints.issuer(), crate::ISSUER);
    let recovered = state.db.clone().ok_or(StoreError::Unavailable)?;
    let app = crate::router(state);
    for cookie in [ALPHA_COOKIE, BETA_COOKIE, REVOKED_COOKIE] {
        for path in ["/api/me", "/api/consent"] {
            let request = Request::builder()
                .method("GET")
                .uri(path)
                .header("host", "localhost:8088")
                .header(
                    header::COOKIE,
                    format!("{}={cookie}", crate::SESSION_COOKIE),
                )
                .body(Body::empty())
                .map_err(|_| StoreError::Invalid)?;
            let response = app
                .clone()
                .oneshot(request)
                .await
                .map_err(|_| StoreError::Unavailable)?;
            assert_eq!(
                response.status(),
                StatusCode::UNAUTHORIZED,
                "the recovered service rejects every old cookie at the HTTP boundary"
            );
            assert!(
                !response.headers().contains_key(header::SET_COOKIE),
                "an old cookie cannot issue replacement credentials"
            );
        }
    }
    eprintln!("CASE T05_TLS_RESTORE_SERVICE_REJECTS_OLD_COOKIES");
    for marker in [alpha(), beta(), revoked()] {
        assert_eq!(
            recovered.load_session(marker).await.err(),
            Some(StoreError::Revoked)
        );
    }
    assert_eq!(
        recovered.consume_login(PENDING, PENDING_STATE).await.err(),
        Some(StoreError::Invalid)
    );
    let after_epochs = bounded(clone.client.query(
        "SELECT version FROM rio_synthetic.accounts ORDER BY account_id",
        &[],
    ))
    .await?;
    let after_receipts = bounded(clone.client.query(
        "SELECT revision,granted,expires_ms FROM rio_synthetic.consent_receipts ORDER BY account_id", &[],
    )).await?;
    assert_eq!(after_epochs.len(), 2);
    assert_eq!(after_receipts.len(), 2);
    for index in 0..2 {
        assert_eq!(
            after_epochs[index].try_get::<_, i64>(0)?,
            epochs[index].try_get::<_, i64>(0)? + 1
        );
        assert_eq!(
            after_receipts[index].try_get::<_, i64>("revision")?,
            revisions[index].try_get::<_, i64>(0)? + 1
        );
        assert!(!after_receipts[index].try_get::<_, bool>("granted")?);
        assert!(
            after_receipts[index]
                .try_get::<_, Option<i64>>("expires_ms")?
                .is_none()
        );
    }
    assert_eq!(
        count(
            &clone.client,
            "SELECT recovery_generation FROM rio_synthetic.store_guard WHERE id=1"
        )
        .await?,
        generation + 1
    );
    assert!(
        snapshot(&source.client).await? == source_before,
        "restore validation and recovery never mutate the primary database"
    );
    eprintln!("CASE T05_TLS_NATIVE_RESTORE_FENCED");

    let fresh = [0xa6; 32];
    let session = issue(&recovered, fresh, "TST-alpha").await?;
    assert_eq!(
        recovered.cmv_catalog(alpha()).await.err(),
        Some(StoreError::Revoked)
    );
    let catalog = recovered.cmv_catalog(fresh).await?;
    let terminal = catalog
        .objects
        .iter()
        .find(|o| o.object_id == CMV_TERMINAL_MARKER)
        .ok_or(StoreError::Invalid)?;
    assert_eq!(terminal.state, "DELETED");
    assert_eq!(
        terminal.digest,
        Key::from(Sha256::digest(b"native deleted object"))
    );
    assert_eq!(
        recovered
            .delete_cmv_object_checked(
                alpha(),
                &"r".repeat(43),
                CMV_TERMINAL_MARKER,
                terminal.digest
            )
            .await
            .err(),
        Some(StoreError::Revoked)
    );
    let confirmed = recovered
        .delete_cmv_object_checked(fresh, &session.csrf, CMV_TERMINAL_MARKER, terminal.digest)
        .await?;
    assert_eq!(confirmed.state, "DELETED");
    assert_eq!(Some(confirmed.ended_ms), terminal.ended_ms);
    assert_eq!(confirmed.digest, terminal.digest);
    assert_eq!(count(&clone.client, "SELECT count(*) FROM rio_synthetic.cmv_events WHERE account_id='TST-alpha' AND object_id=decode(repeat('c8',32),'hex')").await?, 2);
    let marker = catalog
        .objects
        .iter()
        .find(|o| o.object_id == CMV_MARKER)
        .ok_or(StoreError::Invalid)?;
    assert_eq!(marker.state, "LIVE");
    assert_eq!(
        marker.digest,
        Key::from(Sha256::digest(b"native snapshot object"))
    );
    assert_eq!(
        recovered.read_cmv_object(fresh, CMV_MARKER).await?,
        b"native snapshot object"
    );
    assert_eq!(session.account_id, "TST-alpha");
    assert_eq!(recovered.load_session(fresh).await?.account_id, "TST-alpha");
    assert!(
        !recovered.read_consent(fresh).await?.granted,
        "fresh authentication after restore does not revive old consent"
    );
    assert!(
        snapshot(&source.client).await? == source_before,
        "fresh clone session issuance is isolated from primary state"
    );
    eprintln!("CASE T05_TLS_RESTORE_FRESH_BOUND_SESSION");
    Ok(())
}
