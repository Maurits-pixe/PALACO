use super::*;
use crate::{
    ISSUER, ORIGIN, router, router_with_cmv_storage,
    storage::{PgStore, StoreError},
};
use axum::{
    body::{Body, to_bytes},
    http::Request,
    response::Response,
};
use std::sync::Arc;
use tower::ServiceExt;
type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;

async fn call(
    app: &Router,
    method: &str,
    path: &str,
    token: Option<&str>,
    csrf: Option<&str>,
    origin: Option<&str>,
    body: &str,
) -> Result<Response, Box<dyn std::error::Error + Send + Sync>> {
    let mut request = Request::builder()
        .method(method)
        .uri(path)
        .header("host", "localhost:8088")
        .header("content-type", "application/json");
    if let Some(token) = token {
        request = request.header("cookie", format!("{SESSION_COOKIE}={token}"));
    }
    if let Some(csrf) = csrf {
        request = request.header("x-csrf-token", csrf);
    }
    if let Some(origin) = origin {
        request = request.header("origin", origin);
    }
    Ok(app
        .clone()
        .oneshot(request.body(Body::from(body.to_owned()))?)
        .await?)
}

fn put_body(id: &str, payload: &[u8], retention: i64) -> String {
    json!({"objectId":id,"payload":URL_SAFE_NO_PAD.encode(payload),"retentionMs":retention})
        .to_string()
}

async fn document(
    response: Response,
    status: StatusCode,
) -> Result<Value, Box<dyn std::error::Error + Send + Sync>> {
    assert_eq!(response.status(), status);
    assert_eq!(
        response
            .headers()
            .get("cache-control")
            .and_then(|v| v.to_str().ok()),
        Some("no-store")
    );
    assert_eq!(
        response
            .headers()
            .get("x-content-type-options")
            .and_then(|v| v.to_str().ok()),
        Some("nosniff")
    );
    assert!(
        !response
            .headers()
            .contains_key("access-control-allow-origin")
    );
    let data: Value = serde_json::from_slice(&to_bytes(response.into_body(), 32_768).await?)?;
    assert_eq!(data["mode"], "SYNTHETIC_ONLY");
    assert_eq!(data["accountActive"], false);
    assert_eq!(data["canOpenContact"], false);
    assert_eq!(data["operativeAuthority"], "NONE");
    assert!(data.get("csrfToken").is_none());
    assert!(data.get("accountId").is_none());
    Ok(data)
}

async fn inventory(
    app: &Router,
    token: &str,
) -> Result<Value, Box<dyn std::error::Error + Send + Sync>> {
    let data = document(
        call(
            app,
            "GET",
            "/api/storage/objects",
            Some(token),
            None,
            None,
            "",
        )
        .await?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(data["schema"], "RIO_CMV_SYNTHETIC_CATALOG_V1");
    let items = data["objects"].as_array().ok_or("catalog missing")?;
    assert!(items.len() <= MAX_ACCOUNT_OBJECTS as usize);
    assert_eq!(data["usage"]["retainedObjects"], items.len());
    let mut bytes = 0;
    for item in items {
        assert!(item.get("payload").is_none());
        assert!(item.get("accountId").is_none());
        assert!(item.get("ownerId").is_none());
        bytes += item["liveBytes"]
            .as_u64()
            .ok_or("invalid catalog byte count")?;
    }
    assert_eq!(data["usage"]["liveBytes"], bytes);
    Ok(data)
}

#[tokio::test]
async fn http_storage_is_opt_in_strict_bounded_and_never_uses_memory() -> TestResult {
    let state = crate::tests::test_state()?;
    assert!(router_with_cmv_storage(state.clone()).await.is_err());
    let default = router(state.clone());
    for path in [
        "/api/storage/document-exchange.mjs",
        "/api/storage/client.mjs",
    ] {
        assert_eq!(
            call(&default, "GET", path, None, None, None, "")
                .await?
                .status(),
            StatusCode::NOT_FOUND
        );
    }
    assert_eq!(
        call(&default, "GET", "/api/storage/usage", None, None, None, "")
            .await?
            .status(),
        StatusCode::NOT_FOUND
    );
    let app = crate::router_with_routes(state, routes());
    for path in [
        "/api/storage/document-exchange.mjs",
        "/api/storage/client.mjs",
    ] {
        let response = call(&app, "GET", path, None, None, None, "").await?;
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response
                .headers()
                .get("content-type")
                .and_then(|v| v.to_str().ok()),
            Some("text/javascript; charset=utf-8")
        );
        assert_eq!(
            response
                .headers()
                .get("cache-control")
                .and_then(|v| v.to_str().ok()),
            Some("no-store")
        );
    }
    let token = crate::random_token();
    let csrf = crate::random_token();
    assert_eq!(
        call(&app, "GET", "/api/storage/objects", None, None, None, "")
            .await?
            .status(),
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        call(
            &app,
            "GET",
            "/api/storage/objects",
            Some(&token),
            None,
            None,
            ""
        )
        .await?
        .status(),
        StatusCode::SERVICE_UNAVAILABLE
    );
    assert_eq!(
        call(
            &app,
            "GET",
            "/api/storage/objects?accountId=TST-beta",
            Some(&token),
            None,
            None,
            ""
        )
        .await?
        .status(),
        StatusCode::BAD_REQUEST
    );
    let id = URL_SAFE_NO_PAD.encode([7; 32]);
    let valid = put_body(&id, b"fixture", 60_000);
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/storage/objects",
            None,
            Some(&csrf),
            Some(ORIGIN),
            &valid
        )
        .await?
        .status(),
        StatusCode::UNAUTHORIZED
    );
    for origin in [None, Some("https://attacker.example")] {
        assert_eq!(
            call(
                &app,
                "POST",
                "/api/storage/objects",
                Some(&token),
                Some(&csrf),
                origin,
                &valid
            )
            .await?
            .status(),
            StatusCode::FORBIDDEN
        );
    }
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/storage/objects",
            Some(&token),
            None,
            Some(ORIGIN),
            &valid
        )
        .await?
        .status(),
        StatusCode::FORBIDDEN
    );
    for body in [
        format!(r#"["{id}","Zg",1]"#),
        valid.replace("\"retentionMs\":60000", "\"retentionMs\":0"),
        valid.replace("\"retentionMs\":60000", "\"retentionMs\":86400001"),
        valid.replace("\"retentionMs\":60000", "\"retentionMs\":1.5"),
        valid.replace("\"retentionMs\":60000", "\"retentionMs\":true"),
        format!(r#"{{"objectId":"{id}","payload":"Zg","retentionMs":1,"accountId":"TST-beta"}}"#),
        format!(r#"{{"objectId":"{id}","payload":"Zg","retentionMs":1,"retentionMs":2}}"#),
        put_body(&format!("{id}="), b"fixture", 1),
        put_body("short", b"fixture", 1),
        put_body(&id, b"", 1),
        put_body(&id, &vec![0; MAX_OBJECT_BYTES + 1], 1),
        format!(r#"{{"objectId":"{id}","payload":"Zh","retentionMs":1}}"#),
    ] {
        assert_eq!(
            call(
                &app,
                "POST",
                "/api/storage/objects",
                Some(&token),
                Some(&csrf),
                Some(ORIGIN),
                &body
            )
            .await?
            .status(),
            StatusCode::BAD_REQUEST
        );
    }
    // The route-local budget accepts a full-size object, without widening consent/logout bodies.
    let full = put_body(&id, &vec![3; MAX_OBJECT_BYTES], 60_000);
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/storage/objects",
            Some(&token),
            Some(&csrf),
            Some(ORIGIN),
            &full
        )
        .await?
        .status(),
        StatusCode::SERVICE_UNAVAILABLE
    );
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/consent",
            Some(&token),
            Some(&csrf),
            Some(ORIGIN),
            &full
        )
        .await?
        .status(),
        StatusCode::PAYLOAD_TOO_LARGE
    );
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/storage/objects",
            Some(&token),
            Some(&csrf),
            Some(ORIGIN),
            &" ".repeat(BODY_LIMIT + 1)
        )
        .await?
        .status(),
        StatusCode::PAYLOAD_TOO_LARGE
    );
    assert_eq!(
        call(
            &app,
            "GET",
            "/api/storage/usage?accountId=TST-beta",
            Some(&token),
            None,
            None,
            ""
        )
        .await?
        .status(),
        StatusCode::BAD_REQUEST
    );
    for (name, value) in [
        ("host", "attacker.example"),
        ("authorization", "Bearer fake"),
        ("x-forwarded-host", "localhost:8088"),
        ("origin", ORIGIN),
        ("x-csrf-token", &csrf),
    ] {
        let request = Request::builder()
            .method("POST")
            .uri("/api/storage/objects")
            .header("host", "localhost:8088")
            .header("content-type", "application/json")
            .header("origin", ORIGIN)
            .header("x-csrf-token", &csrf)
            .header("cookie", format!("{SESSION_COOKIE}={token}"))
            .header(name, value)
            .body(Body::from(valid.clone()))?;
        assert!(matches!(
            app.clone().oneshot(request).await?.status(),
            StatusCode::BAD_REQUEST | StatusCode::FORBIDDEN
        ));
    }
    assert!(decode("Zg=", MAX_OBJECT_BYTES).is_err());
    assert!(decode("Zh", MAX_OBJECT_BYTES).is_err());
    for body in ["[]", "null", r#"{"accountId":"TST-beta"}"#] {
        assert_eq!(
            call(
                &app,
                "DELETE",
                &format!("/api/storage/objects/{id}"),
                Some(&token),
                Some(&csrf),
                Some(ORIGIN),
                body
            )
            .await?
            .status(),
            StatusCode::BAD_REQUEST
        );
    }
    Ok(())
}

async fn seed(db: &PgStore, actor: &str) -> Result<(String, String), StoreError> {
    let token = crate::random_token();
    let csrf = crate::random_token();
    let transaction = hash(&crate::random_token());
    let state = hash(&crate::random_token());
    db.begin_login(transaction, state, None).await?;
    let permit = db.consume_login(transaction, state).await?;
    let subject = if actor == "TST-alpha" {
        "11111111-1111-4111-8111-111111111111"
    } else {
        "22222222-2222-4222-8222-222222222222"
    };
    db.replace_session_bound(permit, actor, ISSUER, subject, hash(&token), csrf.clone())
        .await?;
    Ok((token, csrf))
}

#[tokio::test]
async fn retry_upload_has_strict_input_and_method_local_body_limits() -> TestResult {
    let state = crate::tests::test_state()?;
    let token = crate::random_token();
    let csrf = crate::random_token();
    let id = crate::random_token();
    let path = format!("/api/storage/objects/{id}");
    let valid = json!({"payload":"Zg","retentionMs":60000}).to_string();
    assert_eq!(
        call(
            &router(state.clone()),
            "PUT",
            &path,
            Some(&token),
            Some(&csrf),
            Some(ORIGIN),
            &valid
        )
        .await?
        .status(),
        StatusCode::NOT_FOUND
    );
    let app = crate::router_with_routes(state, routes());
    for (cookie, csrf, origin, status) in [
        (
            None,
            Some(csrf.as_str()),
            Some(ORIGIN),
            StatusCode::UNAUTHORIZED,
        ),
        (
            Some(token.as_str()),
            None,
            Some(ORIGIN),
            StatusCode::FORBIDDEN,
        ),
        (
            Some(token.as_str()),
            Some(csrf.as_str()),
            None,
            StatusCode::FORBIDDEN,
        ),
        (
            Some(token.as_str()),
            Some(csrf.as_str()),
            Some("https://attacker.example"),
            StatusCode::FORBIDDEN,
        ),
    ] {
        assert_eq!(
            call(&app, "PUT", &path, cookie, csrf, origin, &valid)
                .await?
                .status(),
            status
        );
    }
    for body in [
        "[]".to_owned(),
        "null".to_owned(),
        json!({"objectId":id,"payload":"Zg","retentionMs":1}).to_string(),
        r#"{"payload":"Zg","retentionMs":1,"retentionMs":2}"#.to_owned(),
        r#"{"payload":"Zg","payload":"Zw","retentionMs":1}"#.to_owned(),
        json!({"payload":"Zg","retentionMs":0}).to_string(),
        json!({"payload":"Zg","retentionMs":86400001}).to_string(),
        json!({"payload":"Zg","retentionMs":1.5}).to_string(),
        json!({"payload":"Zg","retentionMs":true}).to_string(),
        json!({"payload":"Zg=","retentionMs":1}).to_string(),
        json!({"payload":"Zh","retentionMs":1}).to_string(),
        json!({"payload":"","retentionMs":1}).to_string(),
        json!({"payload":URL_SAFE_NO_PAD.encode(vec![0;MAX_OBJECT_BYTES+1]),"retentionMs":1})
            .to_string(),
    ] {
        assert_eq!(
            call(
                &app,
                "PUT",
                &path,
                Some(&token),
                Some(&csrf),
                Some(ORIGIN),
                &body
            )
            .await?
            .status(),
            StatusCode::BAD_REQUEST
        );
    }
    for bad_path in [
        format!("{path}?accountId=TST-beta"),
        format!("{path}="),
        "/api/storage/objects/short".to_owned(),
    ] {
        assert_eq!(
            call(
                &app,
                "PUT",
                &bad_path,
                Some(&token),
                Some(&csrf),
                Some(ORIGIN),
                &valid
            )
            .await?
            .status(),
            StatusCode::BAD_REQUEST
        );
    }
    let full =
        json!({"payload":URL_SAFE_NO_PAD.encode(vec![9;MAX_OBJECT_BYTES]),"retentionMs":60000})
            .to_string();
    assert_eq!(
        call(
            &app,
            "PUT",
            &path,
            Some(&token),
            Some(&csrf),
            Some(ORIGIN),
            &full
        )
        .await?
        .status(),
        StatusCode::SERVICE_UNAVAILABLE
    );
    assert_eq!(
        call(
            &app,
            "DELETE",
            &path,
            Some(&token),
            Some(&csrf),
            Some(ORIGIN),
            &full
        )
        .await?
        .status(),
        StatusCode::PAYLOAD_TOO_LARGE
    );
    assert_eq!(
        call(
            &app,
            "PUT",
            &path,
            Some(&token),
            Some(&csrf),
            Some(ORIGIN),
            &" ".repeat(BODY_LIMIT + 1)
        )
        .await?
        .status(),
        StatusCode::PAYLOAD_TOO_LARGE
    );
    Ok(())
}

#[tokio::test]
async fn checked_delete_requires_one_canonical_digest_and_keeps_small_body_limit() -> TestResult {
    let state = crate::tests::test_state()?;
    let token = crate::random_token();
    let csrf = crate::random_token();
    let digest = crate::random_token();
    let path = format!("/api/storage/objects/{}", crate::random_token());
    let valid = json!({"sha256":digest}).to_string();
    assert_eq!(
        call(
            &router(state.clone()),
            "DELETE",
            &path,
            Some(&token),
            Some(&csrf),
            Some(ORIGIN),
            &valid
        )
        .await?
        .status(),
        StatusCode::NOT_FOUND
    );
    let app = crate::router_with_routes(state, routes());
    for (cookie, csrf, origin, status) in [
        (
            None,
            Some(csrf.as_str()),
            Some(ORIGIN),
            StatusCode::UNAUTHORIZED,
        ),
        (
            Some(token.as_str()),
            None,
            Some(ORIGIN),
            StatusCode::FORBIDDEN,
        ),
        (
            Some(token.as_str()),
            Some(csrf.as_str()),
            None,
            StatusCode::FORBIDDEN,
        ),
        (
            Some(token.as_str()),
            Some(csrf.as_str()),
            Some("https://attacker.example"),
            StatusCode::FORBIDDEN,
        ),
    ] {
        assert_eq!(
            call(&app, "DELETE", &path, cookie, csrf, origin, &valid)
                .await?
                .status(),
            status
        );
    }
    for body in [
        "[]".to_owned(),
        "null".to_owned(),
        json!({"sha256":null}).to_string(),
        json!({"sha256":true}).to_string(),
        json!({"sha256":[]}).to_string(),
        json!({"sha256":{}}).to_string(),
        json!({"sha256":""}).to_string(),
        json!({"sha256":"short"}).to_string(),
        json!({"sha256":format!("{digest}=")}).to_string(),
        json!({"sha256":"A".repeat(42)+"B"}).to_string(),
        json!({"sha256":digest,"accountId":"TST-beta"}).to_string(),
        format!(r#"{{"sha256":"{digest}","sha256":"{digest}"}}"#),
    ] {
        assert_eq!(
            call(
                &app,
                "DELETE",
                &path,
                Some(&token),
                Some(&csrf),
                Some(ORIGIN),
                &body
            )
            .await?
            .status(),
            StatusCode::BAD_REQUEST
        );
    }
    for body in [&valid, "{}"] {
        assert_eq!(
            call(
                &app,
                "DELETE",
                &path,
                Some(&token),
                Some(&csrf),
                Some(ORIGIN),
                body
            )
            .await?
            .status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
    }
    assert_eq!(
        call(
            &app,
            "DELETE",
            &format!("{path}?accountId=TST-beta"),
            Some(&token),
            Some(&csrf),
            Some(ORIGIN),
            &valid
        )
        .await?
        .status(),
        StatusCode::BAD_REQUEST
    );
    assert_eq!(
        call(
            &app,
            "DELETE",
            &path,
            Some(&token),
            Some(&csrf),
            Some(ORIGIN),
            &" ".repeat(257)
        )
        .await?
        .status(),
        StatusCode::PAYLOAD_TOO_LARGE
    );
    Ok(())
}

#[tokio::test]
#[ignore = "requires owned disposable synthetic PostgreSQL"]
async fn postgres_cmv_http_contract() -> TestResult {
    let db = Arc::new(PgStore::connect_local(&std::env::var("RIO_PG_TEST_URL")?).await?);
    let mut state = crate::tests::test_state()?;
    state.db = Some(db.clone());
    let app = router_with_cmv_storage(state).await?;
    let (alpha, csrf_a) = seed(&db, "TST-alpha").await?;
    let (beta, csrf_b) = seed(&db, "TST-beta").await?;
    let id = crate::random_token();
    let path = format!("/api/storage/objects/{id}");
    let payload = vec![0x8f; MAX_OBJECT_BYTES];
    let body = put_body(&id, &payload, 60_000);
    for csrf in [&csrf_a, "wrong"] {
        assert_eq!(
            call(
                &app,
                "POST",
                "/api/storage/objects",
                Some(&beta),
                Some(csrf),
                Some(ORIGIN),
                &body
            )
            .await?
            .status(),
            StatusCode::FORBIDDEN
        );
    }
    let created = document(
        call(
            &app,
            "POST",
            "/api/storage/objects",
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &body,
        )
        .await?,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(created["object"]["bytes"], MAX_OBJECT_BYTES);
    let retry_body =
        json!({"payload":URL_SAFE_NO_PAD.encode(&payload),"retentionMs":60000}).to_string();
    let confirmed = document(
        call(
            &app,
            "PUT",
            &path,
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &retry_body,
        )
        .await?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(
        confirmed, created,
        "identical retry acknowledges the original bytes without changing the envelope"
    );
    for body in [
        json!({"payload":"Zg","retentionMs":60000}).to_string(),
        json!({"payload":URL_SAFE_NO_PAD.encode(&payload),"retentionMs":60001}).to_string(),
    ] {
        assert_eq!(
            call(
                &app,
                "PUT",
                &path,
                Some(&beta),
                Some(&csrf_b),
                Some(ORIGIN),
                &body
            )
            .await?
            .status(),
            StatusCode::CONFLICT
        );
    }
    assert_eq!(
        call(
            &app,
            "PUT",
            &path,
            Some(&beta),
            Some(&csrf_a),
            Some(ORIGIN),
            &retry_body
        )
        .await?
        .status(),
        StatusCode::FORBIDDEN
    );
    let new_path = format!("/api/storage/objects/{}", crate::random_token());
    let delete_body = json!({"sha256":created["object"]["sha256"]}).to_string();
    document(
        call(
            &app,
            "PUT",
            &new_path,
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &retry_body,
        )
        .await?,
        StatusCode::CREATED,
    )
    .await?;
    assert_eq!(
        call(
            &app,
            "DELETE",
            &new_path,
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &json!({"sha256":URL_SAFE_NO_PAD.encode([0;32])}).to_string()
        )
        .await?
        .status(),
        StatusCode::CONFLICT
    );
    let deleted = document(
        call(
            &app,
            "DELETE",
            &new_path,
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &delete_body,
        )
        .await?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(deleted["object"]["state"], "DELETED");
    assert_eq!(deleted["object"]["sha256"], created["object"]["sha256"]);
    assert_eq!(deleted["object"]["liveBytes"], 0);
    assert_eq!(deleted["object"]["payloadVerified"], false);
    assert!(deleted["object"]["endedAt"].is_i64());
    let repeated = document(
        call(
            &app,
            "DELETE",
            &new_path,
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &delete_body,
        )
        .await?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(deleted, repeated);
    assert_eq!(
        call(
            &app,
            "DELETE",
            &new_path,
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            "{}"
        )
        .await?
        .status(),
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        call(
            &app,
            "DELETE",
            &new_path,
            Some(&alpha),
            Some(&csrf_a),
            Some(ORIGIN),
            &delete_body
        )
        .await?
        .status(),
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        call(
            &app,
            "DELETE",
            &new_path,
            Some(&beta),
            Some(&csrf_a),
            Some(ORIGIN),
            &delete_body
        )
        .await?
        .status(),
        StatusCode::FORBIDDEN
    );
    let own = inventory(&app, &beta).await?;
    let item = own["objects"]
        .as_array()
        .ok_or("catalog missing")?
        .iter()
        .find(|o| o["objectId"] == id)
        .ok_or("object missing")?;
    assert_eq!(item["state"], "LIVE");
    assert_eq!(item["payloadVerified"], true);
    assert!(
        inventory(&app, &alpha).await?["objects"]
            .as_array()
            .ok_or("catalog missing")?
            .iter()
            .all(|o| o["objectId"] != id)
    );
    let read = document(
        call(&app, "GET", &path, Some(&beta), None, None, "").await?,
        StatusCode::OK,
    )
    .await?;
    assert_eq!(read["object"]["payload"], URL_SAFE_NO_PAD.encode(&payload));
    assert_eq!(
        read["object"]["sha256"],
        URL_SAFE_NO_PAD.encode(Sha256::digest(&payload))
    );
    assert_eq!(
        call(&app, "GET", &path, Some(&alpha), None, None, "")
            .await?
            .status(),
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        call(
            &app,
            "DELETE",
            &path,
            Some(&alpha),
            Some(&csrf_a),
            Some(ORIGIN),
            "{}"
        )
        .await?
        .status(),
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/storage/objects",
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &body
        )
        .await?
        .status(),
        StatusCode::CONFLICT
    );
    let used = document(
        call(
            &app,
            "GET",
            "/api/storage/usage",
            Some(&beta),
            None,
            None,
            "",
        )
        .await?,
        StatusCode::OK,
    )
    .await?;
    assert!(
        used["usage"]["liveBytes"]
            .as_u64()
            .is_some_and(|v| v >= MAX_OBJECT_BYTES as u64)
    );
    assert_eq!(used["limits"]["lifetimeObjects"], MAX_ACCOUNT_OBJECTS);
    // Drive the byte quota through HTTP without depending on other fixture object counts.
    let mut allocated = vec![id.clone()];
    loop {
        let next = crate::random_token();
        let response = call(
            &app,
            "POST",
            "/api/storage/objects",
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &put_body(&next, &payload, 60_000),
        )
        .await?;
        if response.status() == StatusCode::TOO_MANY_REQUESTS {
            break;
        }
        assert_eq!(response.status(), StatusCode::CREATED);
        allocated.push(next);
        assert!(
            allocated.len() <= 4,
            "quota cannot be bypassed through HTTP"
        );
    }
    for object in allocated {
        document(
            call(
                &app,
                "DELETE",
                &format!("/api/storage/objects/{object}"),
                Some(&beta),
                Some(&csrf_b),
                Some(ORIGIN),
                "{}",
            )
            .await?,
            StatusCode::OK,
        )
        .await?;
    }
    assert_eq!(
        call(&app, "GET", &path, Some(&beta), None, None, "")
            .await?
            .status(),
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/storage/objects",
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &body
        )
        .await?
        .status(),
        StatusCode::CONFLICT
    );
    let expires = crate::random_token();
    assert_eq!(
        call(
            &app,
            "PUT",
            &path,
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &retry_body
        )
        .await?
        .status(),
        StatusCode::CONFLICT
    );
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/storage/objects",
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &put_body(&expires, b"expires", 1)
        )
        .await?
        .status(),
        StatusCode::CREATED
    );
    tokio::time::sleep(std::time::Duration::from_millis(5)).await;
    assert_eq!(
        call(
            &app,
            "GET",
            &format!("/api/storage/objects/{expires}"),
            Some(&beta),
            None,
            None,
            ""
        )
        .await?
        .status(),
        StatusCode::FORBIDDEN
    );
    db.logout_all(hash(&beta), &csrf_b).await?;
    assert_eq!(
        call(
            &app,
            "DELETE",
            &new_path,
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &delete_body
        )
        .await?
        .status(),
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        call(
            &app,
            "PUT",
            &path,
            Some(&beta),
            Some(&csrf_b),
            Some(ORIGIN),
            &retry_body
        )
        .await?
        .status(),
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        call(
            &app,
            "GET",
            "/api/storage/objects",
            Some(&beta),
            None,
            None,
            ""
        )
        .await?
        .status(),
        StatusCode::UNAUTHORIZED
    );
    let catalog = inventory(&app, &alpha).await?;
    assert!(
        catalog["objects"]
            .as_array()
            .ok_or("catalog missing")?
            .iter()
            .all(|o| o["objectId"] != id)
    );
    assert_eq!(
        call(
            &app,
            "GET",
            "/api/storage/usage",
            Some(&beta),
            None,
            None,
            ""
        )
        .await?
        .status(),
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        call(
            &app,
            "GET",
            "/api/storage/usage",
            Some(&alpha),
            None,
            None,
            ""
        )
        .await?
        .status(),
        StatusCode::OK
    );
    db.recover_after_restore().await?;
    assert_eq!(
        call(
            &app,
            "GET",
            "/api/storage/usage",
            Some(&alpha),
            None,
            None,
            ""
        )
        .await?
        .status(),
        StatusCode::UNAUTHORIZED
    );
    Ok(())
}
