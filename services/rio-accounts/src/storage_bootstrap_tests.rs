//! Reopening an owned TLS database must never recreate missing authority.
use super::*;
use crate::tls_database::SyntheticTlsDbConfig;
use std::net::{IpAddr, Ipv4Addr};

const ALPHA_SUBJECT: &str = "11111111-1111-4111-8111-111111111111";

struct RawConnection {
    client: Client,
    connection: AbortHandle,
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

#[derive(PartialEq)]
struct GuardState {
    schema_version: i32,
    last_ms: i64,
    recovery_generation: i64,
    audit_full: bool,
    audit_suppressed: i64,
    mode: String,
    account_active: bool,
}

async fn guard_state(raw: &Client) -> Result<GuardState, StoreError> {
    let row = bounded(raw.query_one(
        "SELECT schema_version,last_ms,recovery_generation,audit_full,audit_suppressed,mode,account_active \
         FROM rio_synthetic.store_guard WHERE id=1",
        &[],
    ))
    .await?;
    Ok(GuardState {
        schema_version: row.try_get("schema_version")?,
        last_ms: row.try_get("last_ms")?,
        recovery_generation: row.try_get("recovery_generation")?,
        audit_full: row.try_get("audit_full")?,
        audit_suppressed: row.try_get("audit_suppressed")?,
        mode: row.try_get("mode")?,
        account_active: row.try_get("account_active")?,
    })
}

async fn restore_guard(raw: &Client, saved: &GuardState) -> Result<(), StoreError> {
    bounded(raw.execute(
        "INSERT INTO rio_synthetic.store_guard \
         (id,schema_version,last_ms,recovery_generation,audit_full,audit_suppressed,mode,account_active) \
         VALUES(1,$1,$2,$3,$4,$5,$6,$7) ON CONFLICT(id) DO UPDATE SET \
         schema_version=EXCLUDED.schema_version,last_ms=EXCLUDED.last_ms,\
         recovery_generation=EXCLUDED.recovery_generation,audit_full=EXCLUDED.audit_full,\
         audit_suppressed=EXCLUDED.audit_suppressed,mode=EXCLUDED.mode,account_active=EXCLUDED.account_active",
        &[&saved.schema_version, &saved.last_ms, &saved.recovery_generation, &saved.audit_full,
          &saved.audit_suppressed, &saved.mode, &saved.account_active],
    ))
    .await?;
    Ok(())
}

async fn count(raw: &Client, sql: &str) -> Result<i64, StoreError> {
    Ok(bounded(raw.query_one(sql, &[])).await?.try_get(0)?)
}

// Compare privately retained complete rows; assertion diagnostics never print cookie-derived data.
async fn effect_snapshot(raw: &Client) -> Result<[String; 3], StoreError> {
    let row = bounded(raw.query_one(
        "SELECT \
         (SELECT COALESCE(jsonb_agg(to_jsonb(s) ORDER BY s.token_hash)::text,'[]') FROM rio_synthetic.sessions s), \
         (SELECT COALESCE(jsonb_agg(to_jsonb(a) ORDER BY a.id)::text,'[]') FROM rio_synthetic.audit_events a), \
         (SELECT COALESCE(jsonb_agg(to_jsonb(o) ORDER BY o.audit_id)::text,'[]') FROM rio_synthetic.outbox o)",
        &[],
    ))
    .await?;
    Ok([row.try_get(0)?, row.try_get(1)?, row.try_get(2)?])
}

fn key(label: &str) -> Key {
    Sha256::digest(label.as_bytes()).into()
}

#[tokio::test]
#[ignore = "requires the owned disposable PostgreSQL TLS fixture after its storage contract"]
async fn postgres_tls_bootstrap_contract() -> Result<(), StoreError> {
    let password = std::env::var("RIO_PG_TLS_PASSWORD").map_err(|_| StoreError::Invalid)?;
    let ca_path = std::env::var("RIO_PG_TLS_CA_DER").map_err(|_| StoreError::Invalid)?;
    let ca = std::fs::read(ca_path).map_err(|_| StoreError::Invalid)?;
    let config = SyntheticTlsDbConfig::for_test(
        "localhost",
        IpAddr::V4(Ipv4Addr::LOCALHOST),
        8091,
        &password,
        &ca,
    )?;
    let parts = config.connect().await?;
    let raw = RawConnection {
        client: parts.client,
        connection: parts.connection,
    };
    let bindings = bounded(raw.client.query(
        "SELECT account_id,issuer,subject FROM rio_synthetic.auth_bindings ORDER BY account_id",
        &[],
    ))
    .await?;
    assert_eq!(
        bindings.len(),
        2,
        "bootstrap retains exactly two fixed bindings"
    );
    for (row, (account, subject)) in bindings.iter().zip([
        ("TST-alpha", ALPHA_SUBJECT),
        ("TST-beta", "22222222-2222-4222-8222-222222222222"),
    ]) {
        assert!(
            row.try_get::<_, String>("account_id")? == account
                && row.try_get::<_, String>("issuer")? == crate::ISSUER
                && row.try_get::<_, String>("subject")? == subject,
            "bootstrap uses only the exact fixed issuer and subjects"
        );
    }

    // An ordinary reopen preserves negative account state and durable guard counters.
    let original_guard = guard_state(&raw.client).await?;
    let account = bounded(raw.client.query_one(
        "SELECT status,version FROM rio_synthetic.accounts WHERE account_id='TST-alpha'",
        &[],
    ))
    .await?;
    let original_status: String = account.try_get("status")?;
    let original_version: i64 = account.try_get("version")?;
    bounded(raw.client.execute(
        "UPDATE rio_synthetic.accounts SET status='SYNTHETIC_DISABLED',version=version+7 \
         WHERE account_id='TST-alpha'",
        &[],
    ))
    .await?;
    bounded(raw.client.execute(
        "UPDATE rio_synthetic.store_guard SET recovery_generation=recovery_generation+5,\
         audit_full=true,audit_suppressed=audit_suppressed+3 WHERE id=1",
        &[],
    ))
    .await?;
    let expected_guard = guard_state(&raw.client).await?;
    let reopen = PgStore::connect_tls_synthetic(&config).await;
    let actual_guard = guard_state(&raw.client).await?;
    let actual_account = bounded(raw.client.query_one(
        "SELECT status,version FROM rio_synthetic.accounts WHERE account_id='TST-alpha'",
        &[],
    ))
    .await?;
    bounded(raw.client.execute(
        "UPDATE rio_synthetic.accounts SET status=$1,version=$2 WHERE account_id='TST-alpha'",
        &[&original_status, &original_version],
    ))
    .await?;
    restore_guard(&raw.client, &original_guard).await?;
    assert!(reopen.is_ok(), "an intact TLS namespace can be reopened");
    assert!(
        actual_guard == expected_guard,
        "reopen preserves every durable guard field"
    );
    assert!(
        actual_account.try_get::<_, String>("status")? == "SYNTHETIC_DISABLED"
            && actual_account.try_get::<_, i64>("version")? == original_version + 7,
        "reopen preserves disabled status and account version"
    );
    drop(reopen);
    eprintln!("CASE T05_TLS_BOOTSTRAP_REOPEN_PRESERVES_STATE");

    let store = PgStore::connect_tls_synthetic(&config).await?;
    let transaction = key("tls-bootstrap-predecessor-transaction");
    let state = key("tls-bootstrap-predecessor-state");
    let predecessor = key("tls-bootstrap-predecessor-session");
    let anti_forgery = "b".repeat(43);
    store.begin_login(transaction, state, None).await?;
    let permit = store.consume_login(transaction, state).await?;
    store
        .replace_session_bound(
            permit,
            "TST-alpha",
            crate::ISSUER,
            ALPHA_SUBJECT,
            predecessor,
            anti_forgery.clone(),
        )
        .await?;
    let next_transaction = key("tls-bootstrap-missing-binding-transaction");
    let next_state = key("tls-bootstrap-missing-binding-state");
    store
        .begin_login(next_transaction, next_state, Some(predecessor))
        .await?;
    let permit = store.consume_login(next_transaction, next_state).await?;
    let effects_before = effect_snapshot(&raw.client).await?;
    let removed = bounded(raw.client.execute(
        "DELETE FROM rio_synthetic.auth_bindings WHERE account_id='TST-alpha' AND issuer=$1 AND subject=$2",
        &[&crate::ISSUER, &ALPHA_SUBJECT],
    ))
    .await?;
    let missing_binding_reopen = PgStore::connect_tls_synthetic(&config).await;
    let binding_count = count(
        &raw.client,
        "SELECT count(*) FROM rio_synthetic.auth_bindings WHERE account_id='TST-alpha'",
    )
    .await?;
    let denied = store
        .replace_session_bound(
            permit,
            "TST-alpha",
            crate::ISSUER,
            ALPHA_SUBJECT,
            key("tls-bootstrap-forbidden-session"),
            "c".repeat(43),
        )
        .await;
    let effects_after = effect_snapshot(&raw.client).await?;
    bounded(raw.client.execute(
        "INSERT INTO rio_synthetic.auth_bindings(account_id,issuer,subject) \
         VALUES('TST-alpha',$1,$2) ON CONFLICT(account_id) DO NOTHING",
        &[&crate::ISSUER, &ALPHA_SUBJECT],
    ))
    .await?;
    store.logout(predecessor, &anti_forgery).await?;
    assert_eq!(
        removed, 1,
        "the owned fixture removed exactly its alpha binding"
    );
    assert!(
        matches!(missing_binding_reopen, Err(StoreError::Unavailable)),
        "a missing fixed binding closes TLS store construction"
    );
    assert_eq!(
        binding_count, 0,
        "reopen cannot recreate missing binding authority"
    );
    assert!(
        matches!(denied, Err(StoreError::Forbidden)),
        "an existing store cannot replace a session without its binding"
    );
    assert!(
        effects_before == effects_after,
        "missing binding denial preserves sessions, predecessor, audit and outbox rows"
    );
    drop(store);
    eprintln!("CASE T05_TLS_BOOTSTRAP_MISSING_BINDING_DENIED");

    let saved_guard = guard_state(&raw.client).await?;
    let removed_guard = bounded(
        raw.client
            .execute("DELETE FROM rio_synthetic.store_guard WHERE id=1", &[]),
    )
    .await?;
    let missing_guard_reopen = PgStore::connect_tls_synthetic(&config).await;
    let guard_count = count(
        &raw.client,
        "SELECT count(*) FROM rio_synthetic.store_guard",
    )
    .await?;
    restore_guard(&raw.client, &saved_guard).await?;
    assert_eq!(
        removed_guard, 1,
        "the owned fixture removed exactly its guard"
    );
    assert!(
        matches!(missing_guard_reopen, Err(StoreError::Unavailable)),
        "a missing durable guard closes TLS store construction"
    );
    assert_eq!(
        guard_count, 0,
        "reopen cannot recreate a missing durable guard"
    );
    eprintln!("CASE T05_TLS_BOOTSTRAP_MISSING_GUARD_DENIED");

    // Rename only one owned fixture table; no schema or data is dropped.
    bounded(raw.client.batch_execute(
        "ALTER TABLE rio_synthetic.consent_receipts RENAME TO consent_receipts_bootstrap_test_hold",
    ))
    .await?;
    let partial_reopen = PgStore::connect_tls_synthetic(&config).await;
    let absent_table: bool = bounded(raw.client.query_one(
        "SELECT to_regclass('rio_synthetic.consent_receipts') IS NULL",
        &[],
    ))
    .await?
    .try_get(0)?;
    bounded(raw.client.batch_execute(
        "ALTER TABLE rio_synthetic.consent_receipts_bootstrap_test_hold RENAME TO consent_receipts",
    ))
    .await?;
    assert!(
        matches!(partial_reopen, Err(StoreError::Unavailable)),
        "a partial existing namespace closes TLS store construction"
    );
    assert!(
        absent_table,
        "reopen cannot create a replacement table in a partial namespace"
    );
    eprintln!("CASE T05_TLS_BOOTSTRAP_PARTIAL_NAMESPACE_DENIED");

    let reopened = PgStore::connect_tls_synthetic(&config).await?;
    reopened.health().await?;
    eprintln!("CASE T05_TLS_BOOTSTRAP_EXACT_FIXTURE_RESTORED");
    Ok(())
}
