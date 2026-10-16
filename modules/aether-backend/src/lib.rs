#![forbid(unsafe_code)]
#![deny(warnings, clippy::unwrap_used, clippy::todo)]

use std::{
    path::Path,
    sync::{Arc, Mutex},
    time::{SystemTime, UNIX_EPOCH},
};

use actix_web::{
    HttpResponse,
    error::InternalError,
    http::StatusCode,
    web::{self, JsonConfig},
};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use ring::{
    aead::{Aad, AES_256_GCM, LessSafeKey, NONCE_LEN, Nonce, UnboundKey},
    rand::{SecureRandom, SystemRandom},
};
use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use uuid::Uuid;
use zeroize::Zeroize;

pub const MAX_PLAINTEXT_BYTES: usize = 64 * 1024;

pub fn decode_master_key(value: &str) -> Result<[u8; 32], &'static str> {
    let mut decoded = STANDARD
        .decode(value)
        .map_err(|_| "AETHER_MASTER_KEY must be valid base64")?;
    if decoded.len() != 32 {
        decoded.zeroize();
        return Err("AETHER_MASTER_KEY must decode to exactly 32 bytes");
    }
    let key = decoded
        .as_slice()
        .try_into()
        .map_err(|_| "AETHER_MASTER_KEY must decode to exactly 32 bytes")?;
    decoded.zeroize();
    Ok(key)
}

pub struct AppState {
    key: Arc<CryptoKey>,
    vault: Vault,
}

impl AppState {
    #[must_use]
    pub fn new(key: [u8; 32], vault: Vault) -> Self {
        Self {
            key: Arc::new(CryptoKey(key)),
            vault,
        }
    }
}

struct CryptoKey([u8; 32]);

impl Drop for CryptoKey {
    fn drop(&mut self) {
        self.0.zeroize();
    }
}

#[derive(Clone)]
pub struct Vault {
    connection: Arc<Mutex<Connection>>,
}

impl Vault {
    pub fn open(path: impl AsRef<Path>) -> rusqlite::Result<Self> {
        let connection = Connection::open(path)?;
        initialize_schema(&connection)?;
        Ok(Self {
            connection: Arc::new(Mutex::new(connection)),
        })
    }

    pub fn in_memory() -> rusqlite::Result<Self> {
        let connection = Connection::open_in_memory()?;
        initialize_schema(&connection)?;
        Ok(Self {
            connection: Arc::new(Mutex::new(connection)),
        })
    }

    fn save(&self, blob: &EncryptedBlob) -> rusqlite::Result<()> {
        let connection = self
            .connection
            .lock()
            .map_err(|_| rusqlite::Error::InvalidQuery)?;
        connection.execute(
            "INSERT INTO secrets (id, ciphertext, nonce, created_at) VALUES (?1, ?2, ?3, ?4)",
            params![blob.id, blob.ciphertext, blob.nonce, blob.created_at],
        )?;
        Ok(())
    }

    fn get(&self, id: &str) -> rusqlite::Result<Option<EncryptedBlob>> {
        let connection = self
            .connection
            .lock()
            .map_err(|_| rusqlite::Error::InvalidQuery)?;
        connection
            .query_row(
                "SELECT id, ciphertext, nonce, created_at FROM secrets WHERE id = ?1",
                [id],
                |row| {
                    Ok(EncryptedBlob {
                        id: row.get(0)?,
                        ciphertext: row.get(1)?,
                        nonce: row.get(2)?,
                        created_at: row.get(3)?,
                    })
                },
            )
            .optional()
    }
}

fn initialize_schema(connection: &Connection) -> rusqlite::Result<()> {
    connection.busy_timeout(std::time::Duration::from_secs(5))?;
    connection.execute_batch(
        "PRAGMA journal_mode = WAL;
         CREATE TABLE IF NOT EXISTS secrets (
             id TEXT PRIMARY KEY NOT NULL,
             ciphertext BLOB NOT NULL,
             nonce BLOB NOT NULL CHECK (length(nonce) = 12),
             created_at INTEGER NOT NULL
         );",
    )
}

pub fn open_vault(path: impl AsRef<Path>) -> rusqlite::Result<Vault> {
    Vault::open(path)
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct EncryptedBlob {
    id: String,
    ciphertext: Vec<u8>,
    nonce: Vec<u8>,
    created_at: i64,
}

#[derive(Deserialize)]
struct EncryptRequest {
    plaintext: String,
}

#[derive(Serialize)]
struct EncryptResponse {
    id: String,
    ciphertext: String,
    nonce: String,
    created_at: i64,
    status: &'static str,
}

#[derive(Serialize)]
struct HealthResponse {
    #[serde(rename = "appId")]
    app_id: &'static str,
    status: &'static str,
    engine: &'static str,
}

#[derive(Serialize)]
struct ApiError {
    error: &'static str,
}

fn json_error(status: StatusCode, error: &'static str) -> HttpResponse {
    HttpResponse::build(status).json(ApiError { error })
}

pub fn json_config() -> JsonConfig {
    JsonConfig::default()
        .limit(MAX_PLAINTEXT_BYTES + 4096)
        .error_handler(|error, _request| {
            InternalError::from_response(
                error,
                json_error(StatusCode::BAD_REQUEST, "INVALID_JSON_REQUEST"),
            )
            .into()
        })
}

pub fn configure(config: &mut web::ServiceConfig) {
    config
        .route("/health", web::get().to(health))
        .route("/api/encrypt", web::post().to(encrypt))
        .route("/api/secrets/{id}", web::get().to(get_secret));
}

async fn health() -> HttpResponse {
    HttpResponse::Ok().json(HealthResponse {
        app_id: "aether",
        status: "preview-only",
        engine: "Rust + ring AES-256-GCM",
    })
}

async fn encrypt(
    state: web::Data<Arc<AppState>>,
    request: web::Json<EncryptRequest>,
) -> HttpResponse {
    let plaintext = request.into_inner().plaintext;
    if plaintext.is_empty() || plaintext.len() > MAX_PLAINTEXT_BYTES {
        return json_error(StatusCode::BAD_REQUEST, "INVALID_PLAINTEXT_SIZE");
    }

    let id = Uuid::new_v4().to_string();
    let key = Arc::clone(&state.key);
    let vault = state.vault.clone();
    let result = web::block(move || {
        let mut plaintext = plaintext;
        let encrypted = encrypt_blob(&key, id, plaintext.as_bytes());
        plaintext.zeroize();
        let blob = encrypted?;
        vault.save(&blob).map_err(|_| "VAULT_WRITE_FAILED")?;
        Ok::<_, &'static str>(blob)
    })
    .await;

    match result {
        Ok(Ok(blob)) => HttpResponse::Ok().json(EncryptResponse {
            id: blob.id,
            ciphertext: STANDARD.encode(blob.ciphertext),
            nonce: STANDARD.encode(blob.nonce),
            created_at: blob.created_at,
            status: "encrypted_and_stored",
        }),
        Ok(Err(error)) => json_error(StatusCode::INTERNAL_SERVER_ERROR, error),
        Err(_) => json_error(StatusCode::INTERNAL_SERVER_ERROR, "VAULT_OPERATION_FAILED"),
    }
}

async fn get_secret(state: web::Data<Arc<AppState>>, path: web::Path<String>) -> HttpResponse {
    let Ok(id) = Uuid::parse_str(path.as_str()) else {
        return json_error(StatusCode::BAD_REQUEST, "INVALID_SECRET_ID");
    };
    let id = id.to_string();
    let vault = state.vault.clone();
    let result = web::block(move || vault.get(&id)).await;

    match result {
        Ok(Ok(Some(blob))) => HttpResponse::Ok().json(EncryptResponse {
            id: blob.id,
            ciphertext: STANDARD.encode(blob.ciphertext),
            nonce: STANDARD.encode(blob.nonce),
            created_at: blob.created_at,
            status: "encrypted",
        }),
        Ok(Ok(None)) => json_error(StatusCode::NOT_FOUND, "SECRET_NOT_FOUND"),
        Ok(Err(_)) | Err(_) => json_error(StatusCode::INTERNAL_SERVER_ERROR, "VAULT_READ_FAILED"),
    }
}

fn encrypt_blob(key: &CryptoKey, id: String, plaintext: &[u8]) -> Result<EncryptedBlob, &'static str> {
    let rng = SystemRandom::new();
    let mut nonce = [0_u8; NONCE_LEN];
    rng.fill(&mut nonce).map_err(|_| "CRYPTO_OPERATION_FAILED")?;
    let unbound_key =
        UnboundKey::new(&AES_256_GCM, &key.0).map_err(|_| "CRYPTO_OPERATION_FAILED")?;
    let sealing_key = LessSafeKey::new(unbound_key);
    let mut ciphertext = plaintext.to_vec();
    sealing_key
        .seal_in_place_append_tag(
            Nonce::assume_unique_for_key(nonce),
            Aad::from(id.as_bytes()),
            &mut ciphertext,
        )
        .map_err(|_| "CRYPTO_OPERATION_FAILED")?;
    let created_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "CLOCK_UNAVAILABLE")?
        .as_secs()
        .try_into()
        .map_err(|_| "CLOCK_UNAVAILABLE")?;
    Ok(EncryptedBlob {
        id,
        ciphertext,
        nonce: nonce.to_vec(),
        created_at,
    })
}

#[cfg(test)]
mod tests {
    use actix_web::{App, http::StatusCode, test, web};
    use base64::{Engine as _, engine::general_purpose::STANDARD};
    use ring::{
        aead::{Aad, AES_256_GCM, LessSafeKey, Nonce, UnboundKey},
    };
    use serde_json::{Value, json};
    use std::sync::Arc;

    use super::{
        AppState, CryptoKey, EncryptedBlob, MAX_PLAINTEXT_BYTES, Vault, configure,
        decode_master_key,
    };

    fn decrypt(key: &[u8; 32], blob: &EncryptedBlob) -> Result<Vec<u8>, &'static str> {
        let unbound_key =
            UnboundKey::new(&AES_256_GCM, key).map_err(|_| "invalid key")?;
        let opening_key = LessSafeKey::new(unbound_key);
        let nonce: [u8; 12] = blob
            .nonce
            .as_slice()
            .try_into()
            .map_err(|_| "invalid nonce")?;
        let mut ciphertext = blob.ciphertext.clone();
        let plaintext = opening_key
            .open_in_place(
                Nonce::assume_unique_for_key(nonce),
                Aad::from(blob.id.as_bytes()),
                &mut ciphertext,
            )
            .map_err(|_| "authentication failed")?;
        Ok(plaintext.to_vec())
    }

    #[test]
    fn encrypts_with_random_nonce_and_authenticated_id() {
        let key = CryptoKey([7; 32]);
        let first = super::encrypt_blob(&key, "secret-1".to_owned(), b"classified")
            .expect("encryption should succeed");
        let second = super::encrypt_blob(&key, "secret-2".to_owned(), b"classified")
            .expect("encryption should succeed");
        assert_ne!(first.nonce, second.nonce);
        assert_eq!(decrypt(&key.0, &first).expect("authenticated decryption"), b"classified");

        let tampered = EncryptedBlob {
            id: "another-id".to_owned(),
            ..first
        };
        assert!(decrypt(&key.0, &tampered).is_err());
    }

    #[test]
    fn rejects_invalid_key_sizes() {
        assert_eq!(decode_master_key(&STANDARD.encode([1; 32])), Ok([1; 32]));
        assert!(decode_master_key(&STANDARD.encode([1; 31])).is_err());
        assert!(decode_master_key("not base64").is_err());
    }

    #[test]
    fn vault_persists_ciphertext_not_plaintext() {
        let vault = Vault::in_memory().expect("in-memory SQLite vault");
        let blob = super::encrypt_blob(&CryptoKey([9; 32]), "id-1".to_owned(), b"plaintext")
            .expect("encryption should succeed");
        vault.save(&blob).expect("encrypted blob should be saved");
        let loaded = vault
            .get("id-1")
            .expect("vault query should succeed")
            .expect("saved blob should exist");
        assert_eq!(loaded, blob);
        assert!(!loaded.ciphertext.windows(9).any(|part| part == b"plaintext"));
    }

    #[actix_web::test]
    async fn api_encrypts_persists_and_returns_only_ciphertext() {
        let vault = Vault::in_memory().expect("in-memory SQLite vault");
        let state = Arc::new(AppState::new([3; 32], vault.clone()));
        let app = test::init_service(
            App::new()
                .app_data(web::Data::from(state))
                .app_data(super::json_config())
                .configure(configure),
        )
        .await;
        let health = test::call_and_read_body_json::<_, _, Value>(
            &app,
            test::TestRequest::get().uri("/health").to_request(),
        )
        .await;
        assert_eq!(health["appId"], "aether");
        assert_eq!(health["status"], "preview-only");

        let request = test::TestRequest::post()
            .uri("/api/encrypt")
            .set_json(json!({"plaintext": "secret value"}))
            .to_request();
        let response = test::call_service(&app, request).await;
        assert_eq!(response.status(), StatusCode::OK);
        let body: Value = test::read_body_json(response).await;
        assert_eq!(body["status"], "encrypted_and_stored");
        assert_ne!(body["ciphertext"], "secret value");
        let id = body["id"].as_str().expect("response id");
        let saved = vault
            .get(id)
            .expect("vault query")
            .expect("encrypted payload persisted");
        assert_eq!(STANDARD.encode(saved.ciphertext), body["ciphertext"]);
        assert_eq!(STANDARD.encode(saved.nonce), body["nonce"]);
    }

    #[actix_web::test]
    async fn api_rejects_empty_and_oversized_plaintext() {
        let vault = Vault::in_memory().expect("in-memory SQLite vault");
        let state = Arc::new(AppState::new([5; 32], vault));
        let app = test::init_service(
            App::new()
                .app_data(web::Data::from(state))
                .app_data(super::json_config())
                .configure(configure),
        )
        .await;
        for plaintext in ["".to_owned(), "x".repeat(MAX_PLAINTEXT_BYTES + 1)] {
            let request = test::TestRequest::post()
                .uri("/api/encrypt")
                .set_json(json!({"plaintext": plaintext}))
                .to_request();
            let response = test::call_service(&app, request).await;
            assert_eq!(response.status(), StatusCode::BAD_REQUEST);
        }
    }

    #[actix_web::test]
    async fn api_returns_ciphertext_for_existing_id_and_404_for_missing_id() {
        let vault = Vault::in_memory().expect("in-memory SQLite vault");
        let state = Arc::new(AppState::new([6; 32], vault));
        let app = test::init_service(
            App::new()
                .app_data(web::Data::from(state))
                .app_data(super::json_config())
                .configure(configure),
        )
        .await;
        let response = test::call_service(
            &app,
            test::TestRequest::post()
                .uri("/api/encrypt")
                .set_json(json!({"plaintext": "persist me"}))
                .to_request(),
        )
        .await;
        let created: Value = test::read_body_json(response).await;
        let id = created["id"].as_str().expect("response id");
        let fetched = test::call_service(
            &app,
            test::TestRequest::get()
                .uri(&format!("/api/secrets/{id}"))
                .to_request(),
        )
        .await;
        assert_eq!(fetched.status(), StatusCode::OK);
        let fetched_body: Value = test::read_body_json(fetched).await;
        assert_eq!(fetched_body["id"], id);
        assert_eq!(fetched_body["ciphertext"], created["ciphertext"]);

        let missing = test::call_service(
            &app,
            test::TestRequest::get()
                .uri("/api/secrets/4f3c3fe2-2cc0-44b8-9a12-111111111111")
                .to_request(),
        )
        .await;
        assert_eq!(missing.status(), StatusCode::NOT_FOUND);
    }
}
