//! Owned PostgreSQL proof of conditional erasure and audit-consistent reads.
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

async fn event_count(raw: &Client, id: Key) -> Result<i64, StoreError> {
    Ok(raw.query_one("SELECT count(*) FROM rio_synthetic.cmv_events WHERE account_id='TST-beta' AND object_id=$1",
        &[&id.to_vec()]).await?.try_get(0)?)
}

#[tokio::test]
#[ignore = "requires owned disposable synthetic PostgreSQL after the catalog proof"]
async fn postgres_cmv_delete_contract() -> Result<(), StoreError> {
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
    let id = key("checked-delete-owned");
    let payload = b"delete this fixture";
    let digest = store
        .put_cmv_object(beta, &csrf_b, id, payload, MAX_RETENTION_MS)
        .await?;
    let before = store.cmv_usage(beta).await?;
    assert_eq!(
        store
            .delete_cmv_object_checked(beta, &csrf_a, id, digest)
            .await,
        Err(StoreError::Forbidden)
    );
    assert_eq!(
        store
            .delete_cmv_object_checked(alpha, &csrf_a, id, digest)
            .await,
        Err(StoreError::Forbidden)
    );
    assert_eq!(
        store
            .delete_cmv_object_checked(beta, &csrf_b, key("checked-delete-missing"), digest)
            .await,
        Err(StoreError::Forbidden)
    );
    assert_eq!(
        store
            .delete_cmv_object_checked(beta, &csrf_b, id, [0; 32])
            .await,
        Err(StoreError::Conflict)
    );
    assert_eq!(store.read_cmv_object(beta, id).await?, payload);
    let (first, concurrent) = tokio::join!(
        store.delete_cmv_object_checked(beta, &csrf_b, id, digest),
        peer.delete_cmv_object_checked(beta, &csrf_b, id, digest)
    );
    let first = first?;
    assert_eq!(
        first, concurrent?,
        "independent deletions share the original terminal event"
    );
    assert_eq!(first.state, "DELETED");
    assert_eq!(first.digest, digest);
    assert_eq!(
        first.usage.live_bytes,
        before.live_bytes - payload.len() as i64
    );
    assert_eq!(first.usage.retained_objects, before.retained_objects);
    assert_eq!(store.cmv_usage(beta).await?, first.usage);
    assert_eq!(event_count(&raw, id).await?, 2);
    let reopened = PgStore::connect_local(&url).await?;
    assert_eq!(
        reopened
            .delete_cmv_object_checked(beta, &csrf_b, id, digest)
            .await?,
        first
    );
    assert_eq!(
        store
            .delete_cmv_object_checked(beta, &csrf_b, id, [0; 32])
            .await,
        Err(StoreError::Conflict)
    );
    assert_eq!(
        store.delete_cmv_object(beta, &csrf_b, id).await,
        Err(StoreError::Forbidden),
        "legacy deletion remains live-only"
    );
    assert_eq!(
        store
            .put_cmv_object_retry(beta, &csrf_b, id, payload, MAX_RETENTION_MS)
            .await,
        Err(StoreError::Conflict)
    );
    assert_eq!(
        event_count(&raw, id).await?,
        2,
        "confirmation adds no audit event"
    );
    let row = raw.query_one("SELECT state,octet_length(payload), \
        (SELECT at_ms FROM rio_synthetic.cmv_events e WHERE e.account_id=o.account_id AND e.object_id=o.object_id AND phase=1) \
        FROM rio_synthetic.cmv_objects o WHERE account_id='TST-beta' AND object_id=$1", &[&id.to_vec()]).await?;
    assert_eq!(row.try_get::<_, String>(0)?, "DELETED");
    assert_eq!(row.try_get::<_, i32>(1)?, 0);
    assert_eq!(row.try_get::<_, i64>(2)?, first.ended_ms);

    let expired = key("checked-delete-expired");
    let expired_digest = store
        .put_cmv_object(beta, &csrf_b, expired, b"expires", 1)
        .await?;
    tokio::time::sleep(Duration::from_millis(5)).await;
    let expiry = store
        .delete_cmv_object_checked(beta, &csrf_b, expired, expired_digest)
        .await?;
    assert_eq!(
        expiry.state, "EXPIRED",
        "expiry is never relabelled as user deletion"
    );
    assert_eq!(
        peer.delete_cmv_object_checked(beta, &csrf_b, expired, expired_digest)
            .await?,
        expiry
    );
    assert_eq!(event_count(&raw, expired).await?, 2);
    let deadline: i64 = raw.query_one("SELECT expires_ms FROM rio_synthetic.cmv_objects WHERE account_id='TST-beta' AND object_id=$1", &[&expired.to_vec()]).await?.try_get(0)?;
    assert!(expiry.ended_ms >= deadline);

    // The preceding owned catalog proof filled alpha's 64 lifetime slots.
    let full = store.cmv_catalog(alpha).await?;
    assert_eq!(full.usage.retained_objects, MAX_ACCOUNT_OBJECTS);
    let item = full
        .objects
        .iter()
        .find(|item| item.state == "LIVE")
        .ok_or(StoreError::Invalid)?;
    let at_limit = store
        .delete_cmv_object_checked(alpha, &csrf_a, item.object_id, item.digest)
        .await?;
    assert_eq!(at_limit.usage.retained_objects, MAX_ACCOUNT_OBJECTS);
    assert_eq!(
        peer.delete_cmv_object_checked(alpha, &csrf_a, item.object_id, item.digest)
            .await?,
        at_limit
    );

    // A terminal audit failure must roll back both state transition and cleared bytes.
    let fault_id = key("checked-delete-audit-fault");
    let fault_bytes = b"atomic erase fixture";
    let fault_digest = store
        .put_cmv_object(beta, &csrf_b, fault_id, fault_bytes, MAX_RETENTION_MS)
        .await?;
    raw.batch_execute("CREATE FUNCTION rio_synthetic.delete_test_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic fault'; END $$; CREATE TRIGGER delete_test_fault BEFORE INSERT ON rio_synthetic.cmv_events FOR EACH ROW WHEN (NEW.event_type='DELETED') EXECUTE FUNCTION rio_synthetic.delete_test_fault()").await?;
    let failing = PgStore::connect_local(&url).await?;
    assert_eq!(
        failing
            .delete_cmv_object_checked(beta, &csrf_b, fault_id, fault_digest)
            .await,
        Err(StoreError::Unavailable)
    );
    assert_eq!(failing.health().await, Err(StoreError::Unavailable));
    raw.batch_execute("DROP TRIGGER delete_test_fault ON rio_synthetic.cmv_events; DROP FUNCTION rio_synthetic.delete_test_fault()").await?;
    assert_eq!(peer.read_cmv_object(beta, fault_id).await?, fault_bytes);
    assert_eq!(event_count(&raw, fault_id).await?, 1);

    // Every byte/quota/mutation path checks the same catalog before acknowledgement.
    // Repair only this owned injected row; never alter or erase append-only audit.
    let original = raw.query_one("SELECT created_ms,expires_ms FROM rio_synthetic.cmv_objects WHERE account_id='TST-beta' AND object_id=$1", &[&fault_id.to_vec()]).await?;
    let created: i64 = original.try_get(0)?;
    let expires: i64 = original.try_get(1)?;
    for audit_fault in [false, true] {
        if audit_fault {
            raw.execute("UPDATE rio_synthetic.cmv_objects SET created_ms=created_ms-1,expires_ms=expires_ms-1 WHERE account_id='TST-beta' AND object_id=$1", &[&fault_id.to_vec()]).await?;
        } else {
            raw.execute("UPDATE rio_synthetic.cmv_objects SET digest=$2 WHERE account_id='TST-beta' AND object_id=$1", &[&fault_id.to_vec(), &vec![0u8;32]]).await?;
        }
        for operation in 0..6 {
            let bad = PgStore::connect_local(&url).await?;
            let error = match operation {
                0 => bad.read_cmv_object(beta, fault_id).await.err(),
                1 => bad.cmv_usage(beta).await.err(),
                2 => bad.delete_cmv_object(beta, &csrf_b, fault_id).await.err(),
                3 => bad
                    .delete_cmv_object_checked(beta, &csrf_b, fault_id, fault_digest)
                    .await
                    .err(),
                4 => bad
                    .put_cmv_object(
                        beta,
                        &csrf_b,
                        key("checked-delete-no-new-post"),
                        b"x",
                        MAX_RETENTION_MS,
                    )
                    .await
                    .err(),
                _ => bad
                    .put_cmv_object_retry(
                        beta,
                        &csrf_b,
                        key("checked-delete-no-new-put"),
                        b"x",
                        MAX_RETENTION_MS,
                    )
                    .await
                    .err(),
            };
            assert_eq!(error, Some(StoreError::Unavailable));
            assert_eq!(bad.health().await, Err(StoreError::Unavailable));
        }
        raw.execute("UPDATE rio_synthetic.cmv_objects SET created_ms=$2,expires_ms=$3,digest=$4 WHERE account_id='TST-beta' AND object_id=$1", &[&fault_id.to_vec(), &created, &expires, &fault_digest.to_vec()]).await?;
    }
    assert_eq!(store.read_cmv_object(beta, fault_id).await?, fault_bytes);
    assert_eq!(event_count(&raw, fault_id).await?, 1);
    store
        .delete_cmv_object_checked(beta, &csrf_b, fault_id, fault_digest)
        .await?;

    store.logout_all(beta, &csrf_b).await?;
    assert_eq!(
        peer.delete_cmv_object_checked(beta, &csrf_b, id, digest)
            .await,
        Err(StoreError::Revoked)
    );
    let (fresh, fresh_csrf) = login(&peer, "TST-beta").await?;
    let fresh_receipt = peer
        .delete_cmv_object_checked(fresh, &fresh_csrf, id, digest)
        .await?;
    assert_eq!(fresh_receipt.ended_ms, first.ended_ms);
    store.recover_after_restore().await?;
    assert_eq!(
        peer.delete_cmv_object_checked(fresh, &fresh_csrf, id, digest)
            .await,
        Err(StoreError::Revoked)
    );
    let (restored, restored_csrf) = login(&peer, "TST-beta").await?;
    let restored_receipt = peer
        .delete_cmv_object_checked(restored, &restored_csrf, id, digest)
        .await?;
    assert_eq!(restored_receipt.state, "DELETED");
    assert_eq!(restored_receipt.ended_ms, first.ended_ms);
    assert_eq!(event_count(&raw, id).await?, 2);
    task.abort();
    Ok(())
}
