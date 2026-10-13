//! T04 HTTP boundary for a tenant-owned synthetic consent receipt.
//! This test scope never activates an account, contact route, identity or provider operation.
use axum::{
    Json,
    body::Bytes,
    extract::State,
    http::{HeaderMap, StatusCode},
};
use serde::Deserialize;
use serde_json::{Value, json};

use crate::{
    ApiError, AppState, SESSION_COOKIE, cookie, hash, mutation_headers,
    storage::{CONSENT_SCOPE, ConsentRecord},
    storage_error,
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Choice {
    scope: String,
    granted: bool,
    revision: i64,
}

fn response(receipt: ConsentRecord) -> Json<Value> {
    Json(json!({
        "receipt": {
            "scope": receipt.scope,
            "granted": receipt.granted,
            "revision": receipt.revision,
            "expiresAt": receipt.expires_ms,
        },
        "mode": "SYNTHETIC_ONLY",
        "account1": "HOLD",
        "accountActive": false,
        "canOpenContact": false,
        "operativeAuthority": "NONE",
    }))
}

/// Read only the receipt belonging to the caller's current opaque session.
pub(crate) async fn read(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let token = cookie(&headers, SESSION_COOKIE)?.ok_or(ApiError(StatusCode::UNAUTHORIZED))?;
    let db = state
        .db
        .as_ref()
        .ok_or(ApiError(StatusCode::SERVICE_UNAVAILABLE))?;
    let receipt = db.read_consent(hash(&token)).await.map_err(storage_error)?;
    Ok(response(receipt))
}

/// Commit an explicit, revision-bound choice for the sole synthetic scope.
pub(crate) async fn write(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<Value>, ApiError> {
    let csrf = mutation_headers(&headers)?;
    if body.len() > 256 {
        return Err(ApiError(StatusCode::PAYLOAD_TOO_LARGE));
    }
    let choice: Choice =
        serde_json::from_slice(&body).map_err(|_| ApiError(StatusCode::BAD_REQUEST))?;
    if choice.revision < 0 {
        return Err(ApiError(StatusCode::BAD_REQUEST));
    }
    if choice.scope != CONSENT_SCOPE {
        return Err(ApiError(StatusCode::FORBIDDEN));
    }
    let token = cookie(&headers, SESSION_COOKIE)?.ok_or(ApiError(StatusCode::UNAUTHORIZED))?;
    let db = state
        .db
        .as_ref()
        .ok_or(ApiError(StatusCode::SERVICE_UNAVAILABLE))?;
    let receipt = db
        .set_consent(
            hash(&token),
            csrf,
            &choice.scope,
            choice.granted,
            choice.revision,
        )
        .await
        .map_err(storage_error)?;
    Ok(response(receipt))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::{Key, PgStore, StoreError};
    use crate::{
        AUTH_URL, CALLBACK, CLIENT_ID, GuardedHttp, ISSUER, JWKS_URL, ORIGIN, Store, TOKEN_URL,
    };
    use axum::{
        Router,
        body::{Body, to_bytes},
        http::Request,
        response::Response,
    };
    use openidconnect::{
        AuthUrl, ClientId, ClientSecret, RedirectUrl, TokenUrl,
        core::{CoreClient, CoreProviderMetadata},
    };
    use std::{io, sync::Arc};
    use tokio::sync::{Mutex, Semaphore};
    use tower::ServiceExt;

    type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;

    fn state(
        db: Option<Arc<PgStore>>,
    ) -> Result<AppState, Box<dyn std::error::Error + Send + Sync>> {
        let metadata: CoreProviderMetadata = serde_json::from_value(json!({
            "issuer": ISSUER,
            "authorization_endpoint": AUTH_URL,
            "token_endpoint": TOKEN_URL,
            "jwks_uri": JWKS_URL,
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }))?;
        let client = CoreClient::from_provider_metadata(
            metadata,
            ClientId::new(CLIENT_ID.to_owned()),
            Some(ClientSecret::new("a".repeat(64))),
        )
        .set_auth_uri(AuthUrl::new(AUTH_URL.to_owned())?)
        .set_token_uri(TokenUrl::new(TOKEN_URL.to_owned())?)
        .set_redirect_uri(RedirectUrl::new(CALLBACK.to_owned())?);
        Ok(AppState {
            client,
            http: GuardedHttp(
                reqwest::Client::builder()
                    .no_proxy()
                    .redirect(reqwest::redirect::Policy::none())
                    .build()?,
            ),
            store: Arc::new(Mutex::new(Store::default())),
            db,
            exchanges: Arc::new(Semaphore::new(8)),
        })
    }

    async fn request(
        app: &Router,
        method: &str,
        path: &str,
        token: Option<&str>,
        csrf: Option<&str>,
        origin: Option<&str>,
        body: String,
    ) -> Result<Response, Box<dyn std::error::Error + Send + Sync>> {
        let mut builder = Request::builder()
            .method(method)
            .uri(path)
            .header("host", "localhost:8088")
            .header("content-type", "application/json");
        if let Some(token) = token {
            builder = builder.header("cookie", format!("{SESSION_COOKIE}={token}"));
        }
        if let Some(csrf) = csrf {
            builder = builder.header("x-csrf-token", csrf);
        }
        if let Some(origin) = origin {
            builder = builder.header("origin", origin);
        }
        Ok(app.clone().oneshot(builder.body(Body::from(body))?).await?)
    }

    async fn receipt(
        response: Response,
    ) -> Result<Value, Box<dyn std::error::Error + Send + Sync>> {
        assert_eq!(response.status(), StatusCode::OK);
        assert!(
            response
                .headers()
                .get("cache-control")
                .is_some_and(|value| value == "no-store")
        );
        let bytes = to_bytes(response.into_body(), 4096).await?;
        let body: Value = serde_json::from_slice(&bytes)?;
        assert!(
            body.get("csrfToken").is_none(),
            "consent responses do not echo anti-forgery values"
        );
        assert!(
            body.get("accountId").is_none(),
            "consent reads do not accept or expose an actor selector"
        );
        assert_eq!(body["mode"], "SYNTHETIC_ONLY");
        assert_eq!(body["account1"], "HOLD");
        assert_eq!(body["accountActive"], false);
        assert_eq!(body["canOpenContact"], false);
        assert_eq!(body["operativeAuthority"], "NONE");
        assert_eq!(body["receipt"]["scope"], CONSENT_SCOPE);
        Ok(body["receipt"].clone())
    }

    fn choice(granted: bool, revision: i64) -> String {
        json!({"scope": CONSENT_SCOPE, "granted": granted, "revision": revision}).to_string()
    }

    fn revision(receipt: &Value) -> Result<i64, io::Error> {
        receipt["revision"]
            .as_i64()
            .ok_or_else(|| io::Error::other("receipt revision missing"))
    }

    async fn seed(db: &PgStore, actor: &str) -> Result<(String, String), StoreError> {
        let token = crate::random_token();
        let csrf = crate::random_token();
        let transaction = crate::random_token();
        let state = crate::random_token();
        db.begin_login(hash(&transaction), hash(&state), None)
            .await?;
        let permit = db.consume_login(hash(&transaction), hash(&state)).await?;
        db.replace_session(permit, actor, hash(&token), csrf.clone())
            .await?;
        Ok((token, csrf))
    }

    #[tokio::test]
    async fn consent_http_schema_is_strict_and_memory_never_grants() -> TestResult {
        let token = crate::random_token();
        let csrf = crate::random_token();
        let test_state = state(None)?;
        let now = std::time::Instant::now();
        test_state.store.lock().await.sessions.insert(
            hash(&token),
            crate::Session {
                account_id: "TST-alpha",
                csrf: csrf.clone(),
                created: now,
                touched: now,
            },
        );
        let app = crate::router(test_state);
        assert_eq!(
            request(
                &app,
                "GET",
                "/api/me",
                Some(&token),
                None,
                None,
                String::new()
            )
            .await?
            .status(),
            StatusCode::OK,
        );
        assert_eq!(
            request(&app, "GET", "/api/consent", None, None, None, String::new())
                .await?
                .status(),
            StatusCode::UNAUTHORIZED,
        );
        assert_eq!(
            request(
                &app,
                "GET",
                "/api/consent",
                Some(&token),
                None,
                None,
                String::new()
            )
            .await?
            .status(),
            StatusCode::SERVICE_UNAVAILABLE,
        );
        assert_eq!(
            request(
                &app,
                "POST",
                "/api/consent",
                Some(&token),
                Some(&csrf),
                Some(ORIGIN),
                choice(false, 0)
            )
            .await?
            .status(),
            StatusCode::SERVICE_UNAVAILABLE,
        );
        assert_eq!(
            request(
                &app,
                "POST",
                "/api/consent",
                Some(&token),
                Some(&csrf),
                Some("https://attacker.example"),
                choice(true, 0)
            )
            .await?
            .status(),
            StatusCode::FORBIDDEN,
        );
        for body in [
            json!({"scope":CONSENT_SCOPE,"granted":"true","revision":0}).to_string(),
            json!({"scope":CONSENT_SCOPE,"granted":true,"revision":0,"accountId":"TST-beta"})
                .to_string(),
            json!({"scope":CONSENT_SCOPE,"granted":true}).to_string(),
            json!({"scope":CONSENT_SCOPE,"granted":true,"revision":-1}).to_string(),
            format!(r#"{{"scope":"{CONSENT_SCOPE}","granted":true,"revision":0,"revision":1}}"#),
        ] {
            assert_eq!(
                request(
                    &app,
                    "POST",
                    "/api/consent",
                    Some(&token),
                    Some(&csrf),
                    Some(ORIGIN),
                    body
                )
                .await?
                .status(),
                StatusCode::BAD_REQUEST,
            );
        }
        assert_eq!(
            request(
                &app,
                "POST",
                "/api/consent",
                Some(&token),
                Some(&csrf),
                Some(ORIGIN),
                json!({"scope":"CONTACT_OR_IDENTITY","granted":true,"revision":0}).to_string()
            )
            .await?
            .status(),
            StatusCode::FORBIDDEN,
        );
        assert_eq!(
            request(
                &app,
                "GET",
                "/api/consent?actor=TST-beta",
                Some(&token),
                None,
                None,
                String::new()
            )
            .await?
            .status(),
            StatusCode::BAD_REQUEST,
        );
        assert_eq!(
            request(
                &app,
                "POST",
                "/api/consent",
                Some(&token),
                Some(&csrf),
                Some(ORIGIN),
                " ".repeat(257)
            )
            .await?
            .status(),
            StatusCode::PAYLOAD_TOO_LARGE,
        );
        Ok(())
    }

    /// Real HTTP router and PostgreSQL proof, selected explicitly by the isolated fixture.
    #[tokio::test]
    #[ignore = "requires isolated synthetic PostgreSQL; never a production database"]
    async fn postgres_consent_http_contract() -> TestResult {
        eprintln!("CASE T04_SETUP");
        let url = std::env::var("RIO_PG_TEST_URL").map_err(|_| StoreError::Invalid)?;
        let db = Arc::new(PgStore::connect_local(&url).await?);
        db.recover_after_restore().await?;
        let app = crate::router(state(Some(db.clone()))?);
        let (alpha, alpha_csrf) = seed(&db, "TST-alpha").await?;
        let (peer, peer_csrf) = seed(&db, "TST-alpha").await?;
        let (beta, beta_csrf) = seed(&db, "TST-beta").await?;

        eprintln!("CASE T04_OWN_RECEIPT");
        let initial = receipt(
            request(
                &app,
                "GET",
                "/api/consent",
                Some(&alpha),
                None,
                None,
                String::new(),
            )
            .await?,
        )
        .await?;
        assert_eq!(initial["granted"], false);
        assert_eq!(initial["expiresAt"], Value::Null);
        assert_eq!(
            request(
                &app,
                "GET",
                "/api/consent",
                Some(&crate::random_token()),
                None,
                None,
                String::new()
            )
            .await?
            .status(),
            StatusCode::UNAUTHORIZED,
        );

        eprintln!("CASE T04_CSRF");
        for wrong_csrf in [&beta_csrf, &peer_csrf] {
            assert_eq!(
                request(
                    &app,
                    "POST",
                    "/api/consent",
                    Some(&alpha),
                    Some(wrong_csrf),
                    Some(ORIGIN),
                    choice(true, revision(&initial)?)
                )
                .await?
                .status(),
                StatusCode::FORBIDDEN,
            );
        }
        let unchanged = receipt(
            request(
                &app,
                "GET",
                "/api/consent",
                Some(&alpha),
                None,
                None,
                String::new(),
            )
            .await?,
        )
        .await?;
        assert_eq!(revision(&unchanged)?, revision(&initial)?);
        assert_eq!(unchanged["granted"], false);
        let accepted = receipt(
            request(
                &app,
                "POST",
                "/api/consent",
                Some(&alpha),
                Some(&alpha_csrf),
                Some(ORIGIN),
                choice(true, revision(&initial)?),
            )
            .await?,
        )
        .await?;
        assert_eq!(accepted["granted"], true);
        assert!(accepted["expiresAt"].as_i64().is_some());
        let peer_receipt = receipt(
            request(
                &app,
                "GET",
                "/api/consent",
                Some(&peer),
                None,
                None,
                String::new(),
            )
            .await?,
        )
        .await?;
        assert_eq!(peer_receipt["granted"], true);
        let beta_initial = receipt(
            request(
                &app,
                "GET",
                "/api/consent",
                Some(&beta),
                None,
                None,
                String::new(),
            )
            .await?,
        )
        .await?;
        assert_eq!(beta_initial["granted"], false);

        eprintln!("CASE T04_CAS");
        let current_revision = revision(&accepted)?;
        let (first, second) = tokio::join!(
            request(
                &app,
                "POST",
                "/api/consent",
                Some(&alpha),
                Some(&alpha_csrf),
                Some(ORIGIN),
                choice(false, current_revision)
            ),
            request(
                &app,
                "POST",
                "/api/consent",
                Some(&alpha),
                Some(&alpha_csrf),
                Some(ORIGIN),
                choice(true, current_revision)
            ),
        );
        let first = first?.status();
        let second = second?.status();
        assert!(
            (first == StatusCode::OK && second == StatusCode::CONFLICT)
                || (first == StatusCode::CONFLICT && second == StatusCode::OK),
            "exactly one revision-bound choice commits",
        );
        let fresh = receipt(
            request(
                &app,
                "GET",
                "/api/consent",
                Some(&alpha),
                None,
                None,
                String::new(),
            )
            .await?,
        )
        .await?;
        assert_eq!(revision(&fresh)?, current_revision + 1);
        let closed = receipt(
            request(
                &app,
                "POST",
                "/api/consent",
                Some(&alpha),
                Some(&alpha_csrf),
                Some(ORIGIN),
                choice(false, revision(&fresh)?),
            )
            .await?,
        )
        .await?;
        assert_eq!(closed["granted"], false);
        let beta_after = receipt(
            request(
                &app,
                "GET",
                "/api/consent",
                Some(&beta),
                None,
                None,
                String::new(),
            )
            .await?,
        )
        .await?;
        assert_eq!(revision(&beta_after)?, revision(&beta_initial)?);
        assert_eq!(beta_after["granted"], false);

        eprintln!("CASE T04_REVOKE");
        assert_eq!(
            request(
                &app,
                "POST",
                "/auth/logout-all",
                Some(&alpha),
                Some(&alpha_csrf),
                Some(ORIGIN),
                "{}".to_owned()
            )
            .await?
            .status(),
            StatusCode::OK,
        );
        for revoked in [&alpha, &peer] {
            assert_eq!(
                request(
                    &app,
                    "GET",
                    "/api/consent",
                    Some(revoked),
                    None,
                    None,
                    String::new()
                )
                .await?
                .status(),
                StatusCode::UNAUTHORIZED,
            );
        }
        let (fresh_alpha, fresh_csrf) = seed(&db, "TST-alpha").await?;
        let after_revoke = receipt(
            request(
                &app,
                "GET",
                "/api/consent",
                Some(&fresh_alpha),
                None,
                None,
                String::new(),
            )
            .await?,
        )
        .await?;
        assert_eq!(after_revoke["granted"], false);
        assert_eq!(
            request(
                &app,
                "POST",
                "/api/consent",
                Some(&fresh_alpha),
                Some(&fresh_csrf),
                Some(ORIGIN),
                choice(true, revision(&accepted)?)
            )
            .await?
            .status(),
            StatusCode::CONFLICT,
        );

        eprintln!("CASE T04_EXPIRY");
        let (expired, expired_csrf) = seed(&db, "TST-alpha").await?;
        let mut config: tokio_postgres::Config = url.parse().map_err(|_| StoreError::Invalid)?;
        config.connect_timeout(std::time::Duration::from_secs(8));
        let (raw, connection) = config
            .connect(tokio_postgres::NoTls)
            .await
            .map_err(StoreError::from)?;
        let task = tokio::spawn(async move {
            let _ = connection.await;
        });
        let expired_hash: Key = hash(&expired);
        raw.execute(
            "UPDATE rio_synthetic.sessions SET created_ms=created_ms-31000,touched_ms=touched_ms-31000,\
             idle_expires_ms=idle_expires_ms-31000,absolute_expires_ms=absolute_expires_ms-31000 WHERE token_hash=$1",
            &[&expired_hash.to_vec()]).await.map_err(StoreError::from)?;
        assert_eq!(
            request(
                &app,
                "GET",
                "/api/consent",
                Some(&expired),
                None,
                None,
                String::new()
            )
            .await?
            .status(),
            StatusCode::UNAUTHORIZED,
        );
        assert_eq!(
            request(
                &app,
                "POST",
                "/api/consent",
                Some(&expired),
                Some(&expired_csrf),
                Some(ORIGIN),
                choice(true, revision(&after_revoke)?)
            )
            .await?
            .status(),
            StatusCode::UNAUTHORIZED,
        );

        eprintln!("CASE T04_UNAVAILABLE");
        raw.execute(
            "UPDATE rio_synthetic.store_guard SET last_ms=floor(extract(epoch FROM clock_timestamp())*1000)::bigint+5000 WHERE id=1",
            &[]).await.map_err(StoreError::from)?;
        assert_eq!(
            request(
                &app,
                "GET",
                "/api/consent",
                Some(&beta),
                None,
                None,
                String::new()
            )
            .await?
            .status(),
            StatusCode::SERVICE_UNAVAILABLE,
        );
        assert_eq!(
            request(
                &app,
                "POST",
                "/api/consent",
                Some(&beta),
                Some(&beta_csrf),
                Some(ORIGIN),
                choice(true, revision(&beta_initial)?)
            )
            .await?
            .status(),
            StatusCode::SERVICE_UNAVAILABLE,
        );
        raw.execute(
            "UPDATE rio_synthetic.store_guard SET last_ms=floor(extract(epoch FROM clock_timestamp())*1000)::bigint WHERE id=1",
            &[]).await.map_err(StoreError::from)?;
        assert_eq!(
            request(
                &app,
                "GET",
                "/api/consent",
                Some(&beta),
                None,
                None,
                String::new()
            )
            .await?
            .status(),
            StatusCode::SERVICE_UNAVAILABLE,
        );
        eprintln!("CASE T04_RECOVERY");
        let recovered = Arc::new(PgStore::connect_local(&url).await?);
        let restarted = crate::router(state(Some(recovered.clone()))?);
        let preserved = receipt(
            request(
                &restarted,
                "GET",
                "/api/consent",
                Some(&beta),
                None,
                None,
                String::new(),
            )
            .await?,
        )
        .await?;
        assert_eq!(preserved["granted"], false);
        recovered.recover_after_restore().await?;
        task.abort();
        Ok(())
    }
}
