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

/// An account-owned catalog entry; never contains object bytes or credentials.
pub struct ObjectMetadata {
    /// Immutable opaque identifier.
    pub object_id: Key,
    /// Verified live digest, or the retained digest when bytes have been cleared.
    pub digest: Key,
    /// Bytes currently retained in the live payload budget.
    pub live_bytes: i64,
    /// Database creation timestamp.
    pub created_ms: i64,
    /// Original retention deadline.
    pub expires_ms: i64,
    /// Attributable terminal event time; absent for live entries.
    pub ended_ms: Option<i64>,
    /// Exactly LIVE, DELETED or EXPIRED.
    pub state: &'static str,
}

/// A bounded, transactionally consistent account inventory after lazy expiry.
pub struct Catalog {
    /// Database clock observation under the existing revocation/serialization fence.
    pub observed_ms: i64,
    /// All retained entries in ascending opaque-ID byte order, including tombstones.
    pub objects: Vec<ObjectMetadata>,
    /// Usage calculated from these exact entries; not a separate read.
    pub usage: Usage,
}

/// Outcome of a new immutable upload or an exactly matching live retry.
#[derive(Debug, PartialEq, Eq)]
pub struct WriteReceipt {
    /// SHA-256 of the acknowledged bytes.
    pub digest: Key,
    /// True only for the transaction that created the object and its audit event.
    pub created: bool,
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

async fn catalog_snapshot(
    tx: &Transaction<'_>,
    session: &SessionRecord,
    now: i64,
) -> Result<Catalog, StoreError> {
    // A single statement snapshot includes both object metadata and its audit.
    // The extra row detects capacity violations; a partial catalog is never returned.
    let rows=tx.query("SELECT o.object_id,o.payload,o.digest,o.created_ms,o.expires_ms,o.state, \
        EXISTS(SELECT 1 FROM rio_synthetic.cmv_events e WHERE e.account_id=o.account_id \
            AND e.object_id=o.object_id AND e.phase=0 AND e.event_type='STORED' AND e.at_ms=o.created_ms) AS stored, \
        (SELECT e.at_ms FROM rio_synthetic.cmv_events e WHERE e.account_id=o.account_id \
            AND e.object_id=o.object_id AND e.phase=1) AS ended_ms, \
        EXISTS(SELECT 1 FROM rio_synthetic.cmv_events e WHERE e.account_id=o.account_id \
            AND e.object_id=o.object_id AND e.phase=1 AND e.event_type=o.state \
            AND e.at_ms BETWEEN o.created_ms AND $4 AND \
            ((o.state='EXPIRED' AND e.at_ms>=o.expires_ms) OR (o.state='DELETED' AND e.at_ms<o.expires_ms))) AS closed \
        FROM rio_synthetic.cmv_objects o WHERE o.account_id=$1 AND o.tenant_id=$2 \
        ORDER BY o.object_id LIMIT $3",
        &[&session.account_id,&session.tenant_id,&(MAX_ACCOUNT_OBJECTS+1),&now]).await?;
    if rows.len() as i64 > MAX_ACCOUNT_OBJECTS {
        return Err(StoreError::Unavailable);
    }
    let mut objects = Vec::with_capacity(rows.len());
    let mut live_bytes = 0_i64;
    for row in rows {
        let object_id: Vec<u8> = row.try_get("object_id")?;
        let digest: Vec<u8> = row.try_get("digest")?;
        let payload: Vec<u8> = row.try_get("payload")?;
        let created_ms: i64 = row.try_get("created_ms")?;
        let expires_ms: i64 = row.try_get("expires_ms")?;
        let ended_ms: Option<i64> = row.try_get("ended_ms")?;
        let state: String = row.try_get("state")?;
        let state = match state.as_str() {
            "LIVE" => "LIVE",
            "DELETED" => "DELETED",
            "EXPIRED" => "EXPIRED",
            _ => return Err(StoreError::Unavailable),
        };
        let live = state == "LIVE";
        if !row.try_get::<_, bool>("stored")?
            || created_ms < 0
            || created_ms > now
            || !expires_ms
                .checked_sub(created_ms)
                .is_some_and(|ms| (1..=MAX_RETENTION_MS).contains(&ms))
            || (live
                && (ended_ms.is_some()
                    || expires_ms <= now
                    || payload.is_empty()
                    || payload.len() > MAX_OBJECT_BYTES
                    || Sha256::digest(&payload)[..] != digest))
            || (!live
                && (!payload.is_empty()
                    || ended_ms.is_none()
                    || !row.try_get::<_, bool>("closed")?))
        {
            return Err(StoreError::Unavailable);
        }
        live_bytes += payload.len() as i64;
        if live_bytes > MAX_ACCOUNT_BYTES {
            return Err(StoreError::Unavailable);
        }
        objects.push(ObjectMetadata {
            object_id: object_id.try_into().map_err(|_| StoreError::Unavailable)?,
            digest: digest.try_into().map_err(|_| StoreError::Unavailable)?,
            live_bytes: payload.len() as i64,
            created_ms,
            expires_ms,
            ended_ms,
            state,
        });
    }
    let catalog = Catalog {
        observed_ms: now,
        usage: Usage {
            live_bytes,
            retained_objects: objects.len() as i64,
        },
        objects,
    };
    Ok(catalog)
}

impl PgStore {
    /// Recover the caller's complete catalog without releasing payload bytes.
    /// Verify live hashes and lifecycle/audit consistency before releasing any entry.
    /// Malformed or over-budget inventories close access instead of truncating data.
    pub async fn cmv_catalog(&self, token_hash: Key) -> Result<Catalog, StoreError> {
        self.timed(async {
            let mut client = self.inner.client.lock().await;
            let tx = client.transaction().await?;
            let now = locked(&tx).await?;
            let session = match current_session(&tx, &token_hash).await {
                Ok(session) => session,
                Err(error) => return reject_business(tx, error).await,
            };
            expire(&tx, &session, now).await?;
            let catalog = catalog_snapshot(&tx, &session, now).await?;
            tx.commit().await?;
            Ok(catalog)
        })
        .await
    }

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

    /// Create or confirm an identical live object after an uncertain network outcome.
    /// A retry validates the complete catalog and exact bytes under the same guard.
    /// It consumes no extra quota/event and never changes the original deadline.
    /// Terminal IDs, changed bytes and changed original retention remain conflicts.
    pub async fn put_cmv_object_retry(
        &self,
        token_hash: Key,
        supplied_csrf: &str,
        object_id: Key,
        payload: &[u8],
        retention_ms: i64,
    ) -> Result<WriteReceipt, StoreError> {
        if !valid_input(payload, retention_ms) {
            return Err(StoreError::Invalid);
        }
        let digest: Key = Sha256::digest(payload).into();
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
            let catalog = catalog_snapshot(&tx, &session, now).await?;
            if let Some(item) = catalog.objects.iter().find(|item| item.object_id == object_id) {
                if item.state != "LIVE" || item.digest != digest
                    || item.expires_ms.checked_sub(item.created_ms) != Some(retention_ms) {
                    return reject_business(tx, StoreError::Conflict).await;
                }
                // Compare exact bytes as well as their verified digest; no hash-only replay.
                let stored: Vec<u8> = tx.query_one(
                    "SELECT payload FROM rio_synthetic.cmv_objects WHERE account_id=$1 AND tenant_id=$2 AND object_id=$3",
                    &[&session.account_id, &session.tenant_id, &&object_id[..]],
                ).await?.try_get(0)?;
                if stored != payload { return reject_business(tx, StoreError::Conflict).await; }
                tx.commit().await?;
                return Ok(WriteReceipt { digest, created: false });
            }
            let used = catalog.usage;
            if used.retained_objects >= MAX_ACCOUNT_OBJECTS
                || used.live_bytes + payload.len() as i64 > MAX_ACCOUNT_BYTES {
                return reject_business(tx, StoreError::Capacity).await;
            }
            let Some(expires) = now.checked_add(retention_ms) else {
                return reject_business(tx, StoreError::Invalid).await;
            };
            tx.execute("INSERT INTO rio_synthetic.cmv_objects \
                (account_id,owner_id,tenant_id,object_id,payload,digest,created_ms,expires_ms,state) \
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,'LIVE')",
                &[&session.account_id, &format!("owner-{}", session.account_id), &session.tenant_id,
                  &&object_id[..], &payload, &&digest[..], &now, &expires]).await?;
            tx.execute("INSERT INTO rio_synthetic.cmv_events VALUES($1,$2,0,'STORED',$3)",
                &[&session.account_id, &&object_id[..], &now]).await?;
            tx.commit().await?;
            Ok(WriteReceipt { digest, created: true })
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

#[cfg(test)]
#[path = "../storage_cmv_catalog_tests.rs"]
mod catalog_tests;

#[cfg(test)]
#[path = "../storage_cmv_retry_tests.rs"]
mod retry_tests;
