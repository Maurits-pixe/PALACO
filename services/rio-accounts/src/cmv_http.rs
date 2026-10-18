//! Explicitly enabled, same-origin HTTP boundary for synthetic opaque objects.
use crate::{
    ApiError, AppState, SESSION_COOKIE, cookie, hash, mutation_headers,
    storage::{
        Key,
        cmv::{MAX_ACCOUNT_BYTES, MAX_ACCOUNT_OBJECTS, MAX_OBJECT_BYTES, MAX_RETENTION_MS},
    },
    storage_error,
};
use axum::{
    Json, Router,
    body::Bytes,
    extract::{DefaultBodyLimit, Path, State},
    http::{HeaderMap, StatusCode},
    routing::get,
};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use serde::Deserialize;
use serde::de::DeserializeOwned;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

const BODY_LIMIT: usize = 24_000;

#[derive(Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct Put {
    object_id: String,
    payload: String,
    retention_ms: i64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Empty {}

fn json_object<T: DeserializeOwned>(body: &[u8]) -> Result<T, ApiError> {
    if body.iter().find(|byte| !byte.is_ascii_whitespace()) != Some(&b'{') {
        return Err(ApiError(StatusCode::BAD_REQUEST));
    }
    serde_json::from_slice(body).map_err(|_| ApiError(StatusCode::BAD_REQUEST))
}

fn decode(value: &str, maximum: usize) -> Result<Vec<u8>, ApiError> {
    if value.len() > maximum.div_ceil(3) * 4 {
        return Err(ApiError(StatusCode::BAD_REQUEST));
    }
    let bytes = URL_SAFE_NO_PAD
        .decode(value)
        .map_err(|_| ApiError(StatusCode::BAD_REQUEST))?;
    if bytes.len() > maximum || URL_SAFE_NO_PAD.encode(&bytes) != value {
        return Err(ApiError(StatusCode::BAD_REQUEST));
    }
    Ok(bytes)
}

fn object_key(value: &str) -> Result<Key, ApiError> {
    decode(value, 32)?
        .try_into()
        .map_err(|_| ApiError(StatusCode::BAD_REQUEST))
}

fn token(headers: &HeaderMap) -> Result<Key, ApiError> {
    Ok(hash(
        &cookie(headers, SESSION_COOKIE)?.ok_or(ApiError(StatusCode::UNAUTHORIZED))?,
    ))
}

fn envelope() -> Value {
    json!({"schema":"RIO_CMV_SYNTHETIC_OBJECT_V1", "mode":"SYNTHETIC_ONLY",
        "account1":"HOLD","accountActive":false,"canOpenContact":false,"operativeAuthority":"NONE"})
}

pub(crate) fn routes() -> Router<AppState> {
    Router::new()
        .route("/api/storage/usage", get(usage))
        .route(
            "/api/storage/objects",
            get(catalog)
                .post(put)
                .layer(DefaultBodyLimit::max(BODY_LIMIT)),
        )
        .route("/api/storage/objects/{object_id}", get(read).delete(delete))
}

async fn catalog(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let token = token(&headers)?;
    let db = state
        .db
        .as_ref()
        .ok_or(ApiError(StatusCode::SERVICE_UNAVAILABLE))?;
    let catalog = db.cmv_catalog(token).await.map_err(storage_error)?;
    let mut response = envelope();
    response["schema"] = json!("RIO_CMV_SYNTHETIC_CATALOG_V1");
    response["observedAt"] = json!(catalog.observed_ms);
    response["objects"]=json!(catalog.objects.iter().map(|object|json!({
        "objectId":URL_SAFE_NO_PAD.encode(object.object_id),"sha256":URL_SAFE_NO_PAD.encode(object.digest),
        "liveBytes":object.live_bytes,"state":object.state,"createdAt":object.created_ms,
        "expiresAt":object.expires_ms,"endedAt":object.ended_ms,"payloadVerified":object.state=="LIVE",
    })).collect::<Vec<_>>());
    response["usage"] = json!({"liveBytes":catalog.usage.live_bytes,"retainedObjects":catalog.usage.retained_objects});
    Ok(Json(response))
}

async fn put(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<(StatusCode, Json<Value>), ApiError> {
    let csrf = mutation_headers(&headers, &state.endpoints)?;
    let token = token(&headers)?;
    if body.len() > BODY_LIMIT {
        return Err(ApiError(StatusCode::PAYLOAD_TOO_LARGE));
    }
    let request: Put = json_object(&body)?;
    let id = object_key(&request.object_id)?;
    let payload = decode(&request.payload, MAX_OBJECT_BYTES)?;
    if payload.is_empty() || !(1..=MAX_RETENTION_MS).contains(&request.retention_ms) {
        return Err(ApiError(StatusCode::BAD_REQUEST));
    }
    let db = state
        .db
        .as_ref()
        .ok_or(ApiError(StatusCode::SERVICE_UNAVAILABLE))?;
    let digest = db
        .put_cmv_object(token, csrf, id, &payload, request.retention_ms)
        .await
        .map_err(storage_error)?;
    let mut response = envelope();
    response["object"] = json!({"objectId":request.object_id,"sha256":URL_SAFE_NO_PAD.encode(digest),"bytes":payload.len()});
    Ok((StatusCode::CREATED, Json(response)))
}

async fn read(
    State(state): State<AppState>,
    Path(id): Path<String>,
    headers: HeaderMap,
) -> Result<Json<Value>, ApiError> {
    let token = token(&headers)?;
    let key = object_key(&id)?;
    let db = state
        .db
        .as_ref()
        .ok_or(ApiError(StatusCode::SERVICE_UNAVAILABLE))?;
    let payload = db
        .read_cmv_object(token, key)
        .await
        .map_err(storage_error)?;
    let mut response = envelope();
    response["object"] = json!({"objectId":id,"payload":URL_SAFE_NO_PAD.encode(&payload),
        "sha256":URL_SAFE_NO_PAD.encode(Sha256::digest(&payload)),"bytes":payload.len()});
    Ok(Json(response))
}

async fn delete(
    State(state): State<AppState>,
    Path(id): Path<String>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<Value>, ApiError> {
    let csrf = mutation_headers(&headers, &state.endpoints)?;
    let token = token(&headers)?;
    let key = object_key(&id)?;
    let _: Empty = json_object(&body)?;
    let db = state
        .db
        .as_ref()
        .ok_or(ApiError(StatusCode::SERVICE_UNAVAILABLE))?;
    db.delete_cmv_object(token, csrf, key)
        .await
        .map_err(storage_error)?;
    let mut response = envelope();
    response["object"] = json!({"objectId":id,"state":"DELETED"});
    Ok(Json(response))
}

async fn usage(State(state): State<AppState>, headers: HeaderMap) -> Result<Json<Value>, ApiError> {
    let token = token(&headers)?;
    let db = state
        .db
        .as_ref()
        .ok_or(ApiError(StatusCode::SERVICE_UNAVAILABLE))?;
    let used = db.cmv_usage(token).await.map_err(storage_error)?;
    let mut response = envelope();
    response["usage"] =
        json!({"liveBytes":used.live_bytes,"retainedObjects":used.retained_objects});
    response["limits"] = json!({"objectBytes":MAX_OBJECT_BYTES,"liveBytes":MAX_ACCOUNT_BYTES,
        "lifetimeObjects":MAX_ACCOUNT_OBJECTS,"retentionMs":MAX_RETENTION_MS});
    Ok(Json(response))
}

#[cfg(test)]
#[path = "cmv_http_tests.rs"]
mod tests;
