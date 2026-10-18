//! Internal, opt-in synthetic object API. No browser route or contact authority.
//! Bytes are opaque synthetic fixtures, not a credential or personal-data vault.
use super::*;

/// Maximum bytes per object.
pub const MAX_OBJECT_BYTES: usize = 16_384;
/// Maximum live bytes per account; terminal objects release their payload budget.
pub const MAX_ACCOUNT_BYTES: i64 = 65_536;
/// Lifetime object slots per account, including tombstones (IDs are never reused).
pub const MAX_ACCOUNT_OBJECTS: i64 = 64;
/// Maximum retention, in milliseconds.
pub const MAX_RETENTION_MS: i64 = 86_400_000;

/// Authenticated account's bounded usage. Tombstones count toward retained slots.
#[derive(Debug, PartialEq, Eq)]
pub struct Usage {
    /// Current live payload size.
    pub live_bytes: i64,
    /// Retained object and tombstone slots.
    pub retained_objects: i64,
}

fn valid_input(payload: &[u8], retention_ms: i64) -> bool {
    !payload.is_empty()
        && payload.len() <= MAX_OBJECT_BYTES
        && (1..=MAX_RETENTION_MS).contains(&retention_ms)
}

async fn usage(tx: &Transaction<'_>, session: &SessionRecord) -> Result<Usage, StoreError> {
    let row = tx
        .query_one(
            "SELECT count(*)::bigint,COALESCE(sum(octet_length(payload)),0)::bigint \
         FROM rio_synthetic.cmv_objects WHERE account_id=$1 AND tenant_id=$2",
            &[&session.account_id, &session.tenant_id],
        )
        .await?;
    Ok(Usage {
        retained_objects: row.try_get(0)?,
        live_bytes: row.try_get(1)?,
    })
}

// Lifecycle and attributable terminal events commit atomically. The guard lock
// also serializes independent connections, quota checks and actor revocation.
async fn expire(tx: &Transaction<'_>, session: &SessionRecord, now: i64) -> Result<(), StoreError> {
    tx.execute(
        "WITH expired AS (UPDATE rio_synthetic.cmv_objects SET payload=''::bytea,state='EXPIRED' \
         WHERE account_id=$1 AND tenant_id=$2 AND state='LIVE' AND expires_ms<=$3 RETURNING object_id) \
         INSERT INTO rio_synthetic.cmv_events(account_id,object_id,phase,event_type,at_ms) \
         SELECT $1,object_id,1,'EXPIRED',$3 FROM expired",
        &[&session.account_id,&session.tenant_id,&now]).await?;
    Ok(())
}

impl PgStore {
    /// Explicit operator opt-in after the existing bootstrap/binding validation.
    /// The browser service never calls this automatically. Restore fencing must
    /// precede use, as with every other PgStore API. No identity rows are repaired.
    pub async fn initialize_cmv_storage(&self) -> Result<(), StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            tx.execute("SELECT pg_advisory_xact_lock(918873280)", &[])
                .await?;
            validate_bootstrap(&tx).await?;
            tx.batch_execute(include_str!("../../migrations/0002_cmv_objects.sql"))
                .await?;
            tx.commit().await?;
            Ok(())
        })
        .await
    }

    /// Create immutable bytes under a caller-generated opaque object ID.
    /// Session identity, CSRF, quotas and object creation share one transaction.
    pub async fn put_cmv_object(
        &self,
        token_hash: Key,
        supplied_csrf: &str,
        object_id: Key,
        payload: &[u8],
        retention_ms: i64,
    ) -> Result<Key, StoreError> {
        if !valid_input(payload, retention_ms) {
            return Err(StoreError::Invalid);
        }
        let digest: Key = Sha256::digest(payload).into();
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let session = match current_session(&tx,&token_hash).await {
                Ok(session) => session, Err(error) => return reject_business(tx,error).await,
            };
            if !csrf_matches(&session.csrf,supplied_csrf) { return reject_business(tx,StoreError::Forbidden).await; }
            expire(&tx,&session,now).await?;
            let exists = tx.query_opt("SELECT 1 FROM rio_synthetic.cmv_objects WHERE account_id=$1 AND object_id=$2",
                &[&session.account_id,&&object_id[..]]).await?.is_some();
            if exists { return reject_business(tx,StoreError::Conflict).await; }
            let used = usage(&tx,&session).await?;
            if used.retained_objects>=MAX_ACCOUNT_OBJECTS || used.live_bytes+payload.len() as i64>MAX_ACCOUNT_BYTES {
                return reject_business(tx,StoreError::Capacity).await;
            }
            let Some(expires) = now.checked_add(retention_ms) else { return reject_business(tx,StoreError::Invalid).await; };
            tx.execute("INSERT INTO rio_synthetic.cmv_objects \
                (account_id,owner_id,tenant_id,object_id,payload,digest,created_ms,expires_ms,state) \
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,'LIVE')",
                &[&session.account_id,&format!("owner-{}",session.account_id),&session.tenant_id,
                  &&object_id[..],&payload,&&digest[..],&now,&expires]).await?;
            tx.execute("INSERT INTO rio_synthetic.cmv_events VALUES($1,$2,0,'STORED',$3)",
                &[&session.account_id,&&object_id[..],&now]).await?;
            tx.commit().await?;
            Ok(digest)
        }).await
    }

    /// Read only the session's own live object; verify SHA-256 before releasing bytes.
    /// Missing, terminal and foreign IDs share the same rejection category.
    pub async fn read_cmv_object(
        &self,
        token_hash: Key,
        object_id: Key,
    ) -> Result<Vec<u8>, StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let session = match current_session(&tx, &token_hash).await {
                Ok(session) => session,
                Err(error) => return reject_business(tx, error).await,
            };
            expire(&tx, &session, now).await?;
            let row = tx
                .query_opt(
                    "SELECT payload,digest FROM rio_synthetic.cmv_objects \
                WHERE account_id=$1 AND tenant_id=$2 AND object_id=$3 AND state='LIVE'",
                    &[&session.account_id, &session.tenant_id, &&object_id[..]],
                )
                .await?;
            let Some(row) = row else {
                // Retain completed expiry and its event even when this read has no result.
                tx.commit().await?;
                return Err(StoreError::Forbidden);
            };
            let payload: Vec<u8> = row.try_get(0)?;
            let digest: Vec<u8> = row.try_get(1)?;
            if Sha256::digest(&payload)[..] != digest {
                return Err(StoreError::Unavailable);
            }
            tx.commit().await?;
            Ok(payload)
        })
        .await
    }

    /// Remove live bytes, preserving the immutable ID, digest and terminal audit event.
    pub async fn delete_cmv_object(
        &self,
        token_hash: Key,
        supplied_csrf: &str,
        object_id: Key,
    ) -> Result<(), StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let session = match current_session(&tx, &token_hash).await {
                Ok(session) => session,
                Err(error) => return reject_business(tx, error).await,
            };
            if !csrf_matches(&session.csrf, supplied_csrf) {
                return reject_business(tx, StoreError::Forbidden).await;
            }
            expire(&tx, &session, now).await?;
            let changed = tx
                .execute(
                    "UPDATE rio_synthetic.cmv_objects SET payload=''::bytea,state='DELETED' \
                WHERE account_id=$1 AND tenant_id=$2 AND object_id=$3 AND state='LIVE'",
                    &[&session.account_id, &session.tenant_id, &&object_id[..]],
                )
                .await?;
            if changed == 0 {
                tx.commit().await?;
                return Err(StoreError::Forbidden);
            }
            tx.execute(
                "INSERT INTO rio_synthetic.cmv_events VALUES($1,$2,1,'DELETED',$3)",
                &[&session.account_id, &&object_id[..], &now],
            )
            .await?;
            tx.commit().await?;
            Ok(())
        })
        .await
    }

    /// Sweep this authenticated account's expired bytes and return its usage.
    /// Physical expiry is lazy; all reads deny expired bytes before releasing them.
    pub async fn cmv_usage(&self, token_hash: Key) -> Result<Usage, StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let session = match current_session(&tx, &token_hash).await {
                Ok(session) => session,
                Err(error) => return reject_business(tx, error).await,
            };
            expire(&tx, &session, now).await?;
            let used = usage(&tx, &session).await?;
            tx.commit().await?;
            Ok(used)
        })
        .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn input_bounds() {
        assert!(!valid_input(&[], 1));
        assert!(!valid_input(&vec![0; MAX_OBJECT_BYTES + 1], 1));
        assert!(!valid_input(b"fixture", 0));
        assert!(!valid_input(b"fixture", MAX_RETENTION_MS + 1));
        assert!(valid_input(&vec![0; MAX_OBJECT_BYTES], MAX_RETENTION_MS));
    }
}
