use axum_server::tls_rustls::RustlsConfig;
use rio_accounts::endpoint_policy::{ENDPOINT_DOCUMENT_LIMIT, StagingEndpointPlan};
use rio_accounts::{AppState, DevConfig, router, router_with_cmv_storage};
use std::{
    ffi::OsString,
    io::{self, Read, Write},
    net::SocketAddr,
};

fn main() {
    let arguments: Vec<OsString> = std::env::args_os().skip(1).collect();
    if arguments
        .first()
        .is_some_and(|argument| argument == "--check-staging-endpoints")
    {
        // Pure endpoint-component validation. Do not initialize the async runtime,
        // environment configuration, TLS files, database, provider or listener.
        if arguments.len() != 1 || check_staging_endpoints().is_err() {
            eprintln!("RIO staging endpoint component rejected.");
            std::process::exit(1);
        }
        return;
    }
    if run(arguments).is_err() {
        // Deliberately omit error details: provider responses and config can contain secrets.
        eprintln!("RIO synthetic development service could not start.");
        std::process::exit(1);
    }
}

fn check_staging_endpoints() -> io::Result<()> {
    let mut input = Vec::new();
    io::stdin()
        .lock()
        .take((ENDPOINT_DOCUMENT_LIMIT + 1) as u64)
        .read_to_end(&mut input)?;
    let plan = StagingEndpointPlan::from_endpoint_json(&input).map_err(io::Error::other)?;
    let mut output = io::stdout().lock();
    serde_json::to_writer(&mut output, &plan.summary())?;
    output.write_all(b"\n")
}

#[tokio::main]
async fn run(arguments: Vec<OsString>) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let config = DevConfig::from_env()?;
    if arguments == ["--recovery-fence"] {
        AppState::recovery_fence(&config).await?;
        println!("RIO synthetic restore fence committed; restored sessions stay closed.");
        return Ok(());
    }
    let cmv = arguments == ["--cmv-storage"];
    if !arguments.is_empty() && !cmv {
        return Err(std::io::Error::other("unsupported synthetic service command").into());
    }
    let tls = RustlsConfig::from_pem_file(&config.tls_cert, &config.tls_key).await?;
    let state = AppState::discover(&config).await?;
    let app = if cmv {
        router_with_cmv_storage(state).await?
    } else {
        router(state)
    };
    let address = SocketAddr::from(([127, 0, 0, 1], 8088));
    println!("RIO SYNTHETIC_ONLY: https://localhost:8088; ACCOUNT-1 HOLD");
    axum_server::bind_rustls(address, tls)
        .serve(app.into_make_service())
        .await?;
    Ok(())
}
