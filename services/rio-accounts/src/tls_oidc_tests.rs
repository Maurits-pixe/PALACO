//! Test-only HTTPS listener and real Keycloak browser login over TLS-backed storage.
use crate::{
    AppState,
    tls_database::{SyntheticTlsDbConfig, SyntheticTlsRestoreDbConfig},
};
use axum_server::{Handle, tls_rustls::RustlsConfig};
use serde_json::Value;
use std::{
    collections::HashMap,
    fs::{self, Metadata},
    io,
    net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener},
    path::{Path, PathBuf},
    process::{ExitStatus, Stdio},
    time::Duration,
};
#[cfg(unix)]
use std::{fs::File, io::Read};
use tokio::{
    process::{Child, Command},
    task::JoinHandle,
    time::timeout,
};

const ADDRESS: SocketAddr = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 8088);
const SCHEMA: &str = "rio-tls-oidc-browser-evidence/v1";
const IDS: [&str; 5] = [
    "RIO-E2E-01",
    "RIO-E2E-02",
    "RIO-E2E-03",
    "RIO-E2E-04",
    "RIO-E2E-05",
];

#[derive(Clone, Copy)]
enum ProofTarget {
    Primary,
    Restore,
}
impl ProofTarget {
    fn configuration(self) -> &'static str {
        match self {
            Self::Primary => "--config=playwright.tls-oidc.config.mjs",
            Self::Restore => "--config=playwright.tls-restore-oidc.config.mjs",
        }
    }
    fn summary(self) -> &'static str {
        match self {
            Self::Primary => "oidc-summary.json",
            Self::Restore => "restore-oidc-summary.json",
        }
    }
}

fn rejected() -> io::Error {
    io::Error::other("TLS OIDC proof rejected")
}

#[cfg(unix)]
fn same_file(left: &Metadata, right: &Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;
    left.dev() == right.dev() && left.ino() == right.ino() && left.uid() == right.uid()
}

#[cfg(unix)]
fn private_directory(path: &Path, owner: &Metadata) -> io::Result<Metadata> {
    use std::os::unix::fs::MetadataExt;
    let metadata = fs::symlink_metadata(path).map_err(|_| rejected())?;
    if !metadata.is_dir() || metadata.uid() != owner.uid() || metadata.mode() & 0o077 != 0 {
        return Err(rejected());
    }
    Ok(metadata)
}

#[cfg(unix)]
fn private_file(metadata: &Metadata, owner: &Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;
    metadata.is_file()
        && metadata.uid() == owner.uid()
        && metadata.mode() & 0o077 == 0
        && metadata.nlink() == 1
}

#[cfg(unix)]
fn read_private(root: &Path, name: &str, limit: u64, owner: &Metadata) -> io::Result<Vec<u8>> {
    let directory = private_directory(root, owner)?;
    let path = root.join(name);
    let before = fs::symlink_metadata(&path).map_err(|_| rejected())?;
    if !private_file(&before, owner) || before.len() > limit {
        return Err(rejected());
    }
    let file = File::open(&path).map_err(|_| rejected())?;
    let opened = file.metadata().map_err(|_| rejected())?;
    if !private_file(&opened, owner) || !same_file(&before, &opened) {
        return Err(rejected());
    }
    let mut bytes = Vec::new();
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| rejected())?;
    let after = fs::symlink_metadata(&path).map_err(|_| rejected())?;
    if bytes.len() as u64 > limit
        || !private_file(&after, owner)
        || !same_file(&opened, &after)
        || !same_file(&directory, &private_directory(root, owner)?)
    {
        return Err(rejected());
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_private(_root: &Path, _name: &str, _limit: u64, _owner: &Metadata) -> io::Result<Vec<u8>> {
    Err(rejected())
}

fn client_secret(input: &[u8], root: &Path) -> io::Result<String> {
    let text = std::str::from_utf8(input).map_err(|_| rejected())?;
    let mut values = HashMap::new();
    for line in text.lines().filter(|line| !line.is_empty()) {
        let (name, value) = line.split_once('=').ok_or_else(rejected)?;
        if values.insert(name, value).is_some() {
            return Err(rejected());
        }
    }
    let names = [
        "RIO_DEV_MODE",
        "RIO_DEV_CLIENT_SECRET",
        "RIO_DEV_TLS_CERT",
        "RIO_DEV_TLS_KEY",
        "RIO_DEV_DATABASE_URL",
        "RIO_PG_TEST_URL",
        "RIO_PG_RESTORE_TEST_URL",
    ];
    if values.len() != names.len()
        || !names.iter().all(|name| values.contains_key(name))
        || values.get("RIO_DEV_MODE") != Some(&"SYNTHETIC_ONLY")
    {
        return Err(rejected());
    }
    for (name, file) in [
        ("RIO_DEV_TLS_CERT", "tls-cert.pem"),
        ("RIO_DEV_TLS_KEY", "tls-key.pem"),
    ] {
        if values.get(name).map(Path::new) != Some(root.join(file).as_path()) {
            return Err(rejected());
        }
    }
    let secret = values.get("RIO_DEV_CLIENT_SECRET").ok_or_else(rejected)?;
    if secret.len() != 64 || !secret.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(rejected());
    }
    // Local plaintext database URL fields are intentionally not used by this TLS constructor.
    Ok((*secret).to_owned())
}

fn valid_summary(input: &[u8]) -> bool {
    let Ok(value) = serde_json::from_slice::<Value>(input) else {
        return false;
    };
    let Some(tests) = value["tests"].as_array() else {
        return false;
    };
    value["schema"] == SCHEMA
        && value["status"] == "passed"
        && value["suiteErrors"] == 0
        && tests.len() == IDS.len()
        && IDS
            .iter()
            .all(|id| tests.iter().filter(|test| test["id"] == *id).count() == 1)
        && tests.iter().all(|test| test["status"] == "passed")
}

struct Server {
    handle: Handle<SocketAddr>,
    task: JoinHandle<io::Result<()>>,
}
impl Drop for Server {
    fn drop(&mut self) {
        self.handle.shutdown();
        self.task.abort();
    }
}
impl Server {
    async fn start(state: AppState, certificate: Vec<u8>, key: Vec<u8>) -> io::Result<Self> {
        // Bind before spawning: a foreign process can never satisfy this test's readiness.
        let listener = TcpListener::bind(ADDRESS).map_err(|_| rejected())?;
        listener.set_nonblocking(true).map_err(|_| rejected())?;
        let tls = RustlsConfig::from_pem(certificate, key)
            .await
            .map_err(|_| rejected())?;
        let handle = Handle::new();
        let task = tokio::spawn(
            axum_server::from_tcp_rustls(listener, tls)
                .map_err(|_| rejected())?
                .handle(handle.clone())
                .serve(
                    crate::router_with_cmv_storage(state)
                        .await
                        .map_err(|_| rejected())?
                        .into_make_service(),
                ),
        );
        let server = Self { handle, task };
        let address = timeout(Duration::from_secs(5), server.handle.listening())
            .await
            .map_err(|_| rejected())?;
        if address != Some(ADDRESS) {
            return Err(rejected());
        }
        Ok(server)
    }
    async fn stop(mut self) -> io::Result<()> {
        self.handle.shutdown();
        timeout(Duration::from_secs(5), &mut self.task)
            .await
            .map_err(|_| rejected())?
            .map_err(|_| rejected())?
            .map_err(|_| rejected())
    }
}

async fn stop_browser(child: &mut Child) -> io::Result<()> {
    if child.try_wait().map_err(|_| rejected())?.is_some() {
        return Ok(());
    }
    #[cfg(unix)]
    if let Some(pid) = child.id() {
        // This unreaped Child reserves its PID. Give Playwright time to close Chromium.
        let _ = timeout(
            Duration::from_secs(2),
            Command::new("/bin/kill")
                .args(["-TERM", "--", &pid.to_string()])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status(),
        )
        .await;
    }
    match timeout(Duration::from_secs(8), child.wait()).await {
        Ok(Ok(_)) => Ok(()),
        _ => timeout(Duration::from_secs(5), child.kill())
            .await
            .map_err(|_| rejected())?
            .map_err(|_| rejected()),
    }
}

async fn browser(verification: &Path, target: ProofTarget) -> io::Result<ExitStatus> {
    let mut command = Command::new("node");
    command
        .current_dir(verification)
        .arg("node_modules/@playwright/test/cli.js")
        .args([
            "test",
            target.configuration(),
            "--global-timeout=120000",
            "--retries=0",
            "--workers=1",
        ])
        .kill_on_drop(true)
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    for (name, _) in std::env::vars_os() {
        let key = name.to_string_lossy().to_ascii_uppercase();
        if key.starts_with("RIO_")
            || key.starts_with("PG")
            || matches!(
                key.as_str(),
                "NODE_OPTIONS" | "DEBUG" | "PWDEBUG" | "HTTP_PROXY" | "HTTPS_PROXY" | "ALL_PROXY"
            )
        {
            command.env_remove(name);
        }
    }
    // Set only after removing inherited test selectors; the optional routes are
    // mandatory in this owned TLS proof and never inferred from a browser response.
    command.env("RIO_CMV_HTTP_PROOF", "1");
    let mut child = command.spawn().map_err(|_| rejected())?;
    match timeout(Duration::from_secs(145), child.wait()).await {
        Ok(Ok(status)) => Ok(status),
        _ => {
            stop_browser(&mut child).await?;
            Err(rejected())
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires owned TLS PostgreSQL, real synthetic Keycloak and installed Chromium"]
async fn postgres_tls_oidc_contract() -> io::Result<()> {
    oidc_contract(ProofTarget::Primary).await?;
    eprintln!("CASE T05_TLS_REAL_OIDC_BROWSER");
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires owned restored TLS PostgreSQL, real synthetic Keycloak and installed Chromium"]
async fn postgres_tls_restore_oidc_contract() -> io::Result<()> {
    // Complete source rows remain opaque in test memory, without Debug or public diagnostics.
    let before = crate::storage::tls_restore_tests::primary_snapshot()
        .await
        .map_err(|_| rejected())?;
    let result = oidc_contract(ProofTarget::Restore).await;
    let after = crate::storage::tls_restore_tests::primary_snapshot()
        .await
        .map_err(|_| rejected())?;
    if before == after {
        eprintln!("CASE CMV_OIDC_PRIMARY_UNCHANGED");
    } else {
        eprintln!("CASE CMV_OIDC_PRIMARY_CHANGED");
    }
    result?;
    if before != after {
        return Err(rejected());
    }
    eprintln!("CASE T05_TLS_RESTORE_REAL_OIDC_BROWSER");
    Ok(())
}

async fn oidc_contract(target: ProofTarget) -> io::Result<()> {
    let verification: PathBuf = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../verification/rio-accounts")
        .canonicalize()
        .map_err(|_| rejected())?;
    let tls_root = verification.join(".tls-runtime");
    let owner = fs::symlink_metadata(&tls_root).map_err(|_| rejected())?;
    let runtime = verification.join(".runtime");
    let secret = client_secret(
        &read_private(&runtime, "bff.env", 16_384, &owner)?,
        &runtime,
    )?;
    let certificate = read_private(&runtime, "tls-cert.pem", 16_384, &owner)?;
    let key = read_private(&runtime, "tls-key.pem", 16_384, &owner)?;
    // Verify the fixed credentials source ownership before the unchanged browser tests read it.
    let _ = read_private(&runtime, "test-credentials.json", 16_384, &owner)?;
    if !read_private(&tls_root, target.summary(), 32_768, &owner)?.is_empty() {
        return Err(rejected());
    }
    let password = String::from_utf8(read_private(&tls_root, "password", 128, &owner)?)
        .map_err(|_| rejected())?;
    let ca = read_private(&tls_root, "ca.der", 16_384, &owner)?;
    let state = match target {
        ProofTarget::Primary => {
            let database = SyntheticTlsDbConfig::for_test(
                "localhost",
                IpAddr::V4(Ipv4Addr::LOCALHOST),
                8091,
                password.trim(),
                &ca,
            )
            .map_err(|_| rejected())?;
            AppState::discover_tls_synthetic("SYNTHETIC_ONLY", &secret, &database).await
        }
        ProofTarget::Restore => {
            let database = SyntheticTlsRestoreDbConfig::for_test(password.trim(), &ca)
                .map_err(|_| rejected())?;
            AppState::discover_tls_synthetic_restore("SYNTHETIC_ONLY", &secret, &database).await
        }
    }
    .map_err(|_| rejected())?;
    if state.db.is_none()
        || !state.store.lock().await.sessions.is_empty()
        || state.endpoints.issuer() != crate::ISSUER
        || state.endpoints.client_id() != crate::CLIENT_ID
        || state.endpoints.origin() != crate::ORIGIN
        || state.endpoints.auth_url() != crate::AUTH_URL
        || state.endpoints.token_url() != crate::TOKEN_URL
        || state.endpoints.jwks_url() != crate::JWKS_URL
        || state.endpoints.discovery_url() != crate::DISCOVERY_URL
        || state.endpoints.callback() != crate::CALLBACK
    {
        return Err(rejected());
    }
    eprintln!("CASE CMV_OIDC_CONFIGURED");
    let server = Server::start(state.clone(), certificate, key).await?;
    eprintln!("CASE CMV_OIDC_SERVER_OPEN");
    let result = browser(&verification, target).await;
    eprintln!("CASE CMV_OIDC_BROWSER_COMPLETED");
    if result.as_ref().is_ok_and(|status| status.success()) {
        eprintln!("CASE CMV_OIDC_BROWSER_PASSED");
    }
    let stopped = server.stop().await;
    // Attempt exclusive rebinding before propagating any browser failure as well.
    let rebound = TcpListener::bind(ADDRESS).map(drop);
    if !result?.success()
        || stopped.is_err()
        || rebound.is_err()
        || !state.store.lock().await.sessions.is_empty()
        || !valid_summary(&read_private(&tls_root, target.summary(), 32_768, &owner)?)
    {
        return Err(rejected());
    }
    eprintln!("CASE CMV_OIDC_SUMMARY_VALID");
    Ok(())
}

#[test]
fn oidc_summary_needs_all_five_unique_successful_cases() {
    let good = serde_json::json!({"schema":SCHEMA,"status":"passed","suiteErrors":0,
        "tests":IDS.map(|id| serde_json::json!({"id":id,"status":"passed"}))});
    assert!(valid_summary(good.to_string().as_bytes()));
    for invalid in [
        serde_json::json!({}),
        serde_json::json!({"schema":SCHEMA,"status":"passed","suiteErrors":0,"tests":[]}),
    ] {
        assert!(!valid_summary(invalid.to_string().as_bytes()));
    }
    for field in ["status", "suiteErrors", "tests"] {
        let mut bad = good.clone();
        bad[field] = Value::Null;
        assert!(!valid_summary(bad.to_string().as_bytes()));
    }
    for status in ["failed", "skipped", "PRIVATE_CANARY"] {
        let mut bad = good.clone();
        bad["tests"][0]["status"] = Value::from(status);
        assert!(!valid_summary(bad.to_string().as_bytes()));
    }
    let mut duplicate = good.clone();
    duplicate["tests"][0] = duplicate["tests"][1].clone();
    assert!(!valid_summary(duplicate.to_string().as_bytes()));
}

#[test]
fn fixture_configuration_never_accepts_duplicate_keys_or_path_overrides() {
    let root = Path::new("/fixed-runtime");
    let valid = format!(
        "RIO_DEV_MODE=SYNTHETIC_ONLY\nRIO_DEV_CLIENT_SECRET={}\nRIO_DEV_TLS_CERT={}\nRIO_DEV_TLS_KEY={}\nRIO_DEV_DATABASE_URL=unused\nRIO_PG_TEST_URL=unused\nRIO_PG_RESTORE_TEST_URL=unused\n",
        "a".repeat(64),
        root.join("tls-cert.pem").display(),
        root.join("tls-key.pem").display()
    );
    assert!(client_secret(valid.as_bytes(), root).is_ok());
    for bad in [
        valid.clone() + "RIO_DEV_MODE=SYNTHETIC_ONLY\n",
        valid.replace("SYNTHETIC_ONLY", "PRODUCTION"),
        valid.replace("tls-key.pem", "PRIVATE_CANARY"),
        valid.replace(&"a".repeat(64), "PRIVATE_CANARY"),
        valid + "EXTRA=PRIVATE_CANARY\n",
    ] {
        assert_eq!(
            client_secret(bad.as_bytes(), root)
                .err()
                .map(|error| error.to_string()),
            Some("TLS OIDC proof rejected".to_owned())
        );
    }
}

#[cfg(unix)]
#[test]
fn fixture_reads_reject_links_unsafe_modes_and_oversize_without_echoing() -> io::Result<()> {
    use std::os::unix::fs::{PermissionsExt, symlink};
    struct Temporary(PathBuf);
    impl Drop for Temporary {
        fn drop(&mut self) {
            for name in ["input", "link", "alias"] {
                let _ = fs::remove_file(self.0.join(name));
            }
            let _ = fs::remove_dir(&self.0);
        }
    }
    let root = std::env::temp_dir().join(format!("rio-oidc-reader-{}", crate::random_token()));
    fs::create_dir(&root)?;
    let temporary = Temporary(root.clone());
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    let owner = fs::symlink_metadata(&root)?;
    fs::write(root.join("input"), b"PRIVATE_CANARY")?;
    fs::set_permissions(root.join("input"), fs::Permissions::from_mode(0o600))?;
    assert_eq!(read_private(&root, "input", 32, &owner)?, b"PRIVATE_CANARY");
    assert_eq!(
        read_private(&root, "input", 4, &owner)
            .err()
            .map(|e| e.to_string()),
        Some("TLS OIDC proof rejected".to_owned())
    );
    symlink(root.join("input"), root.join("link"))?;
    assert!(read_private(&root, "link", 32, &owner).is_err());
    fs::hard_link(root.join("input"), root.join("alias"))?;
    assert!(read_private(&root, "input", 32, &owner).is_err());
    fs::remove_file(root.join("alias"))?;
    fs::set_permissions(root.join("input"), fs::Permissions::from_mode(0o644))?;
    assert!(read_private(&root, "input", 32, &owner).is_err());
    fs::set_permissions(root.join("input"), fs::Permissions::from_mode(0o600))?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o755))?;
    assert!(read_private(&root, "input", 32, &owner).is_err());
    drop(temporary);
    Ok(())
}
