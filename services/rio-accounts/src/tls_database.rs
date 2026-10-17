//! Verified TLS transport for the existing closed synthetic PostgreSQL schema.
//! This module does not select an issuer, start a service, or grant account/contact authority.
//! The only trust anchor is one explicitly supplied DER CA; TLS and channel binding are mandatory.
use crate::storage::StoreError;
use rustls::{ClientConfig, RootCertStore, pki_types::CertificateDer};
use std::{
    net::IpAddr,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use tokio::{task::AbortHandle, time::timeout};
use tokio_postgres::{
    Client, Config,
    config::{ChannelBinding, SslMode},
};
use tokio_postgres_rustls::MakeRustlsConnect;
use x509_cert::{Certificate, Version, der::Decode, ext::pkix::BasicConstraints};

const CONNECT_TIMEOUT: Duration = Duration::from_secs(8);
const QUERY_TIMEOUT: Duration = Duration::from_secs(5);
const MAX_CA_BYTES: usize = 16_384;

/// Immutable, typed transport settings for SYNTHETIC_ONLY storage.
/// The role, database, port, trust store, and TLS policy cannot be overridden.
/// Credentials deliberately have no Debug implementation or public accessor.
///
/// ```compile_fail
/// use rio_accounts::tls_database::SyntheticTlsDbConfig;
/// fn reveal(config: SyntheticTlsDbConfig) {
///     println!("{config:?}");
/// }
/// ```
///
/// ```compile_fail
/// use rio_accounts::tls_database::SyntheticTlsDbConfig;
/// fn downgrade(mut config: SyntheticTlsDbConfig) {
///     config.postgres.ssl_mode(tokio_postgres::config::SslMode::Disable);
/// }
/// ```
pub struct SyntheticTlsDbConfig {
    postgres: Config,
    tls: ClientConfig,
}

/// Immutable TLS transport for the one isolated synthetic restore database.
/// Its destination cannot be used as an ordinary store configuration, and the
/// restore store validates and fences an existing snapshot before returning.
/// Credentials have no Debug implementation or public accessor.
///
/// ```compile_fail
/// use rio_accounts::tls_database::SyntheticTlsRestoreDbConfig;
/// fn reveal(config: SyntheticTlsRestoreDbConfig) {
///     println!("{config:?}");
/// }
/// ```
///
/// ```compile_fail
/// use rio_accounts::tls_database::{SyntheticTlsDbConfig, SyntheticTlsRestoreDbConfig};
/// fn select_primary(restore: SyntheticTlsRestoreDbConfig) -> SyntheticTlsDbConfig {
///     restore.into()
/// }
/// ```
pub struct SyntheticTlsRestoreDbConfig {
    transport: SyntheticTlsDbConfig,
}

impl SyntheticTlsRestoreDbConfig {
    /// Validate the same strict DNS, hex password, DER CA and required TLS policy
    /// as the primary transport. The role and restore database are fixed.
    pub fn new(host: &str, password: &str, ca_der: &[u8]) -> Result<Self, StoreError> {
        let mut transport = SyntheticTlsDbConfig::new(host, password, ca_der)?;
        transport.postgres.dbname("rio_synthetic_tls_restore");
        Ok(Self { transport })
    }

    /// Test-only restore addressing has exactly one loopback identity and socket.
    #[cfg(test)]
    pub(crate) fn for_test(password: &str, ca_der: &[u8]) -> Result<Self, StoreError> {
        let mut transport = SyntheticTlsDbConfig::for_test(
            "localhost",
            IpAddr::V4(std::net::Ipv4Addr::LOCALHOST),
            8091,
            password,
            ca_der,
        )?;
        transport.postgres.dbname("rio_synthetic_tls_restore");
        Ok(Self { transport })
    }

    pub(crate) async fn connect(&self) -> Result<TlsConnectionParts, StoreError> {
        self.transport.connect().await
    }
}

pub(crate) struct TlsConnectionParts {
    pub(crate) client: Client,
    pub(crate) healthy: Arc<AtomicBool>,
    pub(crate) connection: AbortHandle,
}

// Captured before spawning so cancellation also marks an unpolled task unhealthy.
struct ConnectionHealth(Arc<AtomicBool>);
impl Drop for ConnectionHealth {
    fn drop(&mut self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

// Initial verification owns cleanup, including when its caller cancels the future.
struct PendingConnection {
    healthy: Arc<AtomicBool>,
    connection: AbortHandle,
    armed: bool,
}
impl Drop for PendingConnection {
    fn drop(&mut self) {
        if self.armed {
            self.healthy.store(false, Ordering::SeqCst);
            self.connection.abort();
        }
    }
}

fn canonical_dns(host: &str) -> bool {
    if host.is_empty()
        || host.len() > 253
        || !host.is_ascii()
        || host.parse::<IpAddr>().is_ok()
        || !host.contains('.')
    {
        return false;
    }
    let mut labels = host.split('.');
    let valid = labels.all(|label| {
        !label.is_empty()
            && label.len() <= 63
            && label.as_bytes()[0].is_ascii_alphanumeric()
            && label.as_bytes()[label.len() - 1].is_ascii_alphanumeric()
            && label
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
    });
    let suffix = host.rsplit('.').next().unwrap_or_default();
    valid
        && reqwest::Url::parse(&format!("https://{host}"))
            .is_ok_and(|url| url.domain() == Some(host))
        && suffix.bytes().any(|b| b.is_ascii_lowercase())
        && !matches!(
            suffix,
            "localhost" | "localdomain" | "local" | "internal" | "lan" | "home"
        )
        && host != "home.arpa"
        && !host.ends_with(".home.arpa")
}

fn valid_password(password: &str) -> bool {
    (64..=128).contains(&password.len()) && password.bytes().all(|b| b.is_ascii_hexdigit())
}

fn tls_config(ca_der: &[u8]) -> Result<ClientConfig, StoreError> {
    if !(1..=MAX_CA_BYTES).contains(&ca_der.len()) {
        return Err(StoreError::Invalid);
    }
    // Decode consumes the entire DER input. PEM, concatenated certificates, and trailing data fail.
    let certificate = Certificate::from_der(ca_der).map_err(|_| StoreError::Invalid)?;
    let (_, constraints) = certificate
        .tbs_certificate
        .get::<BasicConstraints>()
        .map_err(|_| StoreError::Invalid)?
        .ok_or(StoreError::Invalid)?;
    if certificate.tbs_certificate.version != Version::V3 || !constraints.ca {
        return Err(StoreError::Invalid);
    }
    let mut roots = RootCertStore::empty();
    roots
        .add(CertificateDer::from(ca_der))
        .map_err(|_| StoreError::Invalid)?;
    ClientConfig::builder_with_provider(Arc::new(rustls::crypto::ring::default_provider()))
        .with_safe_default_protocol_versions()
        .map_err(|_| StoreError::Unavailable)
        .map(|builder| builder.with_root_certificates(roots).with_no_client_auth())
}

impl SyntheticTlsDbConfig {
    /// Validate a canonical lowercase ASCII DNS host, 64..128 hex password, and one DER CA.
    /// Validation completes without network I/O. Only port 5432, rio_dev, and rio_synthetic_tls exist.
    pub fn new(host: &str, password: &str, ca_der: &[u8]) -> Result<Self, StoreError> {
        if !canonical_dns(host) || !valid_password(password) {
            return Err(StoreError::Invalid);
        }
        Self::build(host, password, ca_der, 5432, None)
    }

    fn build(
        hostname: &str,
        password: &str,
        ca_der: &[u8],
        port: u16,
        host_addr: Option<IpAddr>,
    ) -> Result<Self, StoreError> {
        let tls = tls_config(ca_der)?;
        let mut postgres = Config::new();
        postgres
            .host(hostname)
            .port(port)
            .user("rio_dev")
            .dbname("rio_synthetic_tls")
            .password(password)
            .ssl_mode(SslMode::Require)
            .channel_binding(ChannelBinding::Require)
            .connect_timeout(CONNECT_TIMEOUT);
        if let Some(addr) = host_addr {
            postgres.hostaddr(addr);
        }
        Ok(Self { postgres, tls })
    }

    /// Test-only addressing separates certificate identity from the fixed local fixture socket.
    #[cfg(test)]
    pub(crate) fn for_test(
        hostname: &str,
        host_addr: IpAddr,
        port: u16,
        password: &str,
        ca_der: &[u8],
    ) -> Result<Self, StoreError> {
        if !(hostname == "localhost" || canonical_dns(hostname))
            || host_addr != IpAddr::V4(std::net::Ipv4Addr::LOCALHOST)
            || !matches!(port, 8092 | 8091)
            || !valid_password(password)
        {
            return Err(StoreError::Invalid);
        }
        Self::build(hostname, password, ca_der, port, Some(host_addr))
    }

    pub(crate) async fn connect(&self) -> Result<TlsConnectionParts, StoreError> {
        let connector = MakeRustlsConnect::new(self.tls.clone());
        let (client, connection) = timeout(CONNECT_TIMEOUT, self.postgres.connect(connector))
            .await
            .map_err(|_| StoreError::Unavailable)?
            .map_err(|_| StoreError::Unavailable)?;
        let healthy = Arc::new(AtomicBool::new(true));
        let health_on_exit = ConnectionHealth(healthy.clone());
        let task = tokio::spawn(async move {
            let _health_on_exit = health_on_exit;
            let _ = connection.await;
        });
        let connection = task.abort_handle();
        let mut pending = PendingConnection {
            healthy: healthy.clone(),
            connection: connection.clone(),
            armed: true,
        };
        timeout(QUERY_TIMEOUT, async {
            let row = client
                .query_one(
                    "SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid()",
                    &[],
                )
                .await
                .map_err(|_| StoreError::Unavailable)?;
            let encrypted: bool = row.try_get("ssl").map_err(|_| StoreError::Unavailable)?;
            let version: String = row
                .try_get("version")
                .map_err(|_| StoreError::Unavailable)?;
            if !encrypted
                || !matches!(version.as_str(), "TLSv1.2" | "TLSv1.3")
                || !healthy.load(Ordering::SeqCst)
            {
                return Err(StoreError::Unavailable);
            }
            Ok(())
        })
        .await
        .map_err(|_| StoreError::Unavailable)??;
        pending.armed = false;
        Ok(TlsConnectionParts {
            client,
            healthy,
            connection,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio_postgres::config::Host;

    // Parser-only certificate: no signing key exists and it is never used for a connection.
    // Live TLS tests use independently generated OpenSSL CAs and signed server certificates.
    fn der(tag: u8, contents: &[u8]) -> Vec<u8> {
        let mut value = vec![tag];
        if contents.len() < 128 {
            value.push(contents.len() as u8);
        } else if contents.len() <= 255 {
            value.extend_from_slice(&[0x81, contents.len() as u8]);
        } else {
            value.push(0x82);
            value.extend_from_slice(&(contents.len() as u16).to_be_bytes());
        }
        value.extend_from_slice(contents);
        value
    }

    fn sequence(parts: &[&[u8]]) -> Vec<u8> {
        der(0x30, &parts.concat())
    }

    fn parser_ca(ca: Option<bool>, duplicate: bool) -> Vec<u8> {
        let algorithm = sequence(&[&der(0x06, &[0x2b, 0x65, 0x70])]);
        let name = sequence(&[&der(
            0x31,
            &sequence(&[&der(0x06, &[0x55, 0x04, 0x03]), &der(0x0c, b"parser test")]),
        )]);
        let validity = sequence(&[&der(0x17, b"250101000000Z"), &der(0x17, b"490101000000Z")]);
        let mut key = vec![0];
        key.extend_from_slice(&[1; 32]);
        let spki = sequence(&[&algorithm, &der(0x03, &key)]);
        let mut fields = [
            der(0xa0, &der(0x02, &[2])),
            der(0x02, &[1]),
            algorithm.clone(),
            name.clone(),
            validity,
            name,
            spki,
        ]
        .concat();
        if let Some(is_ca) = ca {
            let constraints = if is_ca {
                sequence(&[&der(0x01, &[0xff])])
            } else {
                sequence(&[])
            };
            let extension = sequence(&[
                &der(0x06, &[0x55, 0x1d, 0x13]),
                &der(0x01, &[0xff]),
                &der(0x04, &constraints),
            ]);
            let extensions = if duplicate {
                sequence(&[&extension, &extension])
            } else {
                sequence(&[&extension])
            };
            fields.extend_from_slice(&der(0xa3, &extensions));
        }
        let mut signature = vec![0];
        signature.extend_from_slice(&[1; 64]);
        sequence(&[&der(0x30, &fields), &algorithm, &der(0x03, &signature)])
    }

    #[test]
    fn rejects_invalid_input_before_transport_exists() {
        let ca = parser_ca(Some(true), false);
        let password = "a".repeat(64);
        for host in [
            "",
            "localhost",
            "localhost.localdomain",
            "db.local",
            "db.localhost",
            "db.internal",
            "db.lan",
            "db.home",
            "db.home.arpa",
            "127.0.0.1",
            "127.000.000.001",
            "1.2.3.0x1",
            "0177.0.0.1",
            "2130706433",
            "[::1]",
            "::1",
            "db",
            "DB.example.invalid",
            "db.example.invalid.",
            "db..example.invalid",
            "-db.example.invalid",
            "db-.example.invalid",
            "db_1.example.invalid",
            "db.example.invalid:5432",
            "postgresql://db.example.invalid",
            "db.example.invalid?sslmode=disable",
            "db.example.invalid,user=other",
            "db.example.invalid/other",
            "déb.example.invalid",
        ] {
            assert!(matches!(
                SyntheticTlsDbConfig::new(host, &password, &ca),
                Err(StoreError::Invalid)
            ));
        }
        for password in [
            "a".repeat(63),
            "a".repeat(129),
            "g".repeat(64),
            "é".repeat(64),
        ] {
            assert!(matches!(
                SyntheticTlsDbConfig::new("db.example.invalid", &password, &ca),
                Err(StoreError::Invalid)
            ));
        }
        let label_too_long = format!("{}.example.invalid", "a".repeat(64));
        assert!(!canonical_dns(&label_too_long));
        assert!(!canonical_dns(&"a.".repeat(127)));
    }

    #[test]
    fn freezes_required_tls_and_closed_database_settings() {
        let ca = parser_ca(Some(true), false);
        let config = SyntheticTlsDbConfig::new("db.example.invalid", &"A".repeat(128), &ca)
            .expect("valid typed synthetic configuration");
        assert!(matches!(
            config.postgres.get_hosts(),
            [Host::Tcp(host)] if host == "db.example.invalid"
        ));
        assert!(config.postgres.get_hostaddrs().is_empty());
        assert_eq!(config.postgres.get_ports(), [5432]);
        assert_eq!(config.postgres.get_user(), Some("rio_dev"));
        assert_eq!(config.postgres.get_dbname(), Some("rio_synthetic_tls"));
        assert_eq!(config.postgres.get_ssl_mode(), SslMode::Require);
        assert_eq!(
            config.postgres.get_channel_binding(),
            ChannelBinding::Require
        );
        assert_eq!(
            config.postgres.get_connect_timeout(),
            Some(&CONNECT_TIMEOUT)
        );
        assert!(config.postgres.get_options().is_none());
        assert!(config.postgres.get_application_name().is_none());
        assert_eq!(
            config.tls.crypto_provider().cipher_suites,
            rustls::crypto::ring::default_provider().cipher_suites
        );
    }

    #[test]
    fn supplied_ca_is_one_complete_der_ca() {
        let valid = parser_ca(Some(true), false);
        assert!(tls_config(&valid).is_ok());
        let mut trailing = valid.clone();
        trailing.push(0);
        let mut concatenated = valid.clone();
        concatenated.extend_from_slice(&valid);
        for invalid in [
            Vec::new(),
            vec![0],
            vec![0; MAX_CA_BYTES + 1],
            b"-----BEGIN CERTIFICATE-----".to_vec(),
            trailing,
            concatenated,
            parser_ca(None, false),
            parser_ca(Some(false), false),
            parser_ca(Some(true), true),
        ] {
            assert!(matches!(tls_config(&invalid), Err(StoreError::Invalid)));
        }
    }

    #[test]
    fn restore_transport_has_a_separate_fixed_database_and_required_tls() {
        let ca = parser_ca(Some(true), false);
        let password = "a".repeat(64);
        let primary = SyntheticTlsDbConfig::new("db.example.invalid", &password, &ca)
            .expect("valid primary transport");
        let restore = SyntheticTlsRestoreDbConfig::new("db.example.invalid", &password, &ca)
            .expect("valid restore transport");
        assert_eq!(primary.postgres.get_dbname(), Some("rio_synthetic_tls"));
        let transport = &restore.transport;
        assert_eq!(
            transport.postgres.get_dbname(),
            Some("rio_synthetic_tls_restore")
        );
        assert!(
            matches!(transport.postgres.get_hosts(), [Host::Tcp(host)] if host == "db.example.invalid")
        );
        assert!(transport.postgres.get_hostaddrs().is_empty());
        assert_eq!(transport.postgres.get_ports(), [5432]);
        assert_eq!(transport.postgres.get_user(), Some("rio_dev"));
        assert_eq!(transport.postgres.get_ssl_mode(), SslMode::Require);
        assert_eq!(
            transport.postgres.get_channel_binding(),
            ChannelBinding::Require
        );
        assert_eq!(
            transport.postgres.get_connect_timeout(),
            Some(&CONNECT_TIMEOUT)
        );
        assert!(transport.postgres.get_options().is_none());
        assert!(transport.postgres.get_application_name().is_none());
        assert_eq!(
            transport.tls.crypto_provider().cipher_suites,
            rustls::crypto::ring::default_provider().cipher_suites
        );
        let fixture = SyntheticTlsRestoreDbConfig::for_test(&password, &ca)
            .expect("fixed loopback restore transport");
        assert_eq!(
            fixture.transport.postgres.get_dbname(),
            Some("rio_synthetic_tls_restore")
        );
        assert_eq!(fixture.transport.postgres.get_ports(), [8091]);
        assert_eq!(
            fixture.transport.postgres.get_hostaddrs(),
            [IpAddr::V4(std::net::Ipv4Addr::LOCALHOST)]
        );
        assert!(
            matches!(fixture.transport.postgres.get_hosts(), [Host::Tcp(host)] if host == "localhost")
        );
    }

    #[test]
    fn restore_transport_rejects_invalid_input_without_network_io() {
        let ca = parser_ca(Some(true), false);
        let password = "a".repeat(64);
        for host in [
            "localhost",
            "127.0.0.1",
            "db.internal",
            "DB.example.invalid",
            "db.example.invalid:5432",
            "db.example.invalid/other",
        ] {
            assert!(matches!(
                SyntheticTlsRestoreDbConfig::new(host, &password, &ca),
                Err(StoreError::Invalid)
            ));
        }
        for invalid in ["a".repeat(63), "a".repeat(129), "g".repeat(64)] {
            assert!(matches!(
                SyntheticTlsRestoreDbConfig::new("db.example.invalid", &invalid, &ca),
                Err(StoreError::Invalid)
            ));
            assert!(matches!(
                SyntheticTlsRestoreDbConfig::for_test(&invalid, &ca),
                Err(StoreError::Invalid)
            ));
        }
        for invalid in [
            Vec::new(),
            parser_ca(Some(false), false),
            vec![0; MAX_CA_BYTES + 1],
        ] {
            assert!(matches!(
                SyntheticTlsRestoreDbConfig::new("db.example.invalid", &password, &invalid),
                Err(StoreError::Invalid)
            ));
            assert!(matches!(
                SyntheticTlsRestoreDbConfig::for_test(&password, &invalid),
                Err(StoreError::Invalid)
            ));
        }
    }

    #[test]
    fn test_addressing_cannot_select_an_external_socket() {
        let ca = parser_ca(Some(true), false);
        let password = "a".repeat(64);
        let local = IpAddr::V4(std::net::Ipv4Addr::LOCALHOST);
        for hostname in ["localhost", "wrong.example.invalid"] {
            for port in [8092, 8091] {
                let config = SyntheticTlsDbConfig::for_test(hostname, local, port, &password, &ca)
                    .expect("fixed local test socket");
                assert_eq!(config.postgres.get_hostaddrs(), [local]);
                assert_eq!(config.postgres.get_ports(), [port]);
                assert_eq!(config.postgres.get_ssl_mode(), SslMode::Require);
                assert_eq!(
                    config.postgres.get_channel_binding(),
                    ChannelBinding::Require
                );
            }
        }
        for (addr, port) in [
            (IpAddr::V4(std::net::Ipv4Addr::new(127, 0, 0, 2)), 8091),
            (IpAddr::V4(std::net::Ipv4Addr::new(192, 0, 2, 1)), 8091),
            (IpAddr::V6(std::net::Ipv6Addr::LOCALHOST), 8091),
            (local, 5432),
            (local, 0),
        ] {
            assert!(matches!(
                SyntheticTlsDbConfig::for_test("localhost", addr, port, &password, &ca),
                Err(StoreError::Invalid)
            ));
        }
    }

    #[tokio::test]
    async fn connection_cancellation_closes_health() {
        let healthy = Arc::new(AtomicBool::new(true));
        let guard = ConnectionHealth(healthy.clone());
        let task = tokio::spawn(async move {
            let _guard = guard;
            std::future::pending::<()>().await;
        });
        task.abort();
        let _ = task.await;
        assert!(!healthy.load(Ordering::SeqCst));
    }
}
