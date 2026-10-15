//! Native TLS dump/restore proof, with live markers checked before recovery.
//! These ignored tests operate only inside the owned disposable TLS fixture.
use super::*;
use crate::tls_database::{SyntheticTlsDbConfig, SyntheticTlsRestoreDbConfig, TlsConnectionParts};
use std::net::{IpAddr, Ipv4Addr};

const ALPHA: Key = [0xa1; 32];
const BETA: Key = [0xa2; 32];
const REVOKED: Key = [0xa3; 32];
const PENDING: Key = [0xa4; 32];
const PENDING_STATE: Key = [0xa5; 32];
const ALPHA_SUBJECT: &str = "11111111-1111-4111-8111-111111111111";
const BETA_SUBJECT: &str = "22222222-2222-4222-8222-222222222222";

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
struct Snapshot(Vec<String>);
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
        &[&ALPHA.to_vec(), &BETA.to_vec()],
    )).await?.try_get(0).map_err(|_| StoreError::Unavailable)?;
    assert_eq!(
        live, 2,
        "both restored marker sessions must still be valid before fencing; expiry is not proof"
    );
    let revoked: i64 = bounded(raw.query_one(
        "SELECT count(*) FROM rio_synthetic.sessions WHERE token_hash=$1",
        &[&REVOKED.to_vec()],
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
        &[&PENDING.to_vec(), &PENDING_STATE.to_vec(), &ALPHA.to_vec()],
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
    assert!(
        matches!(
            PgStore::connect_tls_synthetic_restore(&restore_config).await,
            Err(StoreError::Unavailable)
        ),
        "restore constructor must reject an empty existing database"
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
    let alpha = issue(&store, ALPHA, "TST-alpha").await?;
    issue(&store, BETA, "TST-beta").await?;
    let revoked = issue(&store, REVOKED, "TST-alpha").await?;
    store.logout(REVOKED, &revoked.csrf).await?;
    let receipt = store.read_consent(ALPHA).await?;
    let consent = store
        .set_consent(ALPHA, &alpha.csrf, CONSENT_SCOPE, true, receipt.revision)
        .await?;
    assert!(
        consent.granted,
        "prepare records actual alpha consent through the store API"
    );
    store
        .begin_login(PENDING, PENDING_STATE, Some(ALPHA))
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

    // Privileged fixture-only deletion: malformed identity state must be rejected
    // before the constructor can perform a recovery fence or repair a binding.
    let removed = bounded(clone.client.execute(
        "DELETE FROM rio_synthetic.auth_bindings WHERE account_id='TST-alpha' AND issuer=$1 AND subject=$2",
        &[&crate::ISSUER, &ALPHA_SUBJECT],
    )).await?;
    let missing = snapshot(&clone.client).await?;
    let rejected = PgStore::connect_tls_synthetic_restore(&restore_config).await;
    let after_rejection = snapshot(&clone.client).await?;
    let restored = bounded(clone.client.execute(
        "INSERT INTO rio_synthetic.auth_bindings(account_id,issuer,subject) VALUES('TST-alpha',$1,$2)",
        &[&crate::ISSUER, &ALPHA_SUBJECT],
    )).await?;
    assert_eq!(removed, 1);
    assert_eq!(restored, 1);
    assert!(
        matches!(rejected, Err(StoreError::Unavailable)),
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

    let recovered = PgStore::connect_tls_synthetic_restore(&restore_config).await?;
    // Observe deletion before any store method can purge rows or consume the old flow.
    assert_eq!(count(&clone.client,
        "SELECT (SELECT count(*) FROM rio_synthetic.sessions)+(SELECT count(*) FROM rio_synthetic.auth_transactions)").await?, 0);
    for marker in [ALPHA, BETA, REVOKED] {
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
