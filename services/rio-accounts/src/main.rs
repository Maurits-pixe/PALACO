use axum_server::tls_rustls::RustlsConfig;
use rio_accounts::{AppState, DevConfig, router};
use std::net::SocketAddr;

#[tokio::main]
async fn main() {
    if run().await.is_err() {
        // Deliberately omit error details: provider responses and config can contain secrets.
        eprintln!("RIO synthetic development service could not start.");
        std::process::exit(1);
    }
}

async fn run() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let config = DevConfig::from_env()?;
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    if arguments == ["--recovery-fence"] {
        AppState::recovery_fence(&config).await?;
        println!("RIO synthetic restore fence committed; restored sessions stay closed.");
        return Ok(());
    }
    if !arguments.is_empty() {
        return Err(std::io::Error::other("unsupported synthetic service command").into());
    }
    let tls = RustlsConfig::from_pem_file(&config.tls_cert, &config.tls_key).await?;
    let state = AppState::discover(&config).await?;
    let address = SocketAddr::from(([127, 0, 0, 1], 8088));
    println!("RIO SYNTHETIC_ONLY: https://localhost:8088; ACCOUNT-1 HOLD");
    axum_server::bind_rustls(address, tls)
        .serve(router(state).into_make_service())
        .await?;
    Ok(())
}
