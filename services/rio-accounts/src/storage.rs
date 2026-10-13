//! T03 PostgreSQL storage for two fictitious actors only.
//! No OIDC token, password, raw session cookie, personal identity or contact authority is stored.
use std::{
    fmt,
    future::Future,
    str::FromStr,
    sync::{Arc, atomic::{AtomicBool, Ordering}},
    time::Duration,
};
use sha2::{Digest, Sha256};
use tokio::{sync::Mutex, task::AbortHandle, time::timeout};
use tokio_postgres::{Client, Config, NoTls, Row, Transaction, config::{Host, SslMode}};

/// SHA-256 of an opaque cookie or state. Raw cookie credentials never enter this module.
pub type Key = [u8; 32];
/// The only supported test consent; it confers no account activation or contact rights.
pub const CONSENT_SCOPE: &str = "RIO_SYNTHETIC_SESSION_TEST_V1";
const FLOW_MS: i64 = 300_000;
const IDLE_MS: i64 = 30_000;
const ABSOLUTE_MS: i64 = 60_000;
const MAX_FLOWS: i64 = 64;
const MAX_SESSIONS: i64 = 128;

/// Safe error categories. Database messages and connection credentials are never exposed.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StoreError {
    /// Malformed or already-consumed login transaction.
    Invalid,
    /// Missing, expired or revoked session/login fence.
    Revoked,
    /// Wrong CSRF, actor, owner or permitted scope.
    Forbidden,
    /// A bounded table or retained event budget is full.
    Capacity,
    /// Database outcome cannot be established; the connection is poisoned.
    Unavailable,
    /// Expected version does not match.
    Conflict,
}
impl fmt::Display for StoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("synthetic storage request rejected")
    }
}
impl std::error::Error for StoreError {}
impl From<tokio_postgres::Error> for StoreError {
    fn from(_: tokio_postgres::Error) -> Self { Self::Unavailable }
}

/// A move-only authorization fence returned by atomic login consumption.
/// Nonce and PKCE remain in the caller's bounded process memory and disappear on restart.
pub struct LoginPermit {
    versions: [i64; 2],
    predecessor: Option<Vec<u8>>,
    expires_ms: i64,
}

/// Protected server session. CSRF is an anti-forgery value, never a provider credential.
#[derive(Clone)]
pub struct SessionRecord {
    /// Fictitious local actor, exclusively TST-alpha or TST-beta.
    pub account_id: &'static str,
    /// Stable 256-bit anti-forgery value, retained across ordinary process restart.
    pub csrf: String,
    /// Durable creation time in milliseconds.
    pub created_ms: i64,
    /// Last successful protected read in milliseconds.
    pub touched_ms: i64,
    /// Hard absolute deadline; reads never extend it.
    pub expires_ms: i64,
    /// Current account revocation epoch.
    pub version: i64,
    /// Server-owned synthetic tenant.
    pub tenant_id: String,
}

/// A durable, bounded receipt for the exact synthetic test scope.
#[derive(Clone, Debug)]
pub struct ConsentRecord {
    /// Fixed test scope; no contact, identity or execution mandate.
    pub scope: &'static str,
    /// Compare-and-set revision.
    pub revision: i64,
    /// Effective grant after current epoch and expiry checks.
    pub granted: bool,
    /// Test grant expiry, absent when not granted.
    pub expires_ms: Option<i64>,
}

struct Inner {
    client: Mutex<Client>,
    healthy: Arc<AtomicBool>,
    connection: AbortHandle,
}
impl Drop for Inner {
    fn drop(&mut self) { self.connection.abort(); }
}

/// A bounded, transactionally serialized synthetic store. No memory fallback is provided.
#[derive(Clone)]
pub struct PgStore { inner: Arc<Inner> }

fn local_config(url: &str) -> Result<(Config, bool), StoreError> {
    if !url.starts_with("postgresql://") || url.len() > 512 { return Err(StoreError::Invalid); }
    let mut config = Config::from_str(url).map_err(|_| StoreError::Invalid)?;
    let host_ok = matches!(config.get_hosts(), [Host::Tcp(host)] if host == "127.0.0.1");
    let restore = config.get_dbname() == Some("rio_synthetic_restore");
    if !host_ok || !config.get_hostaddrs().is_empty() || config.get_ports() != [8090]
        || config.get_user() != Some("rio_dev")
        || !(config.get_dbname() == Some("rio_synthetic") || restore)
        || config.get_options().is_some() || config.get_application_name().is_some()
        || config.get_ssl_mode() != SslMode::Disable
        || !config.get_password().is_some_and(|p| p.len() == 64 && p.iter().all(u8::is_ascii_hexdigit)) {
        return Err(StoreError::Invalid);
    }
    config.connect_timeout(Duration::from_secs(8));
    config.application_name("rio-synthetic-t03");
    Ok((config, restore))
}
fn actor(id: &str) -> Result<(&'static str, usize), StoreError> {
    match id { "TST-alpha" => Ok(("TST-alpha", 0)), "TST-beta" => Ok(("TST-beta", 1)), _ => Err(StoreError::Forbidden) }
}
fn valid_csrf(value: &str) -> bool {
    value.len() == 43 && value.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}
fn csrf_matches(expected: &str, supplied: &str) -> bool {
    valid_csrf(supplied) && Sha256::digest(expected.as_bytes()) == Sha256::digest(supplied.as_bytes())
}
fn session_record(row: &Row) -> Result<SessionRecord, StoreError> {
    let id: String = row.try_get("account_id")?;
    let (account_id, _) = actor(&id)?;
    Ok(SessionRecord {
        account_id, csrf: row.try_get("csrf")?,
        created_ms: row.try_get("created_ms")?, touched_ms: row.try_get("touched_ms")?,
        expires_ms: row.try_get("absolute_expires_ms")?, version: row.try_get("version")?,
        tenant_id: row.try_get("tenant_id")?,
    })
}
async fn locked(tx: &Transaction<'_>) -> Result<i64, StoreError> {
    let row = tx.query_one(
        "SELECT schema_version,last_ms,floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS observed \
         FROM rio_synthetic.store_guard WHERE id=1 FOR UPDATE", &[]).await?;
    if row.try_get::<_, i32>("schema_version")? != 1 { return Err(StoreError::Unavailable); }
    let now = row.try_get::<_, i64>("last_ms")?.max(row.try_get("observed")?);
    tx.execute("UPDATE rio_synthetic.store_guard SET last_ms=$1 WHERE id=1", &[&now]).await?;
    tx.execute("DELETE FROM rio_synthetic.auth_transactions WHERE expires_ms <= $1", &[&now]).await?;
    tx.execute(
        "DELETE FROM rio_synthetic.sessions s USING rio_synthetic.accounts a \
         WHERE s.account_id=a.account_id AND ((NOT s.rotated AND s.idle_expires_ms <= $1) OR s.absolute_expires_ms <= $1 \
         OR s.version<>a.version OR a.status<>'SYNTHETIC_ENABLED')", &[&now]).await?;
    Ok(now)
}
async fn versions(tx: &Transaction<'_>) -> Result<[i64; 2], StoreError> {
    let row = tx.query_one(
        "SELECT (SELECT version FROM rio_synthetic.accounts WHERE account_id='TST-alpha') AS alpha,\
         (SELECT version FROM rio_synthetic.accounts WHERE account_id='TST-beta') AS beta", &[]).await?;
    Ok([row.try_get("alpha")?, row.try_get("beta")?])
}
async fn current_session(tx: &Transaction<'_>, key: &[u8]) -> Result<SessionRecord, StoreError> {
    let row = tx.query_opt(
        "SELECT s.* FROM rio_synthetic.sessions s JOIN rio_synthetic.accounts a \
         ON (s.account_id,s.owner_id,s.tenant_id)=(a.account_id,a.owner_id,a.tenant_id) \
         WHERE s.token_hash=$1 AND NOT s.rotated AND s.version=a.version AND a.status='SYNTHETIC_ENABLED'", &[&key]).await?
        .ok_or(StoreError::Revoked)?;
    session_record(&row)
}
async fn negative_session(tx: &Transaction<'_>, key: &[u8]) -> Result<(SessionRecord, Vec<u8>), StoreError> {
    let row = tx.query_opt(
        "SELECT s.* FROM rio_synthetic.sessions s JOIN rio_synthetic.accounts a \
         ON (s.account_id,s.owner_id,s.tenant_id)=(a.account_id,a.owner_id,a.tenant_id) \
         WHERE s.token_hash=$1 AND s.version=a.version AND a.status='SYNTHETIC_ENABLED'", &[&key]).await?
        .ok_or(StoreError::Revoked)?;
    Ok((session_record(&row)?, row.try_get("family_hash")?))
}
async fn audit(tx: &Transaction<'_>, id: Option<&str>, event: &str, now: i64, positive: bool) -> Result<(), StoreError> {
    let count: i64 = tx.query_one("SELECT count(*) FROM rio_synthetic.audit_events", &[]).await?.try_get(0)?;
    // Reserve room for closing all bounded active sessions and consent grants.
    if positive && count >= 4000 { return Err(StoreError::Capacity); }
    if count >= 4096 {
        // Preserve negative revocation; declare overflow honestly without manufacturing an audit event.
        tx.execute(
            "UPDATE rio_synthetic.store_guard SET audit_full=true,\
             audit_suppressed=LEAST(audit_suppressed+1,9223372036854775806) WHERE id=1", &[]).await?;
        return Ok(());
    }
    let row = tx.query_one(
        "INSERT INTO rio_synthetic.audit_events(account_id,event_type,at_ms) VALUES($1,$2,$3) RETURNING id",
        &[&id,&event,&now]).await?;
    let event_id: i64 = row.try_get(0)?;
    tx.execute("INSERT INTO rio_synthetic.outbox(audit_id) VALUES($1)", &[&event_id]).await?;
    Ok(())
}

impl PgStore {
    /// Connect only to the fixed loopback development PostgreSQL service and migrate atomically.
    /// The isolated restore database is fenced before this method returns.
    pub async fn connect_local(url: &str) -> Result<Self, StoreError> {
        let (config, restore) = local_config(url)?;
        let (client, connection) = timeout(Duration::from_secs(8), config.connect(NoTls)).await
            .map_err(|_| StoreError::Unavailable)?.map_err(|_| StoreError::Unavailable)?;
        let healthy = Arc::new(AtomicBool::new(true));
        let signal = healthy.clone();
        let task = tokio::spawn(async move {
            let _ = connection.await;
            signal.store(false, Ordering::SeqCst);
        });
        let store = Self { inner: Arc::new(Inner {
            client: Mutex::new(client), healthy, connection: task.abort_handle(),
        }) };
        store.migrate().await?;
        if restore { store.recover_after_restore().await?; }
        Ok(store)
    }

    async fn timed<T>(&self, work: impl Future<Output=Result<T, StoreError>>) -> Result<T, StoreError> {
        if !self.inner.healthy.load(Ordering::SeqCst) { return Err(StoreError::Unavailable); }
        let result = match timeout(Duration::from_secs(5), work).await {
            Ok(result) => result,
            Err(_) => Err(StoreError::Unavailable),
        };
        if result.as_ref().err() == Some(&StoreError::Unavailable) {
            // Abort any transaction with an uncertain outcome. Never return a positive fallback.
            self.inner.healthy.store(false, Ordering::SeqCst);
            self.inner.connection.abort();
        }
        result
    }

    async fn migrate(&self) -> Result<(), StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            tx.execute("SELECT pg_advisory_xact_lock(918873280)", &[]).await?;
            tx.batch_execute(include_str!("../migrations/0001_synthetic_accounts.sql")).await?;
            tx.commit().await?;
            Ok(())
        }).await
    }

    /// Confirm that the current database and schema are reachable. Failure closes readiness.
    pub async fn health(&self) -> Result<(), StoreError> {
        self.timed(async {
            let client = self.inner.client.lock().await;
            let row = client.query_one(
                "SELECT schema_version,mode,account_active FROM rio_synthetic.store_guard WHERE id=1", &[]).await?;
            if row.try_get::<_, i32>(0)? != 1 || row.try_get::<_, String>(1)? != "SYNTHETIC_ONLY"
                || row.try_get::<_, bool>(2)? { return Err(StoreError::Unavailable); }
            Ok(())
        }).await
    }

    /// Report whether the bounded audit retention is full; negative revocation remains available.
    pub async fn audit_full(&self) -> Result<bool, StoreError> {
        self.timed(async {
            let client = self.inner.client.lock().await;
            let row = client.query_one("SELECT audit_full FROM rio_synthetic.store_guard WHERE id=1", &[]).await?;
            Ok(row.try_get(0)?)
        }).await
    }

    /// Persist only hashes and revocation epochs for a short, one-use login transaction.
    pub async fn begin_login(&self, transaction_hash: Key, state_hash: Key, previous_session: Option<Key>) -> Result<(), StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let count: i64 = tx.query_one("SELECT count(*) FROM rio_synthetic.auth_transactions", &[]).await?.try_get(0)?;
            if count >= MAX_FLOWS { return Err(StoreError::Capacity); }
            let epochs = versions(&tx).await?;
            let predecessor = match previous_session {
                Some(key) => {
                    let value = key.to_vec();
                    match current_session(&tx, &value).await {
                        Ok(_) => Some(value),
                        Err(StoreError::Revoked) => None,
                        Err(error) => return Err(error),
                    }
                },
                None => None,
            };
            let transaction_hash = transaction_hash.to_vec();
            let state_hash = state_hash.to_vec();
            tx.execute(
                "INSERT INTO rio_synthetic.auth_transactions \
                 (transaction_hash,state_hash,predecessor_hash,alpha_version,beta_version,created_ms,expires_ms) \
                 VALUES($1,$2,$3,$4,$5,$6,$7)",
                &[&transaction_hash,&state_hash,&predecessor,&epochs[0],&epochs[1],&now,&(now+FLOW_MS)]).await?;
            tx.commit().await?;
            Ok(())
        }).await
    }

    /// Remove a replaced browser login transaction so bounded capacity is not orphaned.
    pub async fn discard_login(&self, transaction_hash: Key) -> Result<(), StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            locked(&tx).await?;
            tx.execute("DELETE FROM rio_synthetic.auth_transactions WHERE transaction_hash=$1", &[&transaction_hash.to_vec()]).await?;
            tx.commit().await?;
            Ok(())
        }).await
    }

    /// Atomically consume the matching transaction. Wrong state burns it before rejection.
    pub async fn consume_login(&self, transaction_hash: Key, state_hash: Key) -> Result<LoginPermit, StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let row = tx.query_opt(
                "DELETE FROM rio_synthetic.auth_transactions WHERE transaction_hash=$1 RETURNING *",
                &[&transaction_hash.to_vec()]).await?;
            // Commit consumption even when the next checks reject.
            tx.commit().await?;
            let row = row.ok_or(StoreError::Invalid)?;
            let expected: Vec<u8> = row.try_get("state_hash")?;
            if expected.as_slice() != state_hash || row.try_get::<_, i64>("expires_ms")? <= now { return Err(StoreError::Invalid); }
            Ok(LoginPermit {
                versions: [row.try_get("alpha_version")?,row.try_get("beta_version")?],
                predecessor: row.try_get("predecessor_hash")?, expires_ms: row.try_get("expires_ms")?,
            })
        }).await
    }

    /// Create a session only after current account epoch and predecessor are revalidated at commit.
    pub async fn replace_session(&self, permit: LoginPermit, account_id: &str, token_hash: Key, csrf: String) -> Result<SessionRecord, StoreError> {
        let (account_id, index) = actor(account_id)?;
        if !valid_csrf(&csrf) { return Err(StoreError::Invalid); }
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            if now >= permit.expires_ms { return Err(StoreError::Revoked); }
            let account = tx.query_one(
                "SELECT owner_id,tenant_id,status,version FROM rio_synthetic.accounts WHERE account_id=$1",
                &[&account_id]).await?;
            let version: i64 = account.try_get("version")?;
            if account.try_get::<_, String>("status")? != "SYNTHETIC_ENABLED" || version != permit.versions[index] {
                return Err(StoreError::Revoked);
            }
            let mut family = token_hash.to_vec();
            if let Some(old) = permit.predecessor.as_ref() {
                let previous = current_session(&tx, old).await?;
                if previous.account_id == account_id {
                    family = tx.query_one("SELECT family_hash FROM rio_synthetic.sessions WHERE token_hash=$1",
                        &[old]).await?.try_get(0)?;
                }
                // Retain only negative authority for a bounded original-deadline tombstone.
                tx.execute("UPDATE rio_synthetic.sessions SET rotated=true WHERE token_hash=$1", &[old]).await?;
            }
            let count: i64 = tx.query_one("SELECT count(*) FROM rio_synthetic.sessions", &[]).await?.try_get(0)?;
            if count >= MAX_SESSIONS { return Err(StoreError::Capacity); }
            let owner: String = account.try_get("owner_id")?;
            let tenant: String = account.try_get("tenant_id")?;
            let row = tx.query_one(
                "INSERT INTO rio_synthetic.sessions(token_hash,account_id,owner_id,tenant_id,version,csrf,\
                 created_ms,touched_ms,idle_expires_ms,absolute_expires_ms,family_hash) VALUES($1,$2,$3,$4,$5,$6,$7,$7,$8,$9,$10) RETURNING *",
                &[&token_hash.to_vec(),&account_id,&owner,&tenant,&version,&csrf,&now,&(now+IDLE_MS),&(now+ABSOLUTE_MS),&family]).await?;
            audit(&tx, Some(account_id), "SESSION_CREATED", now, true).await?;
            let record = session_record(&row)?;
            tx.commit().await?;
            Ok(record)
        }).await
    }

    /// Read only the cookie-owned current session; idle touch never extends absolute expiry.
    pub async fn load_session(&self, token_hash: Key) -> Result<SessionRecord, StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let key = token_hash.to_vec();
            match current_session(&tx, &key).await {
                Ok(_) => {},
                Err(StoreError::Revoked) => {
                    tx.commit().await?;
                    return Err(StoreError::Revoked);
                },
                Err(error) => return Err(error),
            }
            let row = tx.query_one(
                "UPDATE rio_synthetic.sessions SET touched_ms=$2,idle_expires_ms=LEAST($2+30000,absolute_expires_ms) \
                 WHERE token_hash=$1 RETURNING *", &[&key,&now]).await?;
            let record = session_record(&row)?;
            tx.commit().await?;
            Ok(record)
        }).await
    }

    /// Destroy only the caller's current session after CSRF is revalidated in the same transaction.
    pub async fn logout(&self, token_hash: Key, supplied_csrf: &str) -> Result<(), StoreError> {
        self.end_session(token_hash, supplied_csrf, false).await
    }

    /// Revoke every session and in-flight login fence for the caller's actor, preserving the other actor.
    pub async fn logout_all(&self, token_hash: Key, supplied_csrf: &str) -> Result<(), StoreError> {
        self.end_session(token_hash, supplied_csrf, true).await
    }

    async fn end_session(&self, token_hash: Key, supplied_csrf: &str, all: bool) -> Result<(), StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let key = token_hash.to_vec();
            let (session, family) = negative_session(&tx, &key).await?;
            if !csrf_matches(&session.csrf, supplied_csrf) { return Err(StoreError::Forbidden); }
            if all {
                tx.execute("UPDATE rio_synthetic.accounts SET version=version+1 WHERE account_id=$1", &[&session.account_id]).await?;
                tx.execute("DELETE FROM rio_synthetic.sessions WHERE account_id=$1", &[&session.account_id]).await?;
                tx.execute(
                    "UPDATE rio_synthetic.consent_receipts SET granted=false,expires_ms=NULL,revision=revision+1 \
                     WHERE account_id=$1", &[&session.account_id]).await?;
            } else {
                tx.execute("DELETE FROM rio_synthetic.sessions WHERE account_id=$1 AND family_hash=$2",
                    &[&session.account_id,&family]).await?;
            }
            audit(&tx, Some(session.account_id), if all { "ACTOR_REVOKED" } else { "SESSION_LOGOUT" }, now, false).await?;
            tx.commit().await?;
            Ok(())
        }).await
    }

    /// Read current, tenant-owned test consent without deriving any PALACO or contact authority.
    pub async fn read_consent(&self, token_hash: Key) -> Result<ConsentRecord, StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let session = current_session(&tx, &token_hash.to_vec()).await?;
            let row = tx.query_one(
                "SELECT revision,granted,expires_ms,version FROM rio_synthetic.consent_receipts \
                 WHERE account_id=$1 AND tenant_id=$2", &[&session.account_id,&session.tenant_id]).await?;
            let expiry: Option<i64> = row.try_get("expires_ms")?;
            let granted = row.try_get::<_, bool>("granted")? && row.try_get::<_, i64>("version")? == session.version
                && expiry.is_some_and(|value| value > now);
            let record = ConsentRecord { scope: CONSENT_SCOPE, revision: row.try_get("revision")?,
                granted, expires_ms: if granted { expiry } else { None } };
            tx.commit().await?;
            Ok(record)
        }).await
    }

    /// Change only the exact bounded test scope with CSRF, current epoch and receipt revision checks.
    pub async fn set_consent(&self, token_hash: Key, supplied_csrf: &str, scope: &str,
        granted: bool, expected_revision: i64) -> Result<ConsentRecord, StoreError> {
        if scope != CONSENT_SCOPE || expected_revision < 0 { return Err(StoreError::Forbidden); }
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let session = current_session(&tx, &token_hash.to_vec()).await?;
            if !csrf_matches(&session.csrf, supplied_csrf) { return Err(StoreError::Forbidden); }
            let expiry = granted.then_some(now+ABSOLUTE_MS);
            let row = tx.query_opt(
                "UPDATE rio_synthetic.consent_receipts SET granted=$3,expires_ms=$4,version=$5,revision=revision+1 \
                 WHERE account_id=$1 AND tenant_id=$2 AND revision=$6 RETURNING revision",
                &[&session.account_id,&session.tenant_id,&granted,&expiry,&session.version,&expected_revision]).await?
                .ok_or(StoreError::Conflict)?;
            audit(&tx, Some(session.account_id), if granted { "CONSENT_RECORDED" } else { "CONSENT_REVOKED" }, now, granted).await?;
            let record = ConsentRecord { scope: CONSENT_SCOPE, revision: row.try_get("revision")?, granted, expires_ms: expiry };
            tx.commit().await?;
            Ok(record)
        }).await
    }

    /// Fence an explicitly restored snapshot before it serves any bearer.
    /// Normal connections to rio_synthetic preserve sessions. The restore database invokes this automatically.
    pub async fn recover_after_restore(&self) -> Result<(), StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            tx.execute("UPDATE rio_synthetic.accounts SET version=version+1", &[]).await?;
            tx.execute("DELETE FROM rio_synthetic.sessions", &[]).await?;
            tx.execute("DELETE FROM rio_synthetic.auth_transactions", &[]).await?;
            tx.execute("UPDATE rio_synthetic.consent_receipts SET granted=false,expires_ms=NULL,revision=revision+1", &[]).await?;
            tx.execute("UPDATE rio_synthetic.store_guard SET recovery_generation=recovery_generation+1 WHERE id=1", &[]).await?;
            audit(&tx, None, "RECOVERY_FENCE", now, false).await?;
            tx.commit().await?;
            Ok(())
        }).await
    }
}
