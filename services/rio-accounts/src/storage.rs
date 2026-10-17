//! T03 PostgreSQL storage for two fictitious actors only.
//! No OIDC token, password, raw session cookie, personal identity or contact authority is stored.
use sha2::{Digest, Sha256};
use std::{
    fmt,
    future::Future,
    str::FromStr,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use tokio::{sync::Mutex, task::AbortHandle, time::timeout};
use tokio_postgres::{
    Client, Config, NoTls, Row, Transaction,
    config::{Host, SslMode},
};

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
    fn from(_error: tokio_postgres::Error) -> Self {
        #[cfg(test)]
        {
            let diagnostic = if _error.is_closed() {
                "CASE T03_SQL_CLOSED"
            } else if std::error::Error::source(&_error)
                .is_some_and(|cause| cause.is::<tokio_postgres::types::WrongType>())
            {
                "CASE T03_SQL_TYPE"
            } else {
                match _error.code().map(|code| code.code()) {
                    Some("23502" | "23503" | "23505" | "23514") => "CASE T03_SQL_CONSTRAINT",
                    Some(_) => "CASE T03_SQL_DATABASE",
                    None => "CASE T03_SQL_OTHER",
                }
            };
            eprintln!("{diagnostic}");
        }
        Self::Unavailable
    }
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
    fn drop(&mut self) {
        self.connection.abort();
    }
}

/// A bounded, transactionally serialized synthetic store. No memory fallback is provided.
#[derive(Clone)]
pub struct PgStore {
    inner: Arc<Inner>,
}

fn local_config(url: &str) -> Result<(Config, bool), StoreError> {
    if !url.starts_with("postgresql://") || url.len() > 512 {
        return Err(StoreError::Invalid);
    }
    let mut config = Config::from_str(url).map_err(|_| StoreError::Invalid)?;
    let host_ok = matches!(config.get_hosts(), [Host::Tcp(host)] if host == "127.0.0.1");
    let restore = config.get_dbname() == Some("rio_synthetic_restore");
    if !host_ok
        || !config.get_hostaddrs().is_empty()
        || config.get_ports() != [8090]
        || config.get_user() != Some("rio_dev")
        || !(config.get_dbname() == Some("rio_synthetic") || restore)
        || config.get_options().is_some()
        || config.get_application_name().is_some()
        || config.get_ssl_mode() != SslMode::Disable
        || !config
            .get_password()
            .is_some_and(|p| p.len() == 64 && p.iter().all(u8::is_ascii_hexdigit))
    {
        return Err(StoreError::Invalid);
    }
    config.connect_timeout(Duration::from_secs(8));
    config.application_name("rio-synthetic-t03");
    Ok((config, restore))
}
fn actor(id: &str) -> Result<(&'static str, usize), StoreError> {
    match id {
        "TST-alpha" => Ok(("TST-alpha", 0)),
        "TST-beta" => Ok(("TST-beta", 1)),
        _ => Err(StoreError::Forbidden),
    }
}
fn valid_csrf(value: &str) -> bool {
    value.len() == 43
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}
fn csrf_matches(expected: &str, supplied: &str) -> bool {
    valid_csrf(supplied)
        && Sha256::digest(expected.as_bytes()) == Sha256::digest(supplied.as_bytes())
}
fn session_record(row: &Row) -> Result<SessionRecord, StoreError> {
    let id: String = row.try_get("account_id")?;
    let (account_id, _) = actor(&id)?;
    Ok(SessionRecord {
        account_id,
        csrf: row.try_get("csrf")?,
        created_ms: row.try_get("created_ms")?,
        touched_ms: row.try_get("touched_ms")?,
        expires_ms: row.try_get("absolute_expires_ms")?,
        version: row.try_get("version")?,
        tenant_id: row.try_get("tenant_id")?,
    })
}
async fn locked(tx: &Transaction<'_>) -> Result<i64, StoreError> {
    let row = tx
        .query_one(
            "SELECT schema_version,last_ms FROM rio_synthetic.store_guard WHERE id=1 FOR UPDATE",
            &[],
        )
        .await?;
    if row.try_get::<_, i32>("schema_version")? != 1 {
        return Err(StoreError::Unavailable);
    }
    // Read the wall clock after the lock is held, so waiting transactions do not compare stale observations.
    let observed: i64 = tx
        .query_one(
            "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint",
            &[],
        )
        .await?
        .try_get(0)?;
    if observed < row.try_get::<_, i64>("last_ms")? {
        return Err(StoreError::Unavailable);
    }
    let now = observed;
    tx.execute(
        "UPDATE rio_synthetic.store_guard SET last_ms=$1 WHERE id=1",
        &[&now],
    )
    .await?;
    tx.execute(
        "DELETE FROM rio_synthetic.auth_transactions WHERE expires_ms <= $1",
        &[&now],
    )
    .await?;
    tx.execute(
        "DELETE FROM rio_synthetic.sessions s USING rio_synthetic.accounts a \
         WHERE s.account_id=a.account_id AND ((NOT s.rotated AND s.idle_expires_ms <= $1) OR s.absolute_expires_ms <= $1 \
         OR s.version<>a.version OR a.status<>'SYNTHETIC_ENABLED')", &[&now]).await?;
    // Clock observations and expiry deletion survive logical rejection of business work.
    tx.batch_execute("SAVEPOINT rio_business").await?;
    Ok(now)
}
async fn reject_business<T>(tx: Transaction<'_>, error: StoreError) -> Result<T, StoreError> {
    if error == StoreError::Unavailable {
        // Unknown database outcomes are never acknowledged or replaced by memory state.
        return Err(error);
    }
    tx.batch_execute("ROLLBACK TO SAVEPOINT rio_business")
        .await?;
    tx.commit().await?;
    Err(error)
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
async fn negative_session(
    tx: &Transaction<'_>,
    key: &[u8],
) -> Result<(SessionRecord, Vec<u8>), StoreError> {
    let row = tx
        .query_opt(
            "SELECT s.* FROM rio_synthetic.sessions s JOIN rio_synthetic.accounts a \
         ON (s.account_id,s.owner_id,s.tenant_id)=(a.account_id,a.owner_id,a.tenant_id) \
         WHERE s.token_hash=$1 AND s.version=a.version AND a.status='SYNTHETIC_ENABLED'",
            &[&key],
        )
        .await?
        .ok_or(StoreError::Revoked)?;
    Ok((session_record(&row)?, row.try_get("family_hash")?))
}
async fn audit(
    tx: &Transaction<'_>,
    id: Option<&str>,
    event: &str,
    now: i64,
    positive: bool,
) -> Result<(), StoreError> {
    let count: i64 = tx
        .query_one("SELECT count(*) FROM rio_synthetic.audit_events", &[])
        .await?
        .try_get(0)?;
    // Reserve room for closing all bounded active sessions and consent grants.
    if positive && count >= 4000 {
        return Err(StoreError::Capacity);
    }
    if count >= 4096 {
        // Preserve negative revocation; declare overflow honestly without manufacturing an audit event.
        tx.execute(
            "UPDATE rio_synthetic.store_guard SET audit_full=true,\
             audit_suppressed=LEAST(audit_suppressed+1,9223372036854775806) WHERE id=1",
            &[],
        )
        .await?;
        return Ok(());
    }
    let row = tx.query_one(
        "INSERT INTO rio_synthetic.audit_events(account_id,event_type,at_ms) VALUES($1,$2,$3) RETURNING id",
        &[&id,&event,&now]).await?;
    let event_id: i64 = row.try_get(0)?;
    tx.execute(
        "INSERT INTO rio_synthetic.outbox(audit_id) VALUES($1)",
        &[&event_id],
    )
    .await?;
    Ok(())
}

impl PgStore {
    /// Connect only to the fixed loopback development PostgreSQL service and migrate atomically.
    /// The isolated restore database is fenced before this method returns.
    pub async fn connect_local(url: &str) -> Result<Self, StoreError> {
        let (config, restore) = local_config(url)?;
        let (client, connection) = timeout(Duration::from_secs(8), config.connect(NoTls))
            .await
            .map_err(|_| StoreError::Unavailable)?
            .map_err(|_| StoreError::Unavailable)?;
        let healthy = Arc::new(AtomicBool::new(true));
        let signal = healthy.clone();
        let task = tokio::spawn(async move {
            let _ = connection.await;
            signal.store(false, Ordering::SeqCst);
        });
        let store = Self {
            inner: Arc::new(Inner {
                client: Mutex::new(client),
                healthy,
                connection: task.abort_handle(),
            }),
        };
        store.migrate().await?;
        if restore {
            store.recover_after_restore().await?;
        }
        Ok(store)
    }

    /// Connect an explicitly configured TLS database with the existing closed synthetic schema.
    /// This does not select a staging issuer or make the browser runtime available remotely.
    pub async fn connect_tls_synthetic(
        config: &crate::tls_database::SyntheticTlsDbConfig,
    ) -> Result<Self, StoreError> {
        let connection = config.connect().await?;
        let store = Self {
            inner: Arc::new(Inner {
                client: Mutex::new(connection.client),
                healthy: connection.healthy,
                connection: connection.connection,
            }),
        };
        store.migrate().await?;
        Ok(store)
    }

    async fn timed<T>(
        &self,
        work: impl Future<Output = Result<T, StoreError>>,
    ) -> Result<T, StoreError> {
        if !self.inner.healthy.load(Ordering::SeqCst) {
            return Err(StoreError::Unavailable);
        }
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
            tx.execute("SELECT pg_advisory_xact_lock(918873280)", &[])
                .await?;
            tx.batch_execute(include_str!("../migrations/0001_synthetic_accounts.sql"))
                .await?;
            tx.commit().await?;
            Ok(())
        })
        .await
    }

    /// Confirm that the current database and schema are reachable. Failure closes readiness.
    pub async fn health(&self) -> Result<(), StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            locked(&tx).await?;
            let row = tx.query_one(
                "SELECT schema_version,mode,account_active FROM rio_synthetic.store_guard WHERE id=1",
                &[],
            ).await?;
            if row.try_get::<_, i32>(0)? != 1
                || row.try_get::<_, String>(1)? != "SYNTHETIC_ONLY"
                || row.try_get::<_, bool>(2)?
            {
                return Err(StoreError::Unavailable);
            }
            tx.commit().await?;
            Ok(())
        })
        .await
    }

    /// Report whether the bounded audit retention is full; negative revocation remains available.
    pub async fn audit_full(&self) -> Result<bool, StoreError> {
        self.timed(async {
            let client = self.inner.client.lock().await;
            let row = client
                .query_one(
                    "SELECT audit_full FROM rio_synthetic.store_guard WHERE id=1",
                    &[],
                )
                .await?;
            Ok(row.try_get(0)?)
        })
        .await
    }

    /// Persist only hashes and revocation epochs for a short, one-use login transaction.
    pub async fn begin_login(
        &self,
        transaction_hash: Key,
        state_hash: Key,
        previous_session: Option<Key>,
    ) -> Result<(), StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let count: i64 = tx.query_one("SELECT count(*) FROM rio_synthetic.auth_transactions", &[]).await?.try_get(0)?;
            if count >= MAX_FLOWS { return reject_business(tx, StoreError::Capacity).await; }
            let epochs = versions(&tx).await?;
            let predecessor = match previous_session {
                Some(key) => {
                    let value = key.to_vec();
                    match current_session(&tx, &value).await {
                        Ok(_) => Some(value),
                        Err(StoreError::Revoked) => None,
                        Err(error) => return reject_business(tx, error).await,
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
            tx.execute(
                "DELETE FROM rio_synthetic.auth_transactions WHERE transaction_hash=$1",
                &[&transaction_hash.to_vec()],
            )
            .await?;
            tx.commit().await?;
            Ok(())
        })
        .await
    }

    /// Atomically consume the matching transaction. Wrong state burns it before rejection.
    pub async fn consume_login(
        &self,
        transaction_hash: Key,
        state_hash: Key,
    ) -> Result<LoginPermit, StoreError> {
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
            if expected.as_slice() != state_hash || row.try_get::<_, i64>("expires_ms")? <= now {
                return Err(StoreError::Invalid);
            }
            Ok(LoginPermit {
                versions: [row.try_get("alpha_version")?, row.try_get("beta_version")?],
                predecessor: row.try_get("predecessor_hash")?,
                expires_ms: row.try_get("expires_ms")?,
            })
        })
        .await
    }

    /// Resolve the exact issuer/subject binding and revalidate its account epoch at commit.
    /// The account hint cannot substitute a database binding. Issuer and subject
    /// are lookup inputs; this method does not itself verify an OIDC token.
    pub async fn replace_session_bound(
        &self,
        permit: LoginPermit,
        account_hint: &str,
        issuer: &str,
        subject: &str,
        token_hash: Key,
        csrf: String,
    ) -> Result<SessionRecord, StoreError> {
        let (account_hint, _) = actor(account_hint)?;
        if !valid_csrf(&csrf) {
            return Err(StoreError::Invalid);
        }
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            if now >= permit.expires_ms { return reject_business(tx, StoreError::Revoked).await; }
            // Both binding and account stay locked until the session commit.
            // Derive ownership from the matching database row, never from the hint.
            let account = tx.query_opt(
                "SELECT a.account_id,a.owner_id,a.tenant_id,a.status,a.version \
                 FROM rio_synthetic.auth_bindings b JOIN rio_synthetic.accounts a \
                 ON a.account_id=b.account_id WHERE b.issuer=$1 AND b.subject=$2 \
                 FOR SHARE OF b,a",
                &[&issuer,&subject]).await?;
            let Some(account) = account else {
                return reject_business(tx, StoreError::Forbidden).await;
            };
            let bound_id: String = account.try_get("account_id")?;
            if bound_id != account_hint {
                return reject_business(tx, StoreError::Forbidden).await;
            }
            let (account_id, index) = match actor(&bound_id) {
                Ok(actor) => actor,
                Err(error) => return reject_business(tx, error).await,
            };
            let version: i64 = account.try_get("version")?;
            if account.try_get::<_, String>("status")? != "SYNTHETIC_ENABLED" || version != permit.versions[index] {
                return reject_business(tx, StoreError::Revoked).await;
            }
            let mut family = token_hash.to_vec();
            if let Some(old) = permit.predecessor.as_ref() {
                let previous = match current_session(&tx, old).await {
                    Ok(session) => session,
                    Err(error) => return reject_business(tx, error).await,
                };
                if previous.account_id == account_id {
                    family = tx.query_one("SELECT family_hash FROM rio_synthetic.sessions WHERE token_hash=$1",
                        &[old]).await?.try_get(0)?;
                }
                // Retain only negative authority for a bounded original-deadline tombstone.
                tx.execute("UPDATE rio_synthetic.sessions SET rotated=true WHERE token_hash=$1", &[old]).await?;
            }
            let count: i64 = tx.query_one("SELECT count(*) FROM rio_synthetic.sessions", &[]).await?.try_get(0)?;
            if count >= MAX_SESSIONS { return reject_business(tx, StoreError::Capacity).await; }
            let owner: String = account.try_get("owner_id")?;
            let tenant: String = account.try_get("tenant_id")?;
            let row = tx.query_one(
                "INSERT INTO rio_synthetic.sessions(token_hash,account_id,owner_id,tenant_id,version,csrf,\
                 created_ms,touched_ms,idle_expires_ms,absolute_expires_ms,family_hash) VALUES($1,$2,$3,$4,$5,$6,$7,$7,$8,$9,$10) RETURNING *",
                &[&token_hash.to_vec(),&account_id,&owner,&tenant,&version,&csrf,&now,&(now+IDLE_MS),&(now+ABSOLUTE_MS),&family]).await?;
            if let Err(error) = audit(&tx, Some(account_id), "SESSION_CREATED", now, true).await {
                return reject_business(tx, error).await;
            }
            let record = match session_record(&row) {
                Ok(record) => record,
                Err(error) => return reject_business(tx, error).await,
            };
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
                Err(error) => return reject_business(tx, error).await,
            }
            let row = tx.query_one(
                "UPDATE rio_synthetic.sessions SET touched_ms=$2::bigint,idle_expires_ms=LEAST($2::bigint+30000::bigint,absolute_expires_ms) \
                 WHERE token_hash=$1 RETURNING *", &[&key,&now]).await?;
            let record = match session_record(&row) {
                Ok(record) => record,
                Err(error) => return reject_business(tx, error).await,
            };
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

    async fn end_session(
        &self,
        token_hash: Key,
        supplied_csrf: &str,
        all: bool,
    ) -> Result<(), StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let key = token_hash.to_vec();
            let (session, family) = match negative_session(&tx, &key).await {
                Ok(record) => record,
                Err(error) => return reject_business(tx, error).await,
            };
            if !csrf_matches(&session.csrf, supplied_csrf) { return reject_business(tx, StoreError::Forbidden).await; }
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
            let session = match current_session(&tx, &token_hash).await {
                Ok(session) => session,
                Err(error) => return reject_business(tx, error).await,
            };
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
    pub async fn set_consent(
        &self,
        token_hash: Key,
        supplied_csrf: &str,
        scope: &str,
        granted: bool,
        expected_revision: i64,
    ) -> Result<ConsentRecord, StoreError> {
        if scope != CONSENT_SCOPE || expected_revision < 0 {
            return Err(StoreError::Forbidden);
        }
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let session = match current_session(&tx, &token_hash).await {
                Ok(session) => session,
                Err(error) => return reject_business(tx, error).await,
            };
            if !csrf_matches(&session.csrf, supplied_csrf) { return reject_business(tx, StoreError::Forbidden).await; }
            let expiry = granted.then_some(now+ABSOLUTE_MS);
            let row = tx.query_opt(
                "UPDATE rio_synthetic.consent_receipts SET granted=$3,expires_ms=$4,version=$5,revision=revision+1 \
                 WHERE account_id=$1 AND tenant_id=$2 AND revision=$6 RETURNING revision",
                &[&session.account_id,&session.tenant_id,&granted,&expiry,&session.version,&expected_revision]).await?;
            let row = match row {
                Some(row) => row,
                None => return reject_business(tx, StoreError::Conflict).await,
            };
            if let Err(error) = audit(&tx, Some(session.account_id), if granted { "CONSENT_RECORDED" } else { "CONSENT_REVOKED" }, now, granted).await {
                return reject_business(tx, error).await;
            }
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

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::task::JoinHandle;

    fn key(label: &str) -> Key {
        Sha256::digest(label.as_bytes()).into()
    }
    fn csrf(label: u8) -> String {
        char::from(label).to_string().repeat(43)
    }
    fn test_url(name: &str) -> Result<String, StoreError> {
        std::env::var(name).map_err(|_| StoreError::Invalid)
    }
    async fn raw(url: &str) -> Result<(Client, JoinHandle<()>), StoreError> {
        let (config, _) = local_config(url)?;
        let (client, connection) = config.connect(NoTls).await?;
        let task = tokio::spawn(async move {
            let _ = connection.await;
        });
        Ok((client, task))
    }

    // Test-only convenience: every existing fixture login supplies its exact
    // declared issuer and subject. This does not manufacture token verification.
    impl PgStore {
        async fn replace_test_session(
            &self,
            permit: LoginPermit,
            account_hint: &str,
            token_hash: Key,
            csrf: String,
        ) -> Result<SessionRecord, StoreError> {
            let subject = match account_hint {
                "TST-alpha" => "11111111-1111-4111-8111-111111111111",
                "TST-beta" => "22222222-2222-4222-8222-222222222222",
                _ => return Err(StoreError::Forbidden),
            };
            self.replace_session_bound(
                permit,
                account_hint,
                crate::ISSUER,
                subject,
                token_hash,
                csrf,
            )
            .await
        }
    }

    struct BindingSnapshot {
        sessions: i64,
        audits: i64,
        outbox: i64,
        rotated: bool,
        family: Vec<u8>,
    }

    async fn binding_snapshot(
        raw: &Client,
        predecessor: Key,
    ) -> Result<BindingSnapshot, StoreError> {
        let counts = raw
            .query_one(
                "SELECT (SELECT count(*) FROM rio_synthetic.sessions) AS sessions, \
             (SELECT count(*) FROM rio_synthetic.audit_events) AS audits, \
             (SELECT count(*) FROM rio_synthetic.outbox) AS outbox",
                &[],
            )
            .await?;
        let parent = raw
            .query_one(
                "SELECT rotated,family_hash FROM rio_synthetic.sessions WHERE token_hash=$1",
                &[&predecessor.to_vec()],
            )
            .await?;
        Ok(BindingSnapshot {
            sessions: counts.try_get("sessions")?,
            audits: counts.try_get("audits")?,
            outbox: counts.try_get("outbox")?,
            rotated: parent.try_get("rotated")?,
            family: parent.try_get("family_hash")?,
        })
    }

    fn binding_denial_preserves(before: &BindingSnapshot, after: &BindingSnapshot) {
        assert_eq!(
            before.sessions, after.sessions,
            "binding denial cannot create a session"
        );
        assert_eq!(
            before.audits, after.audits,
            "binding denial cannot audit a successful issue"
        );
        assert_eq!(
            before.outbox, after.outbox,
            "binding denial cannot enqueue a successful issue"
        );
        assert_eq!(
            before.rotated, after.rotated,
            "binding denial cannot rotate its predecessor"
        );
        // Never print private family material in assertion diagnostics.
        assert!(
            before.family == after.family,
            "binding denial retains its predecessor family"
        );
    }

    async fn login(
        store: &PgStore,
        label: &str,
        id: &str,
        parent: Option<Key>,
    ) -> Result<(Key, String), StoreError> {
        let transaction = key(&format!("transaction:{label}"));
        let state = key(&format!("state:{label}"));
        let token = key(&format!("token:{label}"));
        let anti_forgery = csrf(if id == "TST-beta" { b'z' } else { b'a' });
        eprintln!("CASE T03_LOGIN_BEGIN");
        store.begin_login(transaction, state, parent).await?;
        eprintln!("CASE T03_LOGIN_CONSUME");
        let permit = store.consume_login(transaction, state).await?;
        eprintln!("CASE T03_LOGIN_REPLACE");
        store
            .replace_test_session(permit, id, token, anti_forgery.clone())
            .await?;
        Ok((token, anti_forgery))
    }

    #[test]
    fn configuration_and_scope_are_fixed_before_network_io() {
        let url = format!(
            "postgresql://rio_dev:{}@127.0.0.1:8090/rio_synthetic?sslmode=disable",
            "a".repeat(64)
        );
        assert!(local_config(&url).is_ok());
        for wrong in [
            url.replace("127.0.0.1", "attacker.example"),
            url.replace(":8090", ":5432"),
            url.replace("rio_synthetic?", "postgres?"),
            url.replace("rio_dev:", "postgres:"),
            url.replace("sslmode=disable", "sslmode=require"),
            format!("{url}&hostaddr=192.0.2.1"),
            format!("{url}&options=-csynchronous_commit%3Doff"),
        ] {
            assert!(
                local_config(&wrong).is_err(),
                "unapproved connection parameters are rejected"
            );
        }
        assert!(actor("verified-browser-role").is_err());
        assert!(!valid_csrf("short"));
    }

    /// Real PostgreSQL contract. CI must explicitly select this ignored test with the private URL.
    #[tokio::test]
    #[ignore = "requires isolated synthetic PostgreSQL; never a production database"]
    async fn postgres_storage_contract() -> Result<(), StoreError> {
        eprintln!("CASE T03_SETUP");
        let url = test_url("RIO_PG_TEST_URL")?;
        let store = PgStore::connect_local(&url).await?;
        let other = PgStore::connect_local(&url).await?;
        let (mut raw, task) = raw(&url).await?;
        store.recover_after_restore().await?;
        store.health().await?;

        eprintln!("CASE T03_ATOMIC_FLOW");
        // Atomic one-use consumption, including wrong-state burning across independent clients.
        let transaction = key("atomic-transaction");
        let state = key("atomic-state");
        store.begin_login(transaction, state, None).await?;
        let (one, two) = tokio::join!(
            store.consume_login(transaction, state),
            other.consume_login(transaction, state)
        );
        assert!(
            one.is_ok() != two.is_ok(),
            "exactly one independent client consumes the transaction"
        );
        store.begin_login(key("wrong-state"), state, None).await?;
        assert_eq!(
            store
                .consume_login(key("wrong-state"), key("bad"))
                .await
                .err(),
            Some(StoreError::Invalid)
        );
        assert_eq!(
            store.consume_login(key("wrong-state"), state).await.err(),
            Some(StoreError::Invalid)
        );
        store.begin_login(key("expired-flow"), state, None).await?;
        raw.execute("UPDATE rio_synthetic.auth_transactions SET created_ms=created_ms-301000,expires_ms=expires_ms-301000 \
            WHERE transaction_hash=$1", &[&key("expired-flow").to_vec()]).await?;
        assert_eq!(
            store.consume_login(key("expired-flow"), state).await.err(),
            Some(StoreError::Invalid)
        );

        eprintln!("CASE T03_BINDING_DISABLED");
        // An extant issuer/subject binding does not override account status.
        // There are no live sessions for alpha at this point, so cleanup is
        // distinguishable from rotating or issuing a predecessor session.
        let disabled_tx = key("disabled-bound-login");
        let disabled_state = key("disabled-bound-state");
        store.begin_login(disabled_tx, disabled_state, None).await?;
        let disabled_permit = store.consume_login(disabled_tx, disabled_state).await?;
        let denied_counts_before = raw
            .query_one(
                "SELECT (SELECT count(*) FROM rio_synthetic.sessions) AS sessions, \
             (SELECT count(*) FROM rio_synthetic.audit_events) AS audits, \
             (SELECT count(*) FROM rio_synthetic.outbox) AS outbox",
                &[],
            )
            .await?;
        raw.execute(
            "UPDATE rio_synthetic.accounts SET status='SYNTHETIC_DISABLED' WHERE account_id='TST-alpha'",
            &[]).await?;
        let disabled_result = store
            .replace_session_bound(
                disabled_permit,
                "TST-alpha",
                crate::ISSUER,
                "11111111-1111-4111-8111-111111111111",
                key("disabled-bound-session"),
                csrf(b'd'),
            )
            .await;
        raw.execute(
            "UPDATE rio_synthetic.accounts SET status='SYNTHETIC_ENABLED' WHERE account_id='TST-alpha'",
            &[]).await?;
        assert_eq!(disabled_result.err(), Some(StoreError::Revoked));
        let denied_counts_after = raw
            .query_one(
                "SELECT (SELECT count(*) FROM rio_synthetic.sessions) AS sessions, \
             (SELECT count(*) FROM rio_synthetic.audit_events) AS audits, \
             (SELECT count(*) FROM rio_synthetic.outbox) AS outbox",
                &[],
            )
            .await?;
        for field in ["sessions", "audits", "outbox"] {
            assert_eq!(
                denied_counts_before.try_get::<_, i64>(field)?,
                denied_counts_after.try_get::<_, i64>(field)?,
                "disabled binding cannot issue or audit a session"
            );
        }

        eprintln!("CASE T03_DURABILITY");
        // Durable own-tenant sessions and stable CSRF survive a fresh store/process connection.
        eprintln!("CASE T03_DURABILITY_ALPHA_LOGIN");
        let (alpha, alpha_csrf) = login(&store, "durable-alpha", "TST-alpha", None).await?;
        eprintln!("CASE T03_DURABILITY_BETA_LOGIN");
        let (beta, beta_csrf) = login(&store, "durable-beta", "TST-beta", None).await?;
        eprintln!("CASE T03_DURABILITY_BEFORELOAD");
        let before = store.load_session(alpha).await?;
        eprintln!("CASE T03_DURABILITY_RECONNECT");
        let restarted = PgStore::connect_local(&url).await?;
        eprintln!("CASE T03_DURABILITY_AFTERLOAD");
        let after = restarted.load_session(alpha).await?;
        assert_eq!(after.account_id, "TST-alpha");
        assert_eq!(after.tenant_id, "tenant-TST-alpha");
        assert!(
            after.csrf == alpha_csrf,
            "ordinary reconnect preserves this session anti-forgery value"
        );
        assert_eq!(after.expires_ms, before.expires_ms);
        assert_eq!(store.load_session(beta).await?.account_id, "TST-beta");
        assert_eq!(
            store.logout(alpha, &beta_csrf).await.err(),
            Some(StoreError::Forbidden)
        );
        // The same actor's separate session also cannot substitute its CSRF.
        let tx = key("other-csrf-tx");
        let state2 = key("other-csrf-state");
        store.begin_login(tx, state2, None).await?;
        let permit = store.consume_login(tx, state2).await?;
        let alpha_peer = key("alpha-peer");
        let peer_csrf = csrf(b'b');
        store
            .replace_test_session(permit, "TST-alpha", alpha_peer, peer_csrf.clone())
            .await?;
        assert_eq!(
            store.logout(alpha, &peer_csrf).await.err(),
            Some(StoreError::Forbidden)
        );

        eprintln!("CASE T03_BOUND_ISSUER_SUBJECT");
        // Wrong issuer, unknown subject and account-hint substitution all deny
        // before predecessor rotation, insertion or success audit/outbox writes.
        for (label, hint, issuer, subject) in [
            (
                "binding-wrong-issuer",
                "TST-alpha",
                "https://idp.example.invalid/realms/rio-synthetic-staging",
                "11111111-1111-4111-8111-111111111111",
            ),
            (
                "binding-unknown-subject",
                "TST-alpha",
                crate::ISSUER,
                "33333333-3333-4333-8333-333333333333",
            ),
            (
                "binding-alpha-hint-beta-subject",
                "TST-alpha",
                crate::ISSUER,
                "22222222-2222-4222-8222-222222222222",
            ),
            (
                "binding-beta-hint-alpha-subject",
                "TST-beta",
                crate::ISSUER,
                "11111111-1111-4111-8111-111111111111",
            ),
        ] {
            let transaction = key(&format!("{label}:transaction"));
            let state = key(&format!("{label}:state"));
            store
                .begin_login(transaction, state, Some(alpha_peer))
                .await?;
            let permit = store.consume_login(transaction, state).await?;
            let before = binding_snapshot(&raw, alpha_peer).await?;
            let result = store
                .replace_session_bound(permit, hint, issuer, subject, key(label), csrf(b'q'))
                .await;
            assert_eq!(result.err(), Some(StoreError::Forbidden));
            let after = binding_snapshot(&raw, alpha_peer).await?;
            binding_denial_preserves(&before, &after);
        }

        eprintln!("CASE T03_BOUND_MISSING_RECORD");
        let missing_tx = key("missing-binding-transaction");
        let missing_state = key("missing-binding-state");
        store
            .begin_login(missing_tx, missing_state, Some(alpha_peer))
            .await?;
        let missing_permit = store.consume_login(missing_tx, missing_state).await?;
        let before_missing = binding_snapshot(&raw, alpha_peer).await?;
        // Commit a fixture-only deletion so the independent store connection
        // actually observes a missing binding. Restore the exact constrained
        // record in a separate transaction before checking the denial.
        let deletion = raw.transaction().await?;
        let removed = deletion
            .execute(
                "DELETE FROM rio_synthetic.auth_bindings WHERE account_id='TST-alpha' \
             AND issuer=$1 AND subject=$2",
                &[&crate::ISSUER, &"11111111-1111-4111-8111-111111111111"],
            )
            .await?;
        deletion.commit().await?;
        let missing_result = store
            .replace_session_bound(
                missing_permit,
                "TST-alpha",
                crate::ISSUER,
                "11111111-1111-4111-8111-111111111111",
                key("missing-binding-session"),
                csrf(b'r'),
            )
            .await;
        let after_missing = binding_snapshot(&raw, alpha_peer).await?;
        let still_missing: i64 = raw
            .query_one(
                "SELECT count(*) FROM rio_synthetic.auth_bindings WHERE account_id='TST-alpha'",
                &[],
            )
            .await?
            .try_get(0)?;
        let restoration = raw.transaction().await?;
        restoration
            .execute(
                "INSERT INTO rio_synthetic.auth_bindings(account_id,issuer,subject) \
             VALUES('TST-alpha',$1,$2)",
                &[&crate::ISSUER, &"11111111-1111-4111-8111-111111111111"],
            )
            .await?;
        restoration.commit().await?;
        assert_eq!(removed, 1);
        assert_eq!(
            still_missing, 0,
            "lookup cannot silently repair a missing binding"
        );
        assert_eq!(missing_result.err(), Some(StoreError::Forbidden));
        binding_denial_preserves(&before_missing, &after_missing);

        eprintln!("CASE T03_TENANT");
        // Composite owner/tenant FK rejects a cross-tenant session even through trusted fixture SQL.
        let cross = raw.execute(
            "INSERT INTO rio_synthetic.sessions(token_hash,family_hash,account_id,owner_id,tenant_id,version,csrf,\
             created_ms,touched_ms,idle_expires_ms,absolute_expires_ms) \
             SELECT $1,$1,'TST-alpha','owner-TST-alpha','tenant-TST-beta',version,$2,$3,$3,$4,$5 \
             FROM rio_synthetic.accounts WHERE account_id='TST-alpha'",
            &[&key("cross-tenant").to_vec(),&csrf(b'c'),&before.created_ms,&(before.created_ms+IDLE_MS),&(before.created_ms+ABSOLUTE_MS)]).await;
        assert!(
            cross.is_err(),
            "foreign tenant cannot be associated with the alpha actor"
        );
        let bindings: i64 = raw
            .query_one("SELECT count(*) FROM rio_synthetic.auth_bindings", &[])
            .await?
            .try_get(0)?;
        assert_eq!(bindings, 2);

        eprintln!("CASE T03_CONSENT");
        // Consent is exact-scope, actor-owned, current-version and revision-bound.
        let receipt = store.read_consent(alpha).await?;
        let accepted = store
            .set_consent(alpha, &alpha_csrf, CONSENT_SCOPE, true, receipt.revision)
            .await?;
        assert!(accepted.granted);
        assert!(
            !store.read_consent(beta).await?.granted,
            "alpha consent does not grant beta consent"
        );
        assert_eq!(
            store
                .set_consent(
                    alpha,
                    &alpha_csrf,
                    "CONTACT_OR_IDENTITY",
                    true,
                    accepted.revision
                )
                .await
                .err(),
            Some(StoreError::Forbidden)
        );
        assert_eq!(
            store
                .set_consent(alpha, &alpha_csrf, CONSENT_SCOPE, false, receipt.revision)
                .await
                .err(),
            Some(StoreError::Conflict)
        );

        eprintln!("CASE T03_LOGOUT_ALL");
        // A logout-all closes both alpha sessions and a previously authorized login fence.
        store
            .begin_login(key("pending-alpha"), state, Some(alpha_peer))
            .await?;
        let pending = store.consume_login(key("pending-alpha"), state).await?;
        store.logout_all(alpha, &alpha_csrf).await?;
        assert_eq!(
            store.load_session(alpha).await.err(),
            Some(StoreError::Revoked)
        );
        assert_eq!(
            store.load_session(alpha_peer).await.err(),
            Some(StoreError::Revoked)
        );
        assert_eq!(
            store
                .replace_test_session(pending, "TST-alpha", key("stale-alpha"), csrf(b'c'))
                .await
                .err(),
            Some(StoreError::Revoked)
        );
        assert_eq!(other.load_session(beta).await?.account_id, "TST-beta");
        // Fresh authentication after revocation is permitted; the stale cookie confers no predecessor authority.
        let (fresh, fresh_csrf) =
            login(&store, "fresh-after-revoke", "TST-alpha", Some(alpha)).await?;
        assert!(!store.read_consent(fresh).await?.granted);

        eprintln!("CASE T03_ROTATE_FIRST");
        // Both serializations of real predecessor rotation versus negative revocation close descendants.
        store
            .begin_login(key("rotate-first-tx"), state, Some(fresh))
            .await?;
        let rotate = store.consume_login(key("rotate-first-tx"), state).await?;
        let child = key("rotate-first-child");
        let child_csrf = csrf(b'd');
        store
            .replace_test_session(rotate, "TST-alpha", child, child_csrf.clone())
            .await?;
        assert_eq!(
            store.load_session(fresh).await.err(),
            Some(StoreError::Revoked)
        );
        assert_eq!(store.load_session(child).await?.account_id, "TST-alpha");
        store.logout_all(fresh, &fresh_csrf).await?;
        assert_eq!(
            store.load_session(child).await.err(),
            Some(StoreError::Revoked)
        );
        assert_eq!(store.load_session(beta).await?.account_id, "TST-beta");

        eprintln!("CASE T03_REVOKE_FIRST");
        let (old, old_csrf) = login(&store, "revoke-first-parent", "TST-alpha", None).await?;
        store
            .begin_login(key("revoke-first-tx"), state, Some(old))
            .await?;
        let rotate = store.consume_login(key("revoke-first-tx"), state).await?;
        store.logout_all(old, &old_csrf).await?;
        assert_eq!(
            store
                .replace_test_session(rotate, "TST-alpha", key("revoke-first-child"), csrf(b'e'))
                .await
                .err(),
            Some(StoreError::Revoked)
        );

        eprintln!("CASE T03_RACE");
        let (racing, racing_csrf) = login(&store, "concurrent-parent", "TST-alpha", None).await?;
        store
            .begin_login(key("concurrent-tx"), state, Some(racing))
            .await?;
        let rotate = store.consume_login(key("concurrent-tx"), state).await?;
        let concurrent_child = key("concurrent-child");
        let (revoked, rotated) = tokio::join!(
            store.logout_all(racing, &racing_csrf),
            other.replace_test_session(rotate, "TST-alpha", concurrent_child, csrf(b'f'))
        );
        assert!(
            revoked.is_ok(),
            "negative actor revocation commits in either serialization"
        );
        assert!(rotated.is_ok() || rotated.err() == Some(StoreError::Revoked));
        assert_eq!(
            store.load_session(concurrent_child).await.err(),
            Some(StoreError::Revoked)
        );

        eprintln!("CASE T03_FAMILY");
        // Single logout closes only the predecessor's family, not an independent alpha or beta session.
        let (family, family_csrf) = login(&store, "family-parent", "TST-alpha", None).await?;
        let (independent, _) = login(&store, "independent-alpha", "TST-alpha", None).await?;
        store
            .begin_login(key("family-child-tx"), state, Some(family))
            .await?;
        let rotate = store.consume_login(key("family-child-tx"), state).await?;
        let family_child = key("family-child");
        store
            .replace_test_session(rotate, "TST-alpha", family_child, csrf(b'g'))
            .await?;
        store.logout(family, &family_csrf).await?;
        assert_eq!(
            store.load_session(family_child).await.err(),
            Some(StoreError::Revoked)
        );
        assert_eq!(
            store.load_session(independent).await?.account_id,
            "TST-alpha"
        );
        assert_eq!(store.load_session(beta).await?.account_id, "TST-beta");

        eprintln!("CASE T03_EXPIRY");
        // Fixed idle and absolute expiry do not become alive after reconnect.
        let (idle, _) = login(&store, "idle-expiry", "TST-alpha", None).await?;
        raw.execute("UPDATE rio_synthetic.sessions SET created_ms=created_ms-31000,touched_ms=touched_ms-31000,\
            idle_expires_ms=idle_expires_ms-31000,absolute_expires_ms=absolute_expires_ms-31000 WHERE token_hash=$1",
            &[&idle.to_vec()]).await?;
        assert_eq!(
            store.load_session(idle).await.err(),
            Some(StoreError::Revoked)
        );
        let removed: i64 = raw
            .query_one(
                "SELECT count(*) FROM rio_synthetic.sessions WHERE token_hash=$1",
                &[&idle.to_vec()],
            )
            .await?
            .try_get(0)?;
        assert_eq!(removed, 0, "observed expiry is durably removed");
        let (expired, _) = login(&store, "absolute-expiry", "TST-alpha", None).await?;
        raw.execute("UPDATE rio_synthetic.sessions SET created_ms=created_ms-61000,\
            absolute_expires_ms=absolute_expires_ms-61000,idle_expires_ms=absolute_expires_ms-61000 WHERE token_hash=$1",
            &[&expired.to_vec()]).await?;
        assert_eq!(
            restarted.load_session(expired).await.err(),
            Some(StoreError::Revoked)
        );
        let (new_after_expiry, _) =
            login(&store, "fresh-after-expiry", "TST-alpha", Some(expired)).await?;
        assert_eq!(
            store.load_session(new_after_expiry).await?.account_id,
            "TST-alpha"
        );

        // Logical rejection cannot undo a clock observation or expiry deletion.
        for (label, deny_kind) in [
            ("expired-logout", 0),
            ("expired-consent-read", 1),
            ("expired-consent-write", 2),
        ] {
            let (expired, anti_forgery) = login(&store, label, "TST-alpha", None).await?;
            let observed_before: i64 = raw
                .query_one(
                    "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint",
                    &[],
                )
                .await?
                .try_get(0)?;
            // A rejected call must advance an older guard, rather than just retaining equality.
            raw.execute(
                "UPDATE rio_synthetic.store_guard SET last_ms=$1 WHERE id=1",
                &[&(observed_before - 5)],
            )
            .await?;
            raw.execute(
                "UPDATE rio_synthetic.sessions SET created_ms=created_ms-31000,touched_ms=touched_ms-31000,\
                 idle_expires_ms=idle_expires_ms-31000,absolute_expires_ms=absolute_expires_ms-31000 WHERE token_hash=$1",
                &[&expired.to_vec()],
            ).await?;
            let rejection = match deny_kind {
                0 => store.logout(expired, &anti_forgery).await.err(),
                1 => store.read_consent(expired).await.err(),
                _ => store
                    .set_consent(expired, &anti_forgery, CONSENT_SCOPE, true, 0)
                    .await
                    .err(),
            };
            assert_eq!(rejection, Some(StoreError::Revoked));
            let retained: i64 = raw
                .query_one(
                    "SELECT count(*) FROM rio_synthetic.sessions WHERE token_hash=$1",
                    &[&expired.to_vec()],
                )
                .await?
                .try_get(0)?;
            assert_eq!(
                retained, 0,
                "logical rejection durably removes the expired session"
            );
            let observed_after: i64 = raw
                .query_one(
                    "SELECT last_ms FROM rio_synthetic.store_guard WHERE id=1",
                    &[],
                )
                .await?
                .try_get(0)?;
            assert!(
                observed_after >= observed_before,
                "rejection retains its observed durable clock"
            );
            // Even a privileged fixture clock rewind cannot restore a deleted bearer row.
            raw.execute(
                "UPDATE rio_synthetic.store_guard SET last_ms=$1 WHERE id=1",
                &[&observed_before],
            )
            .await?;
            assert_eq!(
                restarted.load_session(expired).await.err(),
                Some(StoreError::Revoked)
            );
        }

        eprintln!("CASE T03_SCHEMA");
        // No password, provider token, nonce or PKCE columns exist in the durable schema.
        let prohibited: i64 = raw.query_one(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='rio_synthetic' \
             AND column_name IN ('password','password_hash','access_token','refresh_token','id_token','nonce','pkce')",
            &[]).await?.try_get(0)?;
        assert_eq!(prohibited, 0);
        let hidden: i64 = raw.query_one(
            "SELECT (SELECT count(*) FROM rio_synthetic.enrollment_requests WHERE status<>'DISABLED_SYNTHETIC') \
             +(SELECT count(*) FROM rio_synthetic.provisional_id_bindings WHERE status<>'DISABLED_SYNTHETIC') \
             +(SELECT count(*) FROM rio_synthetic.outbox WHERE external_side_effect)", &[]).await?.try_get(0)?;
        assert_eq!(hidden, 0);
        let immutable = raw
            .execute("UPDATE rio_synthetic.audit_events SET at_ms=at_ms+1", &[])
            .await;
        assert!(immutable.is_err(), "attributable audit cannot be rewritten");
        eprintln!("CASE T03_CLOCK");
        // A backwards durable clock cannot freeze and prolong a retained cookie lease.
        raw.execute("UPDATE rio_synthetic.store_guard SET last_ms=floor(extract(epoch FROM clock_timestamp())*1000)::bigint+5000 WHERE id=1",
            &[]).await?;
        assert_eq!(
            store.load_session(beta).await.err(),
            Some(StoreError::Unavailable)
        );
        assert_eq!(other.health().await.err(), Some(StoreError::Unavailable));
        // This is private fixture repair only, followed by an explicit recovery fence.
        raw.execute("UPDATE rio_synthetic.store_guard SET last_ms=floor(extract(epoch FROM clock_timestamp())*1000)::bigint WHERE id=1",
            &[]).await?;
        let recovered = PgStore::connect_local(&url).await?;
        recovered.recover_after_restore().await?;
        assert_eq!(
            recovered.load_session(beta).await.err(),
            Some(StoreError::Revoked)
        );
        task.abort();
        Ok(())
    }

    /// Seed fresh non-bearer marker hashes immediately before the fixture's actual pg_dump.
    #[tokio::test]
    #[ignore = "stage immediately before actual synthetic backup/restore; requires private DB URL"]
    async fn postgres_prepare_restore_proof() -> Result<(), StoreError> {
        eprintln!("CASE T03_BACKUP_PREPARE");
        let url = test_url("RIO_PG_TEST_URL")?;
        let store = PgStore::connect_local(&url).await?;
        store.recover_after_restore().await?;
        for (marker, id) in [
            ([0x91; 32], "TST-alpha"),
            ([0x92; 32], "TST-beta"),
            ([0x93; 32], "TST-alpha"),
        ] {
            let transaction = key(&format!("restore-tx:{}", marker[0]));
            let state = key("restore-state");
            store.begin_login(transaction, state, None).await?;
            let permit = store.consume_login(transaction, state).await?;
            store
                .replace_test_session(permit, id, marker, csrf(b'h'))
                .await?;
        }
        store.logout([0x93; 32], &csrf(b'h')).await?;
        assert!(store.load_session([0x91; 32]).await.is_ok());
        assert!(store.load_session([0x92; 32]).await.is_ok());
        assert_eq!(
            store.load_session([0x93; 32]).await.err(),
            Some(StoreError::Revoked)
        );
        let (raw, task) = raw(&url).await?;
        let live: i64 = raw
            .query_one(
                "SELECT count(*) FROM rio_synthetic.sessions WHERE token_hash IN ($1,$2) \
             AND idle_expires_ms>floor(extract(epoch FROM clock_timestamp())*1000)::bigint \
             AND absolute_expires_ms>floor(extract(epoch FROM clock_timestamp())*1000)::bigint",
                &[&vec![0x91u8; 32], &vec![0x92u8; 32]],
            )
            .await?
            .try_get(0)?;
        assert_eq!(
            live, 2,
            "backup input contains two fresh, currently valid marker sessions"
        );
        task.abort();
        Ok(())
    }

    /// Verify the real cloned snapshot while still live, then fence it before any application use.
    #[tokio::test]
    #[ignore = "stage after actual pg_dump/pg_restore, before any separate recovery fence"]
    async fn postgres_verify_restored_snapshot() -> Result<(), StoreError> {
        eprintln!("CASE T03_RESTORE_BEFORE");
        let url = test_url("RIO_PG_RESTORE_TEST_URL")?;
        let (_, is_restore) = local_config(&url)?;
        assert!(
            is_restore,
            "restore proof never targets the ordinary application database"
        );
        let (raw, task) = raw(&url).await?;
        let before: i64 = raw.query_one(
            "SELECT count(*) FROM rio_synthetic.sessions WHERE token_hash IN ($1,$2) AND NOT rotated \
             AND idle_expires_ms>floor(extract(epoch FROM clock_timestamp())*1000)::bigint \
             AND absolute_expires_ms>floor(extract(epoch FROM clock_timestamp())*1000)::bigint",
            &[&vec![0x91u8;32],&vec![0x92u8;32]]).await?.try_get(0)?;
        assert_eq!(
            before, 2,
            "actual restored clone contains two live sessions before fencing; expiry is not evidence"
        );
        let revoked: i64 = raw
            .query_one(
                "SELECT count(*) FROM rio_synthetic.sessions WHERE token_hash=$1",
                &[&vec![0x93u8; 32]],
            )
            .await?
            .try_get(0)?;
        assert_eq!(
            revoked, 0,
            "the deliberately revoked marker was absent from the backup"
        );
        let generation: i64 = raw
            .query_one(
                "SELECT recovery_generation FROM rio_synthetic.store_guard WHERE id=1",
                &[],
            )
            .await?
            .try_get(0)?;
        eprintln!("CASE T03_RESTORE_FENCE");
        let restored = PgStore::connect_local(&url).await?;
        restored.health().await?;
        for marker in [[0x91; 32], [0x92; 32], [0x93; 32]] {
            assert_eq!(
                restored.load_session(marker).await.err(),
                Some(StoreError::Revoked)
            );
        }
        let empty: i64 = raw
            .query_one(
                "SELECT (SELECT count(*) FROM rio_synthetic.sessions)\
            +(SELECT count(*) FROM rio_synthetic.auth_transactions)",
                &[],
            )
            .await?
            .try_get(0)?;
        assert_eq!(empty, 0);
        let fenced: i64 = raw
            .query_one(
                "SELECT recovery_generation FROM rio_synthetic.store_guard WHERE id=1",
                &[],
            )
            .await?
            .try_get(0)?;
        assert!(
            fenced > generation,
            "controlled recovery advanced its durable fence"
        );
        task.abort();
        Ok(())
    }

    #[tokio::test]
    #[ignore = "requires the owned disposable PostgreSQL TLS fixture"]
    async fn postgres_tls_store_contract() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        use crate::tls_database::SyntheticTlsDbConfig;
        use std::net::{IpAddr, Ipv4Addr};
        use tokio_postgres::config::ChannelBinding;

        let password = std::env::var("RIO_PG_TLS_PASSWORD").map_err(|_| StoreError::Invalid)?;
        let ca_path = std::env::var("RIO_PG_TLS_CA_DER").map_err(|_| StoreError::Invalid)?;
        let other_path =
            std::env::var("RIO_PG_TLS_OTHER_CA_DER").map_err(|_| StoreError::Invalid)?;
        let ca = std::fs::read(ca_path).map_err(|_| StoreError::Invalid)?;
        let other_ca = std::fs::read(other_path).map_err(|_| StoreError::Invalid)?;
        let address = IpAddr::V4(Ipv4Addr::LOCALHOST);

        // Same credentials/database on a deliberately plain local control server:
        // the no-TLS refusal below cannot pass merely because credentials were wrong.
        let mut plain_config = Config::new();
        plain_config
            .host("127.0.0.1")
            .port(8092)
            .user("rio_dev")
            .dbname("rio_synthetic_tls")
            .password(&password)
            .ssl_mode(SslMode::Disable)
            .channel_binding(ChannelBinding::Disable)
            .connect_timeout(Duration::from_secs(8));
        let (plain, connection) = timeout(Duration::from_secs(8), plain_config.connect(NoTls))
            .await
            .map_err(|_| StoreError::Unavailable)?
            .map_err(|_| StoreError::Unavailable)?;
        let plain_task = tokio::spawn(async move {
            let _ = connection.await;
        });
        let row = timeout(
            Duration::from_secs(5),
            plain.query_one(
                "SELECT 1::int AS value,ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()",
                &[],
            ),
        )
        .await
        .map_err(|_| StoreError::Unavailable)??;
        assert_eq!(row.try_get::<_, i32>("value")?, 1);
        assert!(!row.try_get::<_, bool>("ssl")?);
        plain_task.abort();
        eprintln!("CASE T05_TLS_PLAIN_CONTROL");

        let config = SyntheticTlsDbConfig::for_test("localhost", address, 8091, &password, &ca)?;
        let store = PgStore::connect_tls_synthetic(&config).await?;
        store.health().await?;
        {
            let client = store.inner.client.lock().await;
            let row = client
                .query_one(
                    "SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid()",
                    &[],
                )
                .await?;
            assert!(row.try_get::<_, bool>("ssl")?);
            assert!(matches!(
                row.try_get::<_, String>("version")?.as_str(),
                "TLSv1.2" | "TLSv1.3"
            ));
            let guard = client
                .query_one(
                    "SELECT mode,account_active FROM rio_synthetic.store_guard WHERE id=1",
                    &[],
                )
                .await?;
            assert_eq!(guard.try_get::<_, String>("mode")?, "SYNTHETIC_ONLY");
            assert!(!guard.try_get::<_, bool>("account_active")?);
        }
        eprintln!("CASE T05_TLS_ENCRYPTED_CURRENT_CONNECTION");

        let wrong_ca =
            SyntheticTlsDbConfig::for_test("localhost", address, 8091, &password, &other_ca)?;
        assert!(matches!(
            PgStore::connect_tls_synthetic(&wrong_ca).await,
            Err(StoreError::Unavailable)
        ));
        eprintln!("CASE T05_TLS_WRONG_CA");
        let wrong_name =
            SyntheticTlsDbConfig::for_test("wrong.example.invalid", address, 8091, &password, &ca)?;
        assert!(matches!(
            PgStore::connect_tls_synthetic(&wrong_name).await,
            Err(StoreError::Unavailable)
        ));
        eprintln!("CASE T05_TLS_WRONG_HOSTNAME");
        let without_tls =
            SyntheticTlsDbConfig::for_test("localhost", address, 8092, &password, &ca)?;
        assert!(matches!(
            PgStore::connect_tls_synthetic(&without_tls).await,
            Err(StoreError::Unavailable)
        ));
        eprintln!("CASE T05_TLS_NO_FALLBACK");

        let mut forbidden_plain = Config::new();
        forbidden_plain
            .host("127.0.0.1")
            .port(8091)
            .user("rio_dev")
            .dbname("rio_synthetic_tls")
            .password(&password)
            .ssl_mode(SslMode::Disable)
            .channel_binding(ChannelBinding::Disable)
            .connect_timeout(Duration::from_secs(8));
        assert!(
            timeout(Duration::from_secs(8), forbidden_plain.connect(NoTls))
                .await
                .map_err(|_| StoreError::Unavailable)?
                .is_err()
        );
        eprintln!("CASE T05_TLS_PLAINTEXT_DENIED");

        let transaction = key("tls-alpha-transaction");
        let state = key("tls-alpha-state");
        let token = key("tls-alpha-session");
        store.begin_login(transaction, state, None).await?;
        let permit = store.consume_login(transaction, state).await?;
        let alpha = store
            .replace_session_bound(
                permit,
                "TST-alpha",
                crate::ISSUER,
                "11111111-1111-4111-8111-111111111111",
                token,
                csrf(b't'),
            )
            .await?;
        assert_eq!(alpha.account_id, "TST-alpha");
        assert_eq!(alpha.tenant_id, "tenant-TST-alpha");
        assert_eq!(store.load_session(token).await?.account_id, "TST-alpha");
        {
            let client = store.inner.client.lock().await;
            let before = binding_snapshot(&client, token).await?;
            drop(client);
            let next = key("tls-wrong-issuer-transaction");
            let next_state = key("tls-wrong-issuer-state");
            store.begin_login(next, next_state, Some(token)).await?;
            let permit = store.consume_login(next, next_state).await?;
            assert!(matches!(
                store
                    .replace_session_bound(
                        permit,
                        "TST-alpha",
                        "https://idp.example.invalid/realms/rio-synthetic-staging",
                        "11111111-1111-4111-8111-111111111111",
                        key("tls-forbidden-session"),
                        csrf(b'u'),
                    )
                    .await,
                Err(StoreError::Forbidden)
            ));
            let client = store.inner.client.lock().await;
            let after = binding_snapshot(&client, token).await?;
            binding_denial_preserves(&before, &after);
        }
        eprintln!("CASE T05_TLS_BOUND_SUBJECT");

        store.logout(token, &alpha.csrf).await?;
        assert!(matches!(
            store.load_session(token).await,
            Err(StoreError::Revoked)
        ));
        eprintln!("CASE T05_TLS_REVOKED_SESSION");
        drop(store);
        Ok(())
    }
}
