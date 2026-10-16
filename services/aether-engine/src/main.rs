use actix_web::{App, HttpRequest, HttpResponse, HttpServer, web};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use ring::{
    aead, hkdf, hmac,
    rand::{SecureRandom, SystemRandom},
};
use rusqlite::{Connection, OpenFlags, OptionalExtension, params};
use serde::{Deserialize, Serialize};
#[cfg(unix)]
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt};
use std::{
    env, fs, io,
    path::{Path, PathBuf},
};
use uuid::Uuid;

const MAX_BODY: usize = 262_144;
const MAX_PLAINTEXT: usize = 32_768;
const FRONTEND_ORIGINS: [&str; 2] = ["https://localhost:5174", "https://127.0.0.1:5174"];
const NEO_ORIGINS: [&str; 2] = ["https://localhost:5173", "https://127.0.0.1:5173"];

struct State {
    master_key: [u8; 32],
    auth_key: hmac::Key,
    token_tag: hmac::Tag,
    db_path: PathBuf,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct EncryptRequest {
    plaintext: String,
}

#[derive(Serialize, Deserialize)]
struct EncryptedRecord {
    id: String,
    ciphertext: String,
    nonce: String,
    algorithm: String,
    status: String,
}

fn decode_master_key(value: &str) -> Result<[u8; 32], &'static str> {
    STANDARD
        .decode(value)
        .map_err(|_| "AETHER_MASTER_KEY must be valid base64")?
        .try_into()
        .map_err(|_| "AETHER_MASTER_KEY must decode to exactly 32 bytes")
}

fn open_database(path: &Path) -> Result<Connection, rusqlite::Error> {
    let connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    connection.busy_timeout(std::time::Duration::from_secs(5))?;
    connection.pragma_update(None, "synchronous", "FULL")?;
    Ok(connection)
}

fn initialize_database(
    path: &Path,
    master_key: &[u8; 32],
) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        let mut directory = fs::DirBuilder::new();
        directory.recursive(true);
        #[cfg(unix)]
        directory.mode(0o700);
        directory.create(parent)?;
    }
    let mut options = fs::OpenOptions::new();
    options.read(true).write(true).create(true).truncate(false);
    #[cfg(unix)]
    options.mode(0o600);
    let file = options.open(path)?;
    #[cfg(unix)]
    {
        file.set_permissions(fs::Permissions::from_mode(0o600))?;
        for suffix in ["-wal", "-shm"] {
            let mut name = path.as_os_str().to_os_string();
            name.push(suffix);
            let sidecar = PathBuf::from(name);
            match fs::OpenOptions::new().read(true).write(true).open(sidecar) {
                Ok(file) => file.set_permissions(fs::Permissions::from_mode(0o600))?,
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
        }
    }
    drop(file);
    let mut connection = open_database(path)?;
    connection.pragma_update(None, "journal_mode", "WAL")?;
    let transaction = connection.transaction()?;
    transaction.execute_batch(
        "CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value BLOB NOT NULL);
         CREATE TABLE IF NOT EXISTS records (
             id TEXT PRIMARY KEY, ciphertext TEXT NOT NULL, nonce TEXT NOT NULL,
             algorithm TEXT NOT NULL, status TEXT NOT NULL CHECK(status = 'stored')
         );",
    )?;
    let key = hmac::Key::new(hmac::HMAC_SHA256, master_key);
    let check = hmac::sign(&key, b"aether/database-key-check/v1");
    transaction.execute(
        "INSERT OR IGNORE INTO settings (name, value) VALUES ('master_key_check', ?1)",
        [check.as_ref()],
    )?;
    let existing: Vec<u8> = transaction.query_row(
        "SELECT value FROM settings WHERE name = 'master_key_check'",
        [],
        |row| row.get(0),
    )?;
    hmac::verify(&key, b"aether/database-key-check/v1", &existing)
        .map_err(|_| io::Error::other("AETHER_MASTER_KEY does not match this database"))?;
    transaction.commit()?;
    Ok(())
}

fn record_key(master_key: &[u8; 32], id: &str) -> Result<aead::LessSafeKey, &'static str> {
    let salt = hkdf::Salt::new(hkdf::HKDF_SHA256, id.as_bytes());
    let prk = salt.extract(master_key);
    let info = [b"aether/record/aes-256-gcm/v1".as_slice()];
    let material = prk
        .expand(&info, &aead::AES_256_GCM)
        .map_err(|_| "key derivation failed")?;
    let mut bytes = [0u8; 32];
    material
        .fill(&mut bytes)
        .map_err(|_| "key derivation failed")?;
    let key =
        aead::UnboundKey::new(&aead::AES_256_GCM, &bytes).map_err(|_| "key creation failed")?;
    Ok(aead::LessSafeKey::new(key))
}

fn encrypt(master_key: &[u8; 32], plaintext: &str) -> Result<EncryptedRecord, &'static str> {
    let id = Uuid::new_v4().to_string();
    let key = record_key(master_key, &id)?;
    let mut nonce = [0u8; 12];
    SystemRandom::new()
        .fill(&mut nonce)
        .map_err(|_| "randomness unavailable")?;
    let mut ciphertext = plaintext.as_bytes().to_vec();
    key.seal_in_place_append_tag(
        aead::Nonce::assume_unique_for_key(nonce),
        aead::Aad::from(id.as_bytes()),
        &mut ciphertext,
    )
    .map_err(|_| "encryption failed")?;
    Ok(EncryptedRecord {
        id,
        ciphertext: STANDARD.encode(ciphertext),
        nonce: STANDARD.encode(nonce),
        algorithm: "AES-256-GCM".to_owned(),
        status: "stored".to_owned(),
    })
}

fn persist(path: &Path, record: &EncryptedRecord) -> Result<(), rusqlite::Error> {
    let connection = open_database(path)?;
    connection.execute(
        "INSERT INTO records (id, ciphertext, nonce, algorithm, status) VALUES (?1, ?2, ?3, ?4, ?5)",
        params![record.id, record.ciphertext, record.nonce, record.algorithm, record.status],
    )?;
    Ok(())
}

fn canonical_record_id(id: &str) -> bool {
    Uuid::parse_str(id).is_ok_and(|uuid| {
        uuid.get_version_num() == 4
            && uuid.get_variant() == uuid::Variant::RFC4122
            && uuid.to_string() == id
    })
}

fn open_read_database(path: &Path) -> Result<Connection, rusqlite::Error> {
    Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
}

fn stored_record(path: &Path, id: &str) -> Result<Option<EncryptedRecord>, rusqlite::Error> {
    let connection = open_read_database(path)?;
    let record = connection
        .query_row(
            "SELECT id,
                    CASE WHEN length(CAST(ciphertext AS BLOB)) <= 43712 THEN ciphertext END,
                    CASE WHEN length(CAST(nonce AS BLOB)) <= 16 THEN nonce END,
                    CASE WHEN length(CAST(algorithm AS BLOB)) <= 11 THEN algorithm END,
                    CASE WHEN length(CAST(status AS BLOB)) <= 6 THEN status END
             FROM records WHERE id = ?1",
            [id],
            |row| {
                Ok(EncryptedRecord {
                    id: row.get(0)?,
                    ciphertext: row.get(1)?,
                    nonce: row.get(2)?,
                    algorithm: row.get(3)?,
                    status: row.get(4)?,
                })
            },
        )
        .optional()?;
    if let Some(record) = &record {
        // Format checks only: readback does not authenticate or decrypt ciphertext.
        if record.id != id
            || record.algorithm != "AES-256-GCM"
            || record.status != "stored"
            || record.nonce.len() != 16
            || !STANDARD
                .decode(&record.nonce)
                .is_ok_and(|bytes| bytes.len() == 12)
            || record.ciphertext.len() > 43_712
            || !STANDARD
                .decode(&record.ciphertext)
                .is_ok_and(|bytes| (17..=MAX_PLAINTEXT + 16).contains(&bytes.len()))
        {
            return Err(rusqlite::Error::InvalidQuery);
        }
    }
    Ok(record)
}

fn error(status: actix_web::http::StatusCode, message: &str) -> HttpResponse {
    HttpResponse::build(status)
        .insert_header(("Cache-Control", "no-store"))
        .json(serde_json::json!({ "error": message }))
}

fn allowed_request(
    request: &HttpRequest,
    state: &State,
) -> Result<(), (actix_web::http::StatusCode, &'static str)> {
    if let Some(origin) = request.headers().get("Origin")
        && !origin
            .to_str()
            .is_ok_and(|value| FRONTEND_ORIGINS.contains(&value))
    {
        return Err((actix_web::http::StatusCode::FORBIDDEN, "Origin not allowed"));
    }
    let authorized = request
        .headers()
        .get("Authorization")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.split_once(' '))
        .filter(|(scheme, _)| *scheme == "Bearer")
        .map(|(_, token)| token)
        .is_some_and(|value| {
            hmac::verify(&state.auth_key, value.as_bytes(), state.token_tag.as_ref()).is_ok()
        });
    if !authorized {
        return Err((
            actix_web::http::StatusCode::UNAUTHORIZED,
            "Authentication required",
        ));
    }
    Ok(())
}

async fn encrypt_handler(
    request: HttpRequest,
    body: web::Bytes,
    state: web::Data<State>,
) -> HttpResponse {
    if let Err((status, message)) = allowed_request(&request, &state) {
        return error(status, message);
    }
    if request
        .headers()
        .get("Content-Type")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.split(';').next())
        .map(str::trim)
        != Some("application/json")
    {
        return error(
            actix_web::http::StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "JSON required",
        );
    }
    let payload = match serde_json::from_slice::<EncryptRequest>(&body) {
        Ok(payload)
            if !payload.plaintext.trim().is_empty() && payload.plaintext.len() <= MAX_PLAINTEXT =>
        {
            payload
        }
        _ => {
            return error(
                actix_web::http::StatusCode::BAD_REQUEST,
                "Provide 1 to 32768 bytes of nonblank plaintext",
            );
        }
    };
    let result = web::block(move || {
        let record = encrypt(&state.master_key, &payload.plaintext)?;
        persist(&state.db_path, &record).map_err(|_| "database write failed")?;
        Ok::<_, &'static str>(record)
    })
    .await;
    match result {
        Ok(Ok(record)) => HttpResponse::Created()
            .insert_header(("Cache-Control", "no-store"))
            .json(record),
        _ => error(
            actix_web::http::StatusCode::INTERNAL_SERVER_ERROR,
            "Operation could not be confirmed",
        ),
    }
}

async fn health() -> HttpResponse {
    HttpResponse::Ok()
        .insert_header(("Cache-Control", "no-store"))
        .json(serde_json::json!({ "status": "ready" }))
}

async fn record_handler(request: HttpRequest, state: web::Data<State>) -> HttpResponse {
    if let Err((status, message)) = allowed_request(&request, &state) {
        return error(status, message);
    }
    let id = request.match_info().get("id").unwrap_or_default();
    if !canonical_record_id(id) {
        return error(
            actix_web::http::StatusCode::BAD_REQUEST,
            "Provide a lowercase canonical v4 record UUID",
        );
    }
    let id = id.to_owned();
    match web::block(move || stored_record(&state.db_path, &id)).await {
        Ok(Ok(Some(record))) => HttpResponse::Ok()
            .insert_header(("Cache-Control", "no-store"))
            .json(record),
        Ok(Ok(None)) => error(actix_web::http::StatusCode::NOT_FOUND, "Record not found"),
        _ => error(
            actix_web::http::StatusCode::INTERNAL_SERVER_ERROR,
            "Stored record could not be read",
        ),
    }
}

async fn metadata(request: HttpRequest) -> HttpResponse {
    let mut response = HttpResponse::Ok();
    response.insert_header(("Cache-Control", "no-store"));
    response.insert_header(("Vary", "Origin"));
    if let Some(origin) = request
        .headers()
        .get("Origin")
        .and_then(|value| value.to_str().ok())
        && NEO_ORIGINS.contains(&origin)
    {
        response.insert_header(("Access-Control-Allow-Origin", origin));
    }
    response.json(serde_json::json!({ "appId": "aether", "status": "ready" }))
}

fn configure(cfg: &mut web::ServiceConfig) {
    cfg.app_data(web::PayloadConfig::new(MAX_BODY))
        .route("/api/encrypt", web::post().to(encrypt_handler))
        .route("/api/records/{id}", web::get().to(record_handler))
        .route("/health", web::get().to(health))
        .route("/.well-known/palaco-app.json", web::get().to(metadata));
}

#[actix_web::main]
async fn main() -> io::Result<()> {
    let value = env::var("AETHER_MASTER_KEY")
        .map_err(|_| io::Error::other("AETHER_MASTER_KEY is required"))?;
    let master_key = decode_master_key(&value).map_err(io::Error::other)?;
    let token = env::var("AETHER_API_TOKEN")
        .map_err(|_| io::Error::other("AETHER_API_TOKEN is required"))?;
    if token.len() < 32 || !token.bytes().all(|byte| byte.is_ascii_graphic()) {
        return Err(io::Error::other(
            "AETHER_API_TOKEN must contain at least 32 printable ASCII characters without spaces",
        ));
    }
    let db_path = PathBuf::from(
        env::var("AETHER_DB_PATH").unwrap_or_else(|_| "data/aether.sqlite3".to_owned()),
    );
    initialize_database(&db_path, &master_key)
        .map_err(|error| io::Error::other(format!("Database initialization failed: {error}")))?;
    let auth_key = hmac::Key::new(hmac::HMAC_SHA256, &master_key);
    let token_tag = hmac::sign(&auth_key, token.as_bytes());
    let state = web::Data::new(State {
        master_key,
        auth_key,
        token_tag,
        db_path,
    });
    println!("AETHER listening on http://127.0.0.1:3006");
    HttpServer::new(move || App::new().app_data(state.clone()).configure(configure))
        .bind(("127.0.0.1", 3006))?
        .run()
        .await
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::{http::StatusCode, test};

    #[test]
    async fn master_key_is_strict() {
        assert!(decode_master_key("").is_err());
        assert!(decode_master_key("not-base64").is_err());
        assert!(decode_master_key(&STANDARD.encode([1u8; 31])).is_err());
        assert_eq!(
            decode_master_key(&STANDARD.encode([7u8; 32])),
            Ok([7u8; 32])
        );
    }

    #[test]
    async fn encryption_roundtrip_authenticates_record_and_detects_tampering()
    -> Result<(), Box<dyn std::error::Error>> {
        let master = [42u8; 32];
        let record = encrypt(&master, "vertrouwelijk")?;
        let another = encrypt(&master, "vertrouwelijk")?;
        assert_ne!(record.id, another.id);
        assert_ne!(record.ciphertext, another.ciphertext);
        let nonce: [u8; 12] = STANDARD
            .decode(&record.nonce)?
            .try_into()
            .map_err(|_| "nonce length")?;
        let ciphertext = STANDARD.decode(&record.ciphertext)?;
        let mut decrypted = ciphertext.clone();
        let key = record_key(&master, &record.id)?;
        let plaintext = key
            .open_in_place(
                aead::Nonce::assume_unique_for_key(nonce),
                aead::Aad::from(record.id.as_bytes()),
                &mut decrypted,
            )
            .map_err(|_| "decryption failed")?;
        assert_eq!(plaintext, b"vertrouwelijk");
        let mut wrong_id = ciphertext.clone();
        assert!(
            key.open_in_place(
                aead::Nonce::assume_unique_for_key(nonce),
                aead::Aad::from(b"wrong-id"),
                &mut wrong_id
            )
            .is_err()
        );
        let mut tampered = ciphertext;
        tampered[0] ^= 1;
        assert!(
            key.open_in_place(
                aead::Nonce::assume_unique_for_key(nonce),
                aead::Aad::from(record.id.as_bytes()),
                &mut tampered
            )
            .is_err()
        );
        Ok(())
    }

    #[actix_web::test]
    async fn authenticated_readback_is_read_only_and_validates_storage()
    -> Result<(), Box<dyn std::error::Error>> {
        let path = PathBuf::from(format!("test-read-{}.sqlite3", Uuid::new_v4()));
        let master = [21u8; 32];
        initialize_database(&path, &master)?;
        let record = encrypt(&master, "readback fixture")?;
        persist(&path, &record)?;
        let auth_key = hmac::Key::new(hmac::HMAC_SHA256, &master);
        let session_token = "readback-test-session";
        let authorization = ["Bearer", session_token].join(" ");
        let wrong_authorization = ["Bearer", "incorrect-test-session"].join(" ");
        let token_tag = hmac::sign(&auth_key, session_token.as_bytes());
        let app = test::init_service(
            App::new()
                .app_data(web::Data::new(State {
                    master_key: master,
                    auth_key,
                    token_tag,
                    db_path: path.clone(),
                }))
                .configure(configure),
        )
        .await;
        let connection = open_database(&path)?;
        let database_before = fs::read(&path)?;
        let wal_path = PathBuf::from(format!("{}-wal", path.display()));
        let wal_before = fs::read(&wal_path)?;
        for (token, origin, id, expected) in [
            (None, None, "invalid", StatusCode::UNAUTHORIZED),
            (
                Some(wrong_authorization.as_str()),
                None,
                "invalid",
                StatusCode::UNAUTHORIZED,
            ),
            (
                Some(authorization.as_str()),
                Some("https://evil.example"),
                "invalid",
                StatusCode::FORBIDDEN,
            ),
            (
                Some(authorization.as_str()),
                Some("http://localhost:5174"),
                "invalid",
                StatusCode::FORBIDDEN,
            ),
            (
                Some(authorization.as_str()),
                Some("https://localhost:5174/"),
                "invalid",
                StatusCode::FORBIDDEN,
            ),
            (
                Some(authorization.as_str()),
                Some(NEO_ORIGINS[0]),
                "invalid",
                StatusCode::FORBIDDEN,
            ),
        ] {
            let mut request = test::TestRequest::get().uri(&format!("/api/records/{id}"));
            if let Some(token) = token {
                request = request.insert_header(("Authorization", token));
            }
            if let Some(origin) = origin {
                request = request.insert_header(("Origin", origin));
            }
            let response = test::call_service(&app, request.to_request()).await;
            assert_eq!(response.status(), expected);
            assert_eq!(
                response
                    .headers()
                    .get("Cache-Control")
                    .and_then(|value| value.to_str().ok()),
                Some("no-store")
            );
        }
        for id in [
            "invalid".to_owned(),
            "FAB30B51-63CE-44BF-B694-161C9050944D".to_owned(),
            record.id.replace('-', ""),
            "fab30b51-63ce-14bf-b694-161c9050944d".to_owned(),
            "fab30b51-63ce-44bf-7694-161c9050944d".to_owned(),
            "00000000-0000-0000-0000-000000000000".to_owned(),
        ] {
            let response = test::call_service(
                &app,
                test::TestRequest::get()
                    .uri(&format!("/api/records/{id}"))
                    .insert_header(("Authorization", authorization.as_str()))
                    .to_request(),
            )
            .await;
            assert_eq!(response.status(), StatusCode::BAD_REQUEST);
            assert_eq!(
                response
                    .headers()
                    .get("Cache-Control")
                    .and_then(|value| value.to_str().ok()),
                Some("no-store")
            );
        }
        for origin in [None, Some(FRONTEND_ORIGINS[0]), Some(FRONTEND_ORIGINS[1])] {
            let mut request = test::TestRequest::get()
                .uri(&format!("/api/records/{}", record.id))
                .insert_header(("Authorization", authorization.as_str()));
            if let Some(origin) = origin {
                request = request.insert_header(("Origin", origin));
            }
            let response = test::call_service(&app, request.to_request()).await;
            assert_eq!(response.status(), StatusCode::OK);
            assert_eq!(
                response
                    .headers()
                    .get("Cache-Control")
                    .and_then(|value| value.to_str().ok()),
                Some("no-store")
            );
            let body: serde_json::Value = test::read_body_json(response).await;
            assert_eq!(body, serde_json::to_value(&record)?);
        }
        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri(&format!("/api/records/{}", Uuid::new_v4()))
                .insert_header(("Authorization", authorization.as_str()))
                .to_request(),
        )
        .await;
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
        assert_eq!(
            response
                .headers()
                .get("Cache-Control")
                .and_then(|value| value.to_str().ok()),
            Some("no-store")
        );
        assert_eq!(fs::read(&path)?, database_before);
        assert_eq!(fs::read(&wal_path)?, wal_before);
        assert_eq!(
            connection.query_row("SELECT COUNT(*) FROM records", [], |row| row
                .get::<_, i64>(0))?,
            1
        );
        assert_eq!(
            serde_json::to_value(stored_record(&path, &record.id)?.ok_or("missing record")?)?,
            serde_json::to_value(&record)?
        );
        let reader = open_read_database(&path)?;
        assert!(reader.execute("DELETE FROM records", []).is_err());
        drop(reader);
        for (field, value) in [
            ("nonce", "bad".to_owned()),
            ("nonce", "x".repeat(65_536)),
            ("ciphertext", "bad".to_owned()),
            ("ciphertext", "AAAA\0".repeat(65_536)),
            ("ciphertext", STANDARD.encode([0u8; 16])),
            ("ciphertext", STANDARD.encode(vec![0u8; MAX_PLAINTEXT + 17])),
            ("algorithm", "unsupported".to_owned()),
            ("algorithm", "x".repeat(65_536)),
        ] {
            connection.execute(
                &format!("UPDATE records SET {field} = ?1 WHERE id = ?2"),
                params![value, record.id],
            )?;
            let response = test::call_service(
                &app,
                test::TestRequest::get()
                    .uri(&format!("/api/records/{}", record.id))
                    .insert_header(("Authorization", authorization.as_str()))
                    .to_request(),
            )
            .await;
            assert_eq!(response.status(), StatusCode::INTERNAL_SERVER_ERROR);
            assert_eq!(
                response
                    .headers()
                    .get("Cache-Control")
                    .and_then(|value| value.to_str().ok()),
                Some("no-store")
            );
            let body: serde_json::Value = test::read_body_json(response).await;
            assert_eq!(
                body,
                serde_json::json!({"error": "Stored record could not be read"})
            );
            connection.execute("DELETE FROM records", [])?;
            persist(&path, &record)?;
        }
        connection.execute_batch("DROP TABLE records")?;
        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri(&format!("/api/records/{}", record.id))
                .insert_header(("Authorization", authorization.as_str()))
                .to_request(),
        )
        .await;
        assert_eq!(response.status(), StatusCode::INTERNAL_SERVER_ERROR);
        assert_eq!(
            response
                .headers()
                .get("Cache-Control")
                .and_then(|value| value.to_str().ok()),
            Some("no-store")
        );
        assert_eq!(
            test::read_body_json::<serde_json::Value, _>(response).await,
            serde_json::json!({"error": "Stored record could not be read"})
        );
        drop(connection);
        drop(app);
        fs::remove_file(&path)?;
        assert!(stored_record(&path, &record.id).is_err());
        assert!(
            !path.exists(),
            "Readback must never create a missing database"
        );
        for suffix in ["-wal", "-shm"] {
            let sidecar = PathBuf::from(format!("{}{suffix}", path.display()));
            if sidecar.exists() {
                fs::remove_file(sidecar)?;
            }
        }
        Ok(())
    }

    #[actix_web::test]
    async fn authenticated_write_and_failure_contract() -> Result<(), Box<dyn std::error::Error>> {
        let path = PathBuf::from(format!("test-{}.sqlite3", Uuid::new_v4()));
        let master = [17u8; 32];
        initialize_database(&path, &master)?;
        assert!(initialize_database(&path, &[18u8; 32]).is_err());
        #[cfg(unix)]
        assert_eq!(fs::metadata(&path)?.permissions().mode() & 0o777, 0o600);
        let auth_key = hmac::Key::new(hmac::HMAC_SHA256, &master);
        let session_token = "test-session-token";
        let authorization = ["Bearer", session_token].join(" ");
        let token_tag = hmac::sign(&auth_key, session_token.as_bytes());
        let state = web::Data::new(State {
            master_key: master,
            auth_key,
            token_tag,
            db_path: path.clone(),
        });
        let app = test::init_service(App::new().app_data(state).configure(configure)).await;
        let unauthorized = test::TestRequest::post()
            .uri("/api/encrypt")
            .set_json(serde_json::json!({"plaintext":"secret"}))
            .to_request();
        assert_eq!(
            test::call_service(&app, unauthorized).await.status(),
            StatusCode::UNAUTHORIZED
        );
        let wrong_token = ["Bearer", "incorrect-test-session-token"].join(" ");
        let unauthorized = test::TestRequest::post()
            .uri("/api/encrypt")
            .insert_header(("Authorization", wrong_token))
            .set_json(serde_json::json!({"plaintext":"secret"}))
            .to_request();
        assert_eq!(
            test::call_service(&app, unauthorized).await.status(),
            StatusCode::UNAUTHORIZED
        );
        let forbidden = test::TestRequest::post()
            .uri("/api/encrypt")
            .insert_header(("Authorization", authorization.as_str()))
            .insert_header(("Origin", "https://evil.example"))
            .set_json(serde_json::json!({"plaintext":"secret"}))
            .to_request();
        assert_eq!(
            test::call_service(&app, forbidden).await.status(),
            StatusCode::FORBIDDEN
        );
        for plaintext in ["".to_owned(), " ".to_owned(), "x".repeat(MAX_PLAINTEXT + 1)] {
            let request = test::TestRequest::post()
                .uri("/api/encrypt")
                .insert_header(("Authorization", authorization.as_str()))
                .set_json(serde_json::json!({"plaintext":plaintext}))
                .to_request();
            assert_eq!(
                test::call_service(&app, request).await.status(),
                StatusCode::BAD_REQUEST
            );
        }
        let oversized = test::TestRequest::post()
            .uri("/api/encrypt")
            .insert_header(("Authorization", authorization.as_str()))
            .set_payload("x".repeat(MAX_BODY + 1))
            .to_request();
        assert_eq!(
            test::call_service(&app, oversized).await.status(),
            StatusCode::PAYLOAD_TOO_LARGE
        );
        let request = test::TestRequest::post()
            .uri("/api/encrypt")
            .insert_header(("Authorization", authorization.as_str()))
            .insert_header(("Origin", FRONTEND_ORIGINS[0]))
            .set_json(serde_json::json!({"plaintext":"secret"}))
            .to_request();
        let response = test::call_service(&app, request).await;
        assert_eq!(response.status(), StatusCode::CREATED);
        let record: EncryptedRecord = test::read_body_json(response).await;
        let connection = open_database(&path)?;
        let stored: String = connection.query_row(
            "SELECT ciphertext FROM records WHERE id = ?1",
            [&record.id],
            |row| row.get(0),
        )?;
        assert_eq!(stored, record.ciphertext);
        assert_ne!(stored, "secret");
        #[cfg(unix)]
        for suffix in ["", "-wal", "-shm"] {
            let file = PathBuf::from(format!("{}{suffix}", path.display()));
            assert_eq!(fs::metadata(file)?.permissions().mode() & 0o777, 0o600);
        }
        connection.execute_batch("DROP TABLE records")?;
        let failed = test::TestRequest::post()
            .uri("/api/encrypt")
            .insert_header(("Authorization", authorization.as_str()))
            .set_json(serde_json::json!({"plaintext":"secret"}))
            .to_request();
        assert_eq!(
            test::call_service(&app, failed).await.status(),
            StatusCode::INTERNAL_SERVER_ERROR
        );
        for origin in [
            NEO_ORIGINS[0],
            NEO_ORIGINS[1],
            "https://localhost:5175",
            "https://evil.example",
        ] {
            let request = test::TestRequest::get()
                .uri("/.well-known/palaco-app.json")
                .insert_header(("Origin", origin))
                .to_request();
            let response = test::call_service(&app, request).await;
            assert_eq!(
                response
                    .headers()
                    .contains_key("Access-Control-Allow-Origin"),
                NEO_ORIGINS.contains(&origin)
            );
            let body: serde_json::Value = test::read_body_json(response).await;
            assert_eq!(body["appId"], "aether");
            assert_eq!(body["status"], "ready");
        }
        drop(connection);
        drop(app);
        fs::remove_file(&path)?;
        for suffix in ["-wal", "-shm"] {
            let sidecar = PathBuf::from(format!("{}{suffix}", path.display()));
            if sidecar.exists() {
                fs::remove_file(sidecar)?;
            }
        }
        Ok(())
    }
}
