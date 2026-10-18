//! Owned PostgreSQL catalog proof, with fixed summaries rather than private rows.
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

fn entry(catalog: &Catalog, id: Key) -> Result<&ObjectMetadata, StoreError> {
    catalog
        .objects
        .iter()
        .find(|o| o.object_id == id)
        .ok_or(StoreError::Invalid)
}

#[tokio::test]
#[ignore = "requires owned disposable synthetic PostgreSQL"]
async fn postgres_cmv_catalog_contract() -> Result<(), StoreError> {
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
    let live = key("catalog-live");
    let deleted = key("catalog-deleted");
    let expired = key("catalog-expired");
    store
        .put_cmv_object(beta, &csrf_b, live, b"recoverable fixture", 60_000)
        .await?;
    store
        .put_cmv_object(beta, &csrf_b, deleted, b"delete fixture", 60_000)
        .await?;
    store.delete_cmv_object(beta, &csrf_b, deleted).await?;
    store
        .put_cmv_object(beta, &csrf_b, expired, b"expire fixture", 1)
        .await?;
    tokio::time::sleep(Duration::from_millis(5)).await;
    let catalog = peer.cmv_catalog(beta).await?;
    assert_eq!(catalog.usage.retained_objects, catalog.objects.len() as i64);
    assert_eq!(
        catalog.usage.live_bytes,
        catalog.objects.iter().map(|o| o.live_bytes).sum::<i64>()
    );
    assert!(
        catalog
            .objects
            .windows(2)
            .all(|pair| pair[0].object_id < pair[1].object_id)
    );
    let item = entry(&catalog, live)?;
    assert_eq!(item.state, "LIVE");
    assert_eq!(item.live_bytes, 19);
    assert!(item.ended_ms.is_none());
    assert_eq!(item.digest, key("recoverable fixture"));
    for (id, state) in [(deleted, "DELETED"), (expired, "EXPIRED")] {
        let item = entry(&catalog, id)?;
        assert_eq!(item.state, state);
        assert_eq!(item.live_bytes, 0);
        assert!(
            item.ended_ms
                .is_some_and(|at| at >= item.created_ms && at <= catalog.observed_ms)
        );
    }
    let expired_item = entry(&catalog, expired)?;
    assert!(
        expired_item
            .ended_ms
            .is_some_and(|at| at >= expired_item.expires_ms)
    );
    assert!(
        store
            .cmv_catalog(alpha)
            .await?
            .objects
            .iter()
            .all(|o| o.object_id != live)
    );
    let audits: i64 = raw
        .query_one("SELECT count(*) FROM rio_synthetic.cmv_events", &[])
        .await?
        .try_get(0)?;
    let reopened = PgStore::connect_local(&url).await?;
    assert_eq!(
        entry(&reopened.cmv_catalog(beta).await?, live)?.state,
        "LIVE"
    );
    let after: i64 = raw
        .query_one("SELECT count(*) FROM rio_synthetic.cmv_events", &[])
        .await?
        .try_get(0)?;
    assert_eq!(
        audits, after,
        "non-expiring catalog reads append no events and allocate no slots"
    );

    // Fill any remaining alpha lifetime slots, then prove the full catalog is recoverable.
    let count = store.cmv_catalog(alpha).await?.usage.retained_objects;
    for n in count..MAX_ACCOUNT_OBJECTS {
        let id = key(&format!("catalog-slot-{n}"));
        store
            .put_cmv_object(alpha, &csrf_a, id, b"x", 60_000)
            .await?;
        store.delete_cmv_object(alpha, &csrf_a, id).await?;
    }
    assert_eq!(
        store.cmv_catalog(alpha).await?.objects.len(),
        MAX_ACCOUNT_OBJECTS as usize
    );

    // Independent clients expose either the whole committed new object+audit or no new entry.
    let concurrent = key("catalog-concurrent");
    let (created, listed) = tokio::join!(
        store.put_cmv_object(beta, &csrf_b, concurrent, b"atomic", 60_000),
        peer.cmv_catalog(beta)
    );
    created?;
    let listed = listed?;
    if let Some(item) = listed.objects.iter().find(|o| o.object_id == concurrent) {
        assert_eq!(item.state, "LIVE");
    }

    // Privileged fixture faults must not leak a partial or falsely verified catalog.
    let corrupted = PgStore::connect_local(&url).await?;
    raw.execute("UPDATE rio_synthetic.cmv_objects SET digest=$2 WHERE account_id='TST-beta' AND object_id=$1",
        &[&live.to_vec(),&vec![0u8;32]]).await?;
    assert_eq!(
        corrupted.cmv_catalog(beta).await.err(),
        Some(StoreError::Unavailable)
    );
    assert_eq!(
        corrupted.health().await.err(),
        Some(StoreError::Unavailable)
    );
    raw.execute("UPDATE rio_synthetic.cmv_objects SET digest=$2 WHERE account_id='TST-beta' AND object_id=$1",
        &[&live.to_vec(),&key("recoverable fixture").to_vec()]).await?;
    let unaudited = PgStore::connect_local(&url).await?;
    raw.execute(
        "UPDATE rio_synthetic.cmv_objects SET state='DELETED',payload=''::bytea \
        WHERE account_id='TST-beta' AND object_id=$1",
        &[&live.to_vec()],
    )
    .await?;
    assert_eq!(
        unaudited.cmv_catalog(beta).await.err(),
        Some(StoreError::Unavailable)
    );
    raw.execute(
        "UPDATE rio_synthetic.cmv_objects SET state='LIVE',payload=$2 \
        WHERE account_id='TST-beta' AND object_id=$1",
        &[&live.to_vec(), &&b"recoverable fixture"[..]],
    )
    .await?;
    assert_eq!(entry(&store.cmv_catalog(beta).await?, live)?.state, "LIVE");

    store.logout_all(beta, &csrf_b).await?;
    assert_eq!(
        peer.cmv_catalog(beta).await.err(),
        Some(StoreError::Revoked)
    );
    assert!(peer.cmv_catalog(alpha).await.is_ok());
    store.recover_after_restore().await?;
    assert_eq!(
        peer.cmv_catalog(alpha).await.err(),
        Some(StoreError::Revoked)
    );
    let (fresh, _) = login(&peer, "TST-beta").await?;
    assert_eq!(entry(&peer.cmv_catalog(fresh).await?, live)?.state, "LIVE");
    task.abort();
    Ok(())
}
