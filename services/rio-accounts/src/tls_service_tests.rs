//! Actual TLS storage plus in-process HTTP boundary. Seeded sessions are not an OIDC login proof.
use crate::{
    AppState, FLOW_COOKIE, ISSUER, ORIGIN, SESSION_COOKIE, hash, random_token, router,
    storage::{CONSENT_SCOPE, PgStore, StoreError},
    tls_database::SyntheticTlsDbConfig,
};
use axum::{
    Router,
    body::{Body, to_bytes},
    http::{Request, StatusCode, header},
    response::Response,
};
use serde_json::{Value, json};
use std::{
    io,
    net::{IpAddr, Ipv4Addr},
};
use tower::ServiceExt;

type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;

async fn call(
    app: &Router,
    method: &str,
    path: &str,
    cookie: Option<String>,
    csrf: Option<&str>,
    origin: Option<&str>,
    body: String,
) -> Result<Response, Box<dyn std::error::Error + Send + Sync>> {
    let mut request = Request::builder()
        .method(method)
        .uri(path)
        .header("host", "localhost:8088")
        .header("content-type", "application/json");
    if let Some(value) = cookie {
        request = request.header("cookie", value);
    }
    if let Some(value) = csrf {
        request = request.header("x-csrf-token", value);
    }
    if let Some(value) = origin {
        request = request.header("origin", value);
    }
    Ok(app.clone().oneshot(request.body(Body::from(body))?).await?)
}

fn session(token: &str) -> Option<String> {
    Some(format!("{SESSION_COOKIE}={token}"))
}

async fn read_json(response: Response) -> Result<Value, Box<dyn std::error::Error + Send + Sync>> {
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .headers()
            .get("cache-control")
            .and_then(|v| v.to_str().ok()),
        Some("no-store")
    );
    Ok(serde_json::from_slice(
        &to_bytes(response.into_body(), 4096).await?,
    )?)
}

fn closed(value: &Value) {
    assert_eq!(value["mode"], "SYNTHETIC_ONLY");
    assert_eq!(value["account1"], "HOLD");
    assert_eq!(value["accountActive"], false);
    assert_eq!(value["canOpenContact"], false);
    assert_eq!(value["operativeAuthority"], "NONE");
}

async fn receipt(
    app: &Router,
    token: &str,
) -> Result<Value, Box<dyn std::error::Error + Send + Sync>> {
    let body = read_json(
        call(
            app,
            "GET",
            "/api/consent",
            session(token),
            None,
            None,
            String::new(),
        )
        .await?,
    )
    .await?;
    closed(&body);
    assert!(body.get("csrfToken").is_none());
    assert_eq!(body["receipt"]["scope"], CONSENT_SCOPE);
    Ok(body["receipt"].clone())
}

fn choice(granted: bool, revision: &Value) -> String {
    json!({"scope":CONSENT_SCOPE,"granted":granted,"revision":revision}).to_string()
}

async fn seed(db: &PgStore, actor: &str, subject: &str) -> Result<(String, String), StoreError> {
    // Server-only fixture setup, never an external identity verification or browser login.
    let token = random_token();
    let csrf = random_token();
    let transaction = hash(&random_token());
    let state = hash(&random_token());
    db.begin_login(transaction, state, None).await?;
    let permit = db.consume_login(transaction, state).await?;
    db.replace_session_bound(permit, actor, ISSUER, subject, hash(&token), csrf.clone())
        .await?;
    Ok((token, csrf))
}

#[tokio::test]
#[ignore = "requires owned TLS PostgreSQL plus the standard loopback Keycloak discovery fixture"]
async fn postgres_tls_service_contract() -> TestResult {
    let password = std::env::var("RIO_PG_TLS_PASSWORD")?;
    let ca = std::fs::read(std::env::var("RIO_PG_TLS_CA_DER")?)?;
    let other_ca = std::fs::read(std::env::var("RIO_PG_TLS_OTHER_CA_DER")?)?;
    let address = IpAddr::V4(Ipv4Addr::LOCALHOST);
    let config = SyntheticTlsDbConfig::for_test("localhost", address, 8091, &password, &ca)?;
    // Discovery is public; this format-valid fixture secret is never used for token exchange.
    let client_secret = "a".repeat(64);
    for (mode, secret) in [
        ("PRODUCTION", client_secret.as_str()),
        ("SYNTHETIC_ONLY", "PRIVATE_CANARY"),
    ] {
        let error = AppState::discover_tls_synthetic(mode, secret, &config)
            .await
            .err()
            .ok_or_else(|| io::Error::other("invalid service credentials accepted"))?;
        assert_eq!(
            error.to_string(),
            "invalid synthetic development configuration"
        );
    }
    for (hostname, port, trust) in [
        ("localhost", 8091, other_ca.as_slice()),
        ("wrong.example.invalid", 8091, ca.as_slice()),
        ("localhost", 8092, ca.as_slice()),
    ] {
        let invalid = SyntheticTlsDbConfig::for_test(hostname, address, port, &password, trust)?;
        let error = AppState::discover_tls_synthetic("SYNTHETIC_ONLY", &client_secret, &invalid)
            .await
            .err()
            .ok_or_else(|| io::Error::other("unverified TLS service storage accepted"))?;
        assert_eq!(error.to_string(), "synthetic TLS database unavailable");
    }
    eprintln!("CASE T05_TLS_SERVICE_REJECTS_DOWNGRADE");

    let state = AppState::discover_tls_synthetic("SYNTHETIC_ONLY", &client_secret, &config).await?;
    assert_eq!(state.endpoints.origin(), ORIGIN);
    assert_eq!(state.endpoints.issuer(), ISSUER);
    assert_eq!(state.endpoints.client_id(), "rio-bff");
    assert!(state.store.lock().await.sessions.is_empty());
    let db = state
        .db
        .clone()
        .ok_or_else(|| io::Error::other("durable TLS store missing"))?;
    db.health().await?;
    let app = router(state.clone());

    // The real /auth/start writes its one-use login fence via TLS and preserves S256.
    let started = call(&app, "GET", "/auth/start", None, None, None, String::new()).await?;
    assert_eq!(started.status(), StatusCode::SEE_OTHER);
    let location = reqwest::Url::parse(
        started
            .headers()
            .get(header::LOCATION)
            .ok_or_else(|| io::Error::other("login redirect missing"))?
            .to_str()?,
    )?;
    assert_eq!(
        location.origin().ascii_serialization(),
        "http://127.0.0.1:8089"
    );
    let query: std::collections::HashMap<_, _> = location.query_pairs().into_owned().collect();
    assert_eq!(query.get("client_id").map(String::as_str), Some("rio-bff"));
    assert_eq!(
        query.get("redirect_uri").map(String::as_str),
        Some("https://localhost:8088/auth/callback")
    );
    assert_eq!(
        query.get("code_challenge_method").map(String::as_str),
        Some("S256")
    );
    let flow_cookie = started
        .headers()
        .get_all(header::SET_COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok())
        .find(|value| value.starts_with(&format!("{FLOW_COOKIE}=")))
        .and_then(|value| value.split(';').next())
        .ok_or_else(|| io::Error::other("flow cookie missing"))?;
    let transaction = flow_cookie
        .strip_prefix(&format!("{FLOW_COOKIE}="))
        .ok_or_else(|| io::Error::other("flow cookie invalid"))?;
    let input_state = query
        .get("state")
        .ok_or_else(|| io::Error::other("login state missing"))?;
    let callback = format!("/auth/callback?state={input_state}&error=access_denied");
    let rejected = call(
        &app,
        "GET",
        &callback,
        Some(flow_cookie.to_owned()),
        None,
        None,
        String::new(),
    )
    .await?;
    assert_eq!(rejected.status(), StatusCode::BAD_REQUEST);
    assert!(
        db.consume_login(hash(transaction), hash(input_state))
            .await
            .is_err()
    );
    assert!(state.store.lock().await.flows.is_empty());
    assert_eq!(
        call(&app, "GET", "/api/me", None, None, None, String::new())
            .await?
            .status(),
        StatusCode::UNAUTHORIZED
    );
    eprintln!("CASE T05_TLS_SERVICE_LOGIN_FENCE");

    let alpha_subject = "11111111-1111-4111-8111-111111111111";
    let (alpha, alpha_csrf) = seed(&db, "TST-alpha", alpha_subject).await?;
    let (peer, _) = seed(&db, "TST-alpha", alpha_subject).await?;
    let (beta, beta_csrf) = seed(&db, "TST-beta", "22222222-2222-4222-8222-222222222222").await?;
    // The optional HTTP layer keeps the same verified TLS store and bound actors.
    let cmv_app = crate::router_with_cmv_storage(state.clone()).await?;
    let object = random_token();
    let object_path = format!("/api/storage/objects/{object}");
    let body =
        json!({"objectId":object,"payload":"VExTIGZpeHR1cmU","retentionMs":60000}).to_string();
    assert_eq!(
        call(
            &cmv_app,
            "POST",
            "/api/storage/objects",
            session(&beta),
            Some(&beta_csrf),
            Some(ORIGIN),
            body
        )
        .await?
        .status(),
        StatusCode::CREATED
    );
    let stored = read_json(
        call(
            &cmv_app,
            "GET",
            &object_path,
            session(&beta),
            None,
            None,
            String::new(),
        )
        .await?,
    )
    .await?;
    closed(&stored);
    assert_eq!(stored["object"]["payload"], "VExTIGZpeHR1cmU");
    assert_eq!(
        call(
            &cmv_app,
            "GET",
            &object_path,
            session(&alpha),
            None,
            None,
            String::new()
        )
        .await?
        .status(),
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        call(
            &cmv_app,
            "DELETE",
            &object_path,
            session(&beta),
            Some(&beta_csrf),
            Some(ORIGIN),
            "{}".to_owned()
        )
        .await?
        .status(),
        StatusCode::OK
    );
    let account = read_json(
        call(
            &app,
            "GET",
            "/api/me",
            session(&alpha),
            None,
            None,
            String::new(),
        )
        .await?,
    )
    .await?;
    closed(&account);
    assert_eq!(account["accountId"], "TST-alpha");
    assert_eq!(account["csrfToken"], alpha_csrf);
    assert_eq!(
        call(
            &app,
            "GET",
            "/api/me?accountId=TST-beta",
            session(&alpha),
            None,
            None,
            String::new()
        )
        .await?
        .status(),
        StatusCode::BAD_REQUEST
    );
    let before = receipt(&app, &alpha).await?;
    let beta_before = receipt(&app, &beta).await?;
    for (csrf, origin) in [
        (&beta_csrf, ORIGIN),
        (&alpha_csrf, "https://foreign.example.invalid"),
    ] {
        assert_eq!(
            call(
                &app,
                "POST",
                "/api/consent",
                session(&alpha),
                Some(csrf),
                Some(origin),
                choice(true, &before["revision"])
            )
            .await?
            .status(),
            StatusCode::FORBIDDEN
        );
    }
    assert_eq!(receipt(&app, &alpha).await?, before);
    let granted = read_json(
        call(
            &app,
            "POST",
            "/api/consent",
            session(&alpha),
            Some(&alpha_csrf),
            Some(ORIGIN),
            choice(true, &before["revision"]),
        )
        .await?,
    )
    .await?;
    closed(&granted);
    assert_eq!(granted["receipt"]["granted"], true);
    assert_eq!(receipt(&app, &alpha).await?, granted["receipt"]);
    assert_eq!(receipt(&app, &beta).await?, beta_before);
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/consent",
            session(&alpha),
            Some(&alpha_csrf),
            Some(ORIGIN),
            choice(false, &before["revision"])
        )
        .await?
        .status(),
        StatusCode::CONFLICT
    );
    assert_eq!(receipt(&app, &alpha).await?, granted["receipt"]);
    eprintln!("CASE T05_TLS_SERVICE_HTTP_CONSENT");

    assert_eq!(
        call(
            &app,
            "POST",
            "/auth/logout-all",
            session(&alpha),
            Some(&beta_csrf),
            Some(ORIGIN),
            "{}".to_owned()
        )
        .await?
        .status(),
        StatusCode::FORBIDDEN
    );
    let logout = call(
        &app,
        "POST",
        "/auth/logout-all",
        session(&alpha),
        Some(&alpha_csrf),
        Some(ORIGIN),
        "{}".to_owned(),
    )
    .await?;
    assert_eq!(logout.status(), StatusCode::OK);
    assert!(state.store.lock().await.sessions.is_empty());
    drop(app);
    drop(state);
    drop(db);

    // A fresh TLS connection and application state must preserve actor-scoped revocation.
    let restarted =
        AppState::discover_tls_synthetic("SYNTHETIC_ONLY", &client_secret, &config).await?;
    assert!(restarted.db.is_some());
    assert!(restarted.store.lock().await.sessions.is_empty());
    let app = router(restarted);
    for token in [&alpha, &peer] {
        for path in ["/api/me", "/api/consent"] {
            assert_eq!(
                call(&app, "GET", path, session(token), None, None, String::new())
                    .await?
                    .status(),
                StatusCode::UNAUTHORIZED
            );
        }
    }
    let account = read_json(
        call(
            &app,
            "GET",
            "/api/me",
            session(&beta),
            None,
            None,
            String::new(),
        )
        .await?,
    )
    .await?;
    closed(&account);
    assert_eq!(account["accountId"], "TST-beta");
    assert_eq!(account["csrfToken"], beta_csrf);
    assert_eq!(receipt(&app, &beta).await?, beta_before);
    assert_eq!(
        call(
            &app,
            "POST",
            "/auth/logout",
            session(&beta),
            Some(&beta_csrf),
            Some(ORIGIN),
            "{}".to_owned()
        )
        .await?
        .status(),
        StatusCode::OK
    );
    assert_eq!(
        call(
            &app,
            "GET",
            "/api/me",
            session(&beta),
            None,
            None,
            String::new()
        )
        .await?
        .status(),
        StatusCode::UNAUTHORIZED
    );
    eprintln!("CASE T05_TLS_SERVICE_DURABLE_REVOKE");
    Ok(())
}
