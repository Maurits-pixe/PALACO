use std::{env, fs, io, path::PathBuf, sync::Arc};

use actix_cors::Cors;
use actix_web::{App, HttpServer, http::header};
use aether_backend::{AppState, configure, decode_master_key, open_vault};
use zeroize::Zeroize;

const DEFAULT_PORT: u16 = 3006;

#[actix_web::main]
async fn main() -> io::Result<()> {
    let mut encoded_key = env::var("AETHER_MASTER_KEY").map_err(|_| {
        io::Error::other("AETHER_MASTER_KEY must be set to a base64-encoded 32-byte key")
    })?;
    let key_result = decode_master_key(&encoded_key);
    encoded_key.zeroize();
    let key = key_result.map_err(io::Error::other)?;

    let database_path = env::var_os("AETHER_DB_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join(".aether-data")
                .join("vault.sqlite3")
        });
    if let Some(parent) = database_path.parent() {
        fs::create_dir_all(parent)?;
    }

    let vault = open_vault(&database_path)
        .map_err(|_| io::Error::other("Could not initialize the AETHER vault database"))?;
    let state = Arc::new(AppState::new(key, vault));
    let port = env::var("AETHER_PORT")
        .map_or(Ok(DEFAULT_PORT), |value| value.parse::<u16>())
        .map_err(|_| io::Error::other("AETHER_PORT must be a valid port number"))?;

    println!("AETHER preview backend listening on http://127.0.0.1:{port}");
    HttpServer::new(move || {
        let cors = Cors::default()
            .allowed_origin("https://localhost:5174")
            .allowed_origin("https://127.0.0.1:5174")
            .allowed_methods(["GET", "POST"])
            .allowed_headers([header::CONTENT_TYPE])
            .max_age(3600);
        App::new()
            .wrap(cors)
            .app_data(actix_web::web::Data::from(Arc::clone(&state)))
            .app_data(aether_backend::json_config())
            .configure(configure)
    })
    .bind(("127.0.0.1", port))?
    .shutdown_signal(async {
        let _ = tokio::signal::ctrl_c().await;
    })
    .run()
    .await
}
