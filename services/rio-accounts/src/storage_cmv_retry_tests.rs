//! Owned PostgreSQL proof of immutable retries, without exposing fixture rows.
use super::*;

fn key(label: &str) -> Key {
    Sha256::digest(label.as_bytes()).into()
}

async fn login(store: &PgStore, actor: &str) -> Result<(Key, String), StoreError> {
    let token = key(&crate::random_token());
    let csrf = crate::random_token();
    let transaction = key(&crate::random_token());
    let state = key(&crate::random_token());
    store.begin_login(transaction, state, None).await?;
    let permit = store.consume_login(transaction, state).await?;
    let subject = if actor == "TST-alpha" {
        "11111111-1111-4111-8111-111111111111"
    } else {
        "22222222-2222-4222-8222-222222222222"
    };
    store
        .replace_session_bound(permit, actor, crate::ISSUER, subject, token, csrf.clone())
        .await?;
    Ok((token, csrf))
}

async fn retained(store: &PgStore, token: Key, id: Key) -> Result<(i64, i64, Key), StoreError> {
    let catalog = store.cmv_catalog(token).await?;
    let item = catalog
        .objects
        .iter()
        .find(|item| item.object_id == id)
        .ok_or(StoreError::Invalid)?;
    Ok((item.created_ms, item.expires_ms, item.digest))
}

#[tokio::test]
#[ignore = "requires owned disposable synthetic PostgreSQL"]
async fn postgres_cmv_retry_contract() -> Result<(), StoreError> {
    let url = std::env::var("RIO_PG_TEST_URL").map_err(|_| StoreError::Invalid)?;
    let store = PgStore::connect_local(&url).await?;
    store.initialize_cmv_storage().await?;
    let peer = PgStore::connect_local(&url).await?;
    let (config, _) = local_config(&url)?;
    let (raw, connection) = config.connect(NoTls).await?;
    let task = tokio::spawn(async move {
        let _ = connection.await;
    });
    let (alpha, csrf_a) = login(&store, "TST-alpha").await?;
    let (beta, csrf_b) = login(&store, "TST-beta").await?;
    let before = store.cmv_catalog(beta).await?;
    // Alpha's IDs are independent of beta's namespace, even at alpha's full quota.
    let alpha_catalog = store.cmv_catalog(alpha).await?;
    let alpha_item = alpha_catalog
        .objects
        .iter()
        .find(|item| {
            item.state == "LIVE"
                && !before
                    .objects
                    .iter()
                    .any(|other| other.object_id == item.object_id)
        })
        .ok_or(StoreError::Invalid)?;
    let id = alpha_item.object_id;
    let alpha_bytes = store.read_cmv_object(alpha, id).await?;
    let payload = b"retry fixture";
    assert_eq!(
        store
            .put_cmv_object_retry(beta, &csrf_a, id, payload, MAX_RETENTION_MS)
            .await,
        Err(StoreError::Forbidden)
    );
    let (a, b) = tokio::join!(
        store.put_cmv_object_retry(beta, &csrf_b, id, payload, MAX_RETENTION_MS),
        peer.put_cmv_object_retry(beta, &csrf_b, id, payload, MAX_RETENTION_MS)
    );
    let (a, b) = (a?, b?);
    assert_ne!(
        a.created, b.created,
        "exactly one independent writer creates the object"
    );
    assert_eq!(a.digest, b.digest);
    assert_eq!(a.digest, key("retry fixture"));
    assert_eq!(store.read_cmv_object(alpha, id).await?, alpha_bytes);
    let original = retained(&store, beta, id).await?;
    let after = store.cmv_catalog(beta).await?;
    assert_eq!(
        after.usage.retained_objects,
        before.usage.retained_objects + 1
    );
    assert_eq!(
        after.usage.live_bytes,
        before.usage.live_bytes + payload.len() as i64
    );
    let reopened = PgStore::connect_local(&url).await?;
    for _ in 0..3 {
        assert!(
            !reopened
                .put_cmv_object_retry(beta, &csrf_b, id, payload, MAX_RETENTION_MS)
                .await?
                .created
        );
    }
    assert_eq!(
        retained(&store, beta, id).await?,
        original,
        "retry never renews the deadline"
    );
    let events: i64 = raw.query_one("SELECT count(*) FROM rio_synthetic.cmv_events WHERE account_id='TST-beta' AND object_id=$1",
        &[&id.to_vec()]).await?.try_get(0)?;
    assert_eq!(events, 1, "retries append no duplicate storage events");
    for (bytes, retention) in [
        (&b"changed"[..], MAX_RETENTION_MS),
        (&payload[..], MAX_RETENTION_MS - 1),
    ] {
        assert_eq!(
            store
                .put_cmv_object_retry(beta, &csrf_b, id, bytes, retention)
                .await,
            Err(StoreError::Conflict)
        );
    }
    assert_eq!(
        store
            .put_cmv_object(beta, &csrf_b, id, payload, MAX_RETENTION_MS)
            .await,
        Err(StoreError::Conflict),
        "the original create-only API keeps its conflict contract"
    );

    let changed_id = key("retry-concurrent-different");
    let (left, right) = tokio::join!(
        store.put_cmv_object_retry(beta, &csrf_b, changed_id, b"left", MAX_RETENTION_MS),
        peer.put_cmv_object_retry(beta, &csrf_b, changed_id, b"right", MAX_RETENTION_MS)
    );
    assert_eq!(
        [&left, &right]
            .iter()
            .filter(|r| r.as_ref().is_ok_and(|v| v.created))
            .count(),
        1
    );
    assert_eq!(
        [left, right]
            .iter()
            .filter(|r| **r == Err(StoreError::Conflict))
            .count(),
        1
    );
    store.delete_cmv_object(beta, &csrf_b, changed_id).await?;

    // Terminal IDs can never become live again, even with exactly the original request.
    let deleted = key("retry-deleted");
    store
        .put_cmv_object_retry(beta, &csrf_b, deleted, b"gone", MAX_RETENTION_MS)
        .await?;
    store.delete_cmv_object(beta, &csrf_b, deleted).await?;
    assert_eq!(
        store
            .put_cmv_object_retry(beta, &csrf_b, deleted, b"gone", MAX_RETENTION_MS)
            .await,
        Err(StoreError::Conflict)
    );
    let expired = key("retry-expired");
    store
        .put_cmv_object_retry(beta, &csrf_b, expired, b"expired", 1)
        .await?;
    tokio::time::sleep(Duration::from_millis(5)).await;
    assert_eq!(
        peer.put_cmv_object_retry(beta, &csrf_b, expired, b"expired", 1)
            .await,
        Err(StoreError::Conflict)
    );
    assert_eq!(
        store.read_cmv_object(beta, expired).await,
        Err(StoreError::Forbidden)
    );

    // Reconfirming an existing live object succeeds at a full byte budget.
    let mut fillers = Vec::new();
    loop {
        let remaining = MAX_ACCOUNT_BYTES - store.cmv_usage(beta).await?.live_bytes;
        if remaining == 0 {
            break;
        }
        let fill_id = key(&format!("retry-fill-{}", fillers.len()));
        store
            .put_cmv_object_retry(
                beta,
                &csrf_b,
                fill_id,
                &vec![7; remaining.min(MAX_OBJECT_BYTES as i64) as usize],
                MAX_RETENTION_MS,
            )
            .await?;
        fillers.push(fill_id);
        assert!(fillers.len() <= 4);
    }
    assert!(
        !peer
            .put_cmv_object_retry(beta, &csrf_b, id, payload, MAX_RETENTION_MS)
            .await?
            .created
    );
    assert_eq!(
        peer.put_cmv_object_retry(
            beta,
            &csrf_b,
            key("retry-over-bytes"),
            b"x",
            MAX_RETENTION_MS
        )
        .await,
        Err(StoreError::Capacity)
    );
    for fill_id in fillers {
        store.delete_cmv_object(beta, &csrf_b, fill_id).await?;
    }

    // Failed creation cannot commit bytes if the associated append-only event fails.
    let failed = PgStore::connect_local(&url).await?;
    let failed_id = key("retry-atomic-fault");
    raw.batch_execute("CREATE FUNCTION rio_synthetic.retry_test_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic fault'; END $$; CREATE TRIGGER retry_test_fault BEFORE INSERT ON rio_synthetic.cmv_events FOR EACH ROW EXECUTE FUNCTION rio_synthetic.retry_test_fault()").await?;
    assert_eq!(
        failed
            .put_cmv_object_retry(beta, &csrf_b, failed_id, b"rollback", MAX_RETENTION_MS)
            .await,
        Err(StoreError::Unavailable)
    );
    raw.batch_execute("DROP TRIGGER retry_test_fault ON rio_synthetic.cmv_events; DROP FUNCTION rio_synthetic.retry_test_fault()").await?;
    let leaked: i64 = raw.query_one("SELECT count(*) FROM rio_synthetic.cmv_objects WHERE account_id='TST-beta' AND object_id=$1", &[&failed_id.to_vec()]).await?.try_get(0)?;
    assert_eq!(leaked, 0);

    // Corruption or missing attributable creation audit closes acknowledgement and poisons the handle.
    for audit_fault in [false, true] {
        let corrupted = PgStore::connect_local(&url).await?;
        if audit_fault {
            raw.execute("UPDATE rio_synthetic.cmv_objects SET created_ms=created_ms+1,expires_ms=expires_ms+1 WHERE account_id='TST-beta' AND object_id=$1", &[&id.to_vec()]).await?;
        } else {
            raw.execute("UPDATE rio_synthetic.cmv_objects SET digest=$2 WHERE account_id='TST-beta' AND object_id=$1", &[&id.to_vec(), &vec![0u8;32]]).await?;
        }
        assert_eq!(
            corrupted
                .put_cmv_object_retry(beta, &csrf_b, id, payload, MAX_RETENTION_MS)
                .await,
            Err(StoreError::Unavailable)
        );
        assert_eq!(corrupted.health().await, Err(StoreError::Unavailable));
        raw.execute("UPDATE rio_synthetic.cmv_objects SET created_ms=$2,expires_ms=$3,digest=$4 WHERE account_id='TST-beta' AND object_id=$1", &[&id.to_vec(), &original.0, &original.1, &original.2.to_vec()]).await?;
    }

    // Retained tombstones bound metadata; retries need no new lifetime slots either.
    let count = store.cmv_usage(beta).await?.retained_objects;
    for n in count..MAX_ACCOUNT_OBJECTS {
        let fill_id = key(&format!("retry-retained-{n}"));
        store
            .put_cmv_object_retry(beta, &csrf_b, fill_id, b"x", MAX_RETENTION_MS)
            .await?;
        store.delete_cmv_object(beta, &csrf_b, fill_id).await?;
    }
    assert_eq!(
        store.cmv_usage(beta).await?.retained_objects,
        MAX_ACCOUNT_OBJECTS
    );
    assert!(
        !peer
            .put_cmv_object_retry(beta, &csrf_b, id, payload, MAX_RETENTION_MS)
            .await?
            .created
    );
    assert_eq!(
        peer.put_cmv_object_retry(
            beta,
            &csrf_b,
            key("retry-over-slots"),
            b"x",
            MAX_RETENTION_MS
        )
        .await,
        Err(StoreError::Capacity)
    );
    store.logout_all(beta, &csrf_b).await?;
    assert_eq!(
        peer.put_cmv_object_retry(beta, &csrf_b, id, payload, MAX_RETENTION_MS)
            .await,
        Err(StoreError::Revoked)
    );
    let (fresh, fresh_csrf) = login(&peer, "TST-beta").await?;
    assert!(
        !peer
            .put_cmv_object_retry(fresh, &fresh_csrf, id, payload, MAX_RETENTION_MS)
            .await?
            .created
    );
    store.recover_after_restore().await?;
    assert_eq!(
        peer.put_cmv_object_retry(fresh, &fresh_csrf, id, payload, MAX_RETENTION_MS)
            .await,
        Err(StoreError::Revoked)
    );
    let (restored, restored_csrf) = login(&peer, "TST-beta").await?;
    assert!(
        !peer
            .put_cmv_object_retry(restored, &restored_csrf, id, payload, MAX_RETENTION_MS)
            .await?
            .created
    );
    assert_eq!(retained(&peer, restored, id).await?, original);
    task.abort();
    Ok(())
}
