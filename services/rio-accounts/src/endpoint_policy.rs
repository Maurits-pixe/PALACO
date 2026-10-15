//! Immutable endpoint bindings for the synthetic account boundary.
//!
//! Runtime selection remains fixed to the original loopback fixture. The public
//! staging type checks a future endpoint component only: it does not perform the
//! full staging-plan preflight, DNS, TLS, provider discovery, storage or startup.
//! No environment selector, release conversion or public field can activate it.

use serde::Deserialize;
use serde_json::{Value, json};
use std::{error::Error, fmt, sync::Arc};

/// Exact loopback browser origin.
pub const DEV_ORIGIN: &str = "https://localhost:8088";
/// Exact loopback synthetic issuer.
pub const DEV_ISSUER: &str = "http://127.0.0.1:8089/realms/rio-synthetic";
/// Exact confidential development client.
pub const DEV_CLIENT_ID: &str = "rio-bff";
/// Exact development authorization endpoint.
pub const DEV_AUTH_URL: &str =
    "http://127.0.0.1:8089/realms/rio-synthetic/protocol/openid-connect/auth";
/// Exact development token endpoint.
pub const DEV_TOKEN_URL: &str =
    "http://127.0.0.1:8089/realms/rio-synthetic/protocol/openid-connect/token";
/// Exact development signing-key endpoint.
pub const DEV_JWKS_URL: &str =
    "http://127.0.0.1:8089/realms/rio-synthetic/protocol/openid-connect/certs";
/// Exact development discovery endpoint.
pub const DEV_DISCOVERY_URL: &str =
    "http://127.0.0.1:8089/realms/rio-synthetic/.well-known/openid-configuration";
/// Exact development callback.
pub const DEV_CALLBACK: &str = "https://localhost:8088/auth/callback";

const STAGING_REALM: &str = "/realms/rio-synthetic-staging";
const STAGING_CLIENT: &str = "rio-bff-staging";
/// Maximum endpoint-component JSON bytes, including any surrounding whitespace.
pub const ENDPOINT_DOCUMENT_LIMIT: usize = 4096;

// No Debug or Deserialize implementation: endpoint values are not diagnostics,
// and callers cannot bypass constructors by filling fields or decoding this set.
struct EndpointSet {
    origin: String,
    authority: String,
    issuer: String,
    client_id: String,
    auth_url: String,
    token_url: String,
    jwks_url: String,
    discovery_url: String,
    callback: String,
}

fn allows_provider_request(
    discovery_url: &str,
    jwks_url: &str,
    token_url: &str,
    method: &str,
    uri: &str,
) -> bool {
    match method {
        "GET" => uri == discovery_url || uri == jwks_url,
        "POST" => uri == token_url,
        _ => false,
    }
}

fn request_matches(
    expected_authority: &str,
    scheme: Option<&str>,
    authority: Option<&str>,
    host: Option<&str>,
    is_http2: bool,
) -> bool {
    let uri_matches = match (scheme, authority) {
        (None, None) => true,
        (Some("https"), Some(value)) => value == expected_authority,
        _ => false,
    };
    // HTTP/2 carries :authority in the URI. An additional Host must agree.
    uri_matches
        && (host.is_some() || (is_http2 && authority.is_some()))
        && host.is_none_or(|value| value == expected_authority)
}

impl EndpointSet {
    fn metadata_matches(&self, issuer: &str, auth: &str, token: Option<&str>, jwks: &str) -> bool {
        issuer == self.issuer
            && auth == self.auth_url
            && token == Some(self.token_url.as_str())
            && jwks == self.jwks_url
    }
}

/// Internal runtime capability. Release builds can construct only the fixed dev set.
#[derive(Clone)]
pub(crate) struct RuntimeEndpoints {
    inner: Arc<EndpointSet>,
}

impl RuntimeEndpoints {
    pub(crate) fn loopback() -> Self {
        Self {
            inner: Arc::new(EndpointSet {
                origin: DEV_ORIGIN.to_owned(),
                authority: "localhost:8088".to_owned(),
                issuer: DEV_ISSUER.to_owned(),
                client_id: DEV_CLIENT_ID.to_owned(),
                auth_url: DEV_AUTH_URL.to_owned(),
                token_url: DEV_TOKEN_URL.to_owned(),
                jwks_url: DEV_JWKS_URL.to_owned(),
                discovery_url: DEV_DISCOVERY_URL.to_owned(),
                callback: DEV_CALLBACK.to_owned(),
            }),
        }
    }

    pub(crate) fn origin(&self) -> &str {
        &self.inner.origin
    }

    pub(crate) fn authority(&self) -> &str {
        &self.inner.authority
    }

    pub(crate) fn issuer(&self) -> &str {
        &self.inner.issuer
    }

    pub(crate) fn client_id(&self) -> &str {
        &self.inner.client_id
    }

    pub(crate) fn auth_url(&self) -> &str {
        &self.inner.auth_url
    }

    pub(crate) fn token_url(&self) -> &str {
        &self.inner.token_url
    }

    pub(crate) fn jwks_url(&self) -> &str {
        &self.inner.jwks_url
    }

    pub(crate) fn discovery_url(&self) -> &str {
        &self.inner.discovery_url
    }

    pub(crate) fn callback(&self) -> &str {
        &self.inner.callback
    }

    pub(crate) fn allows_provider_request(&self, method: &str, uri: &str) -> bool {
        allows_provider_request(
            self.discovery_url(),
            self.jwks_url(),
            self.token_url(),
            method,
            uri,
        )
    }

    pub(crate) fn metadata_matches(
        &self,
        issuer: &str,
        auth: &str,
        token: Option<&str>,
        jwks: &str,
    ) -> bool {
        self.inner.metadata_matches(issuer, auth, token, jwks)
    }

    pub(crate) fn request_matches(
        &self,
        scheme: Option<&str>,
        authority: Option<&str>,
        host: Option<&str>,
        is_http2: bool,
    ) -> bool {
        request_matches(self.authority(), scheme, authority, host, is_http2)
    }
}

/// Fixed error categories. They contain no submitted URL, JSON or private value.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StagingPlanError {
    /// An origin is not a canonical allowed HTTPS DNS origin.
    InvalidOrigin,
    /// Browser and identity-provider hosts are the same.
    HostIsolation,
    /// Endpoint JSON is malformed, oversized or has an unsupported shape.
    InvalidDocument,
    /// Declared endpoint paths or hostnames disagree with the derived profile.
    EndpointBinding,
}

impl fmt::Display for StagingPlanError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidOrigin => "INVALID_ORIGIN",
            Self::HostIsolation => "COOKIE_HOST_ISOLATION",
            Self::InvalidDocument => "INVALID_DOCUMENT",
            Self::EndpointBinding => "ENDPOINT_BINDING",
        })
    }
}

impl Error for StagingPlanError {}

/// A validated endpoint component for a future synthetic staging plan.
/// It performs only pure string/structure checks and cannot start the account service.
///
/// The internal runtime capability is not a public staging conversion:
///
/// ```compile_fail
/// use rio_accounts::endpoint_policy::StagingEndpointPlan;
/// # fn main() -> Result<(), Box<dyn std::error::Error>> {
/// let plan = StagingEndpointPlan::from_origins(
///     "https://rio.example.invalid",
///     "https://identity.example.invalid",
/// )?;
/// let _runtime: rio_accounts::endpoint_policy::RuntimeEndpoints = plan;
/// # Ok(())
/// # }
/// ```
///
/// Constructors do not resolve DNS, verify certificates, read secrets, perform
/// discovery or check the operator/release decisions of the full T05 preflight.
#[derive(Clone)]
pub struct StagingEndpointPlan {
    inner: Arc<EndpointSet>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct EndpointDocument {
    bff_origin: String,
    idp_issuer: String,
    callback_url: String,
    discovery_url: String,
    authorization_url: String,
    token_url: String,
    jwks_url: String,
}

fn canonical_https_host(origin: &str) -> Result<String, StagingPlanError> {
    if origin.is_empty()
        || origin.len() > 512
        || !origin.is_ascii()
        || origin.bytes().any(|byte| byte <= 32 || byte >= 127)
        || origin
            .bytes()
            .any(|byte| matches!(byte, b'%' | b'\\' | b'?' | b'#' | b'@'))
    {
        return Err(StagingPlanError::InvalidOrigin);
    }
    // Parsing performs no network I/O. Compare the original spelling to the
    // canonical host to reject parser normalization, including IPv4 aliases.
    let parsed = reqwest::Url::parse(origin).map_err(|_| StagingPlanError::InvalidOrigin)?;
    let host = parsed.host_str().ok_or(StagingPlanError::InvalidOrigin)?;
    if parsed.scheme() != "https"
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.port().is_some()
        || parsed.path() != "/"
        || parsed.query().is_some()
        || parsed.fragment().is_some()
        || origin != format!("https://{host}")
        || host.len() > 253
        || !host.contains('.')
        || host.ends_with(".localhost")
        || host.ends_with(".local")
    {
        return Err(StagingPlanError::InvalidOrigin);
    }
    let labels: Vec<&str> = host.split('.').collect();
    if labels
        .last()
        .is_none_or(|label| label.bytes().all(|byte| byte.is_ascii_digit()))
        || labels.iter().any(|label| {
            label.is_empty()
                || label.len() > 63
                || !label.as_bytes()[0].is_ascii_alphanumeric()
                || !label.as_bytes()[label.len() - 1].is_ascii_alphanumeric()
                || label.bytes().any(|byte| {
                    !(byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
                })
        })
    {
        return Err(StagingPlanError::InvalidOrigin);
    }
    Ok(host.to_owned())
}

impl StagingEndpointPlan {
    /// Validate two distinct canonical HTTPS DNS origins and derive the fixed staging paths.
    /// HTTPS default port is implicit: even an explicit :443 is rejected.
    pub fn from_origins(bff: &str, idp: &str) -> Result<Self, StagingPlanError> {
        let bff_host = canonical_https_host(bff)?;
        let idp_host = canonical_https_host(idp)?;
        if bff_host == idp_host {
            return Err(StagingPlanError::HostIsolation);
        }
        let issuer = format!("{idp}{STAGING_REALM}");
        let auth_url = format!("{issuer}/protocol/openid-connect/auth");
        let token_url = format!("{issuer}/protocol/openid-connect/token");
        let jwks_url = format!("{issuer}/protocol/openid-connect/certs");
        let discovery_url = format!("{issuer}/.well-known/openid-configuration");
        Ok(Self {
            inner: Arc::new(EndpointSet {
                origin: bff.to_owned(),
                authority: bff_host,
                issuer,
                client_id: STAGING_CLIENT.to_owned(),
                auth_url,
                token_url,
                jwks_url,
                discovery_url,
                callback: format!("{bff}/auth/callback"),
            }),
        })
    }

    /// Validate only the exact seven endpoint fields of the separate T05 plan.
    /// This input is not the full staging-plan schema. Null slots, unknown or
    /// duplicate fields, malformed UTF-8 and documents over 4096 bytes are rejected.
    pub fn from_endpoint_json(raw: &[u8]) -> Result<Self, StagingPlanError> {
        if raw.len() > ENDPOINT_DOCUMENT_LIMIT {
            return Err(StagingPlanError::InvalidDocument);
        }
        let document: EndpointDocument =
            serde_json::from_slice(raw).map_err(|_| StagingPlanError::InvalidDocument)?;
        let idp = document
            .idp_issuer
            .strip_suffix(STAGING_REALM)
            .ok_or(StagingPlanError::EndpointBinding)?;
        let plan = Self::from_origins(&document.bff_origin, idp)?;
        if document.idp_issuer != plan.inner.issuer
            || document.callback_url != plan.inner.callback
            || document.discovery_url != plan.inner.discovery_url
            || document.authorization_url != plan.inner.auth_url
            || document.token_url != plan.inner.token_url
            || document.jwks_url != plan.inner.jwks_url
        {
            return Err(StagingPlanError::EndpointBinding);
        }
        Ok(plan)
    }

    /// Compare a method and URI before any future provider network operation.
    /// Calling this pure predicate performs no operation itself.
    pub fn allows_provider_request(&self, method: &str, uri: &str) -> bool {
        allows_provider_request(
            &self.inner.discovery_url,
            &self.inner.jwks_url,
            &self.inner.token_url,
            method,
            uri,
        )
    }

    /// Compare discovered metadata strings to the fixed derived endpoint set.
    /// The caller's strings are not evidence that discovery actually occurred.
    pub fn metadata_matches(
        &self,
        issuer: &str,
        auth: &str,
        token: Option<&str>,
        jwks: &str,
    ) -> bool {
        self.inner.metadata_matches(issuer, auth, token, jwks)
    }

    /// Compare only URI authority and Host shape; this does not accept proxy headers,
    /// provide TLS evidence, check CSRF or authenticate a caller.
    pub fn request_matches(
        &self,
        scheme: Option<&str>,
        authority: Option<&str>,
        host: Option<&str>,
        is_http2: bool,
    ) -> bool {
        request_matches(&self.inner.authority, scheme, authority, host, is_http2)
    }

    /// Return only fixed scope/boundary fields; submitted origins are never diagnostics.
    pub fn summary(&self) -> Value {
        json!({
            "schemaVersion": "RIO_STAGING_ENDPOINT_COMPONENT_V1",
            "mode": "PLAN_ONLY",
            "checks": {
                "networkProbesPerformed": false,
                "dnsVerified": false,
                "tlsVerified": false,
                "providerMetadataVerified": false,
                "sourceVerified": false,
                "artifactDigestsVerified": false
            },
            "boundary": {
                "launchSupported": false,
                "deployAllowed": false,
                "account1": "HOLD",
                "humanAcceptance": "HOLD",
                "personalAccounts": false,
                "publicRegistration": false,
                "contact": false,
                "operativeAuthority": "NONE",
                "deployment": "HOLD"
            }
        })
    }

    // Test builds may exercise the actual in-memory router using planned bindings.
    // This method and capability path do not exist in release library builds.
    #[cfg(test)]
    pub(crate) fn test_endpoints(&self) -> RuntimeEndpoints {
        RuntimeEndpoints {
            inner: self.inner.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const BFF: &str = "https://rio.example.invalid";
    const IDP: &str = "https://identity.example.invalid";
    const ISSUER: &str = "https://identity.example.invalid/realms/rio-synthetic-staging";
    const AUTH: &str = "https://identity.example.invalid/realms/rio-synthetic-staging/protocol/openid-connect/auth";
    const TOKEN: &str = "https://identity.example.invalid/realms/rio-synthetic-staging/protocol/openid-connect/token";
    const JWKS: &str = "https://identity.example.invalid/realms/rio-synthetic-staging/protocol/openid-connect/certs";
    const DISCOVERY: &str = "https://identity.example.invalid/realms/rio-synthetic-staging/.well-known/openid-configuration";
    const CALLBACK: &str = "https://rio.example.invalid/auth/callback";
    const PRIVATE: &str = "PRIVATE_ENDPOINT_INPUT_CANARY";

    fn document() -> Value {
        json!({
            "bffOrigin": BFF,
            "idpIssuer": ISSUER,
            "callbackUrl": CALLBACK,
            "discoveryUrl": DISCOVERY,
            "authorizationUrl": AUTH,
            "tokenUrl": TOKEN,
            "jwksUrl": JWKS
        })
    }

    #[test]
    fn runtime_has_only_the_original_loopback_bindings_and_shared_immutable_storage() {
        let runtime = RuntimeEndpoints::loopback();
        let clone = runtime.clone();
        assert!(Arc::ptr_eq(&runtime.inner, &clone.inner));
        assert_eq!(runtime.origin(), "https://localhost:8088");
        assert_eq!(runtime.authority(), "localhost:8088");
        assert_eq!(runtime.issuer(), DEV_ISSUER);
        assert_eq!(runtime.client_id(), "rio-bff");
        assert_eq!(runtime.auth_url(), DEV_AUTH_URL);
        assert_eq!(runtime.token_url(), DEV_TOKEN_URL);
        assert_eq!(runtime.jwks_url(), DEV_JWKS_URL);
        assert_eq!(runtime.discovery_url(), DEV_DISCOVERY_URL);
        assert_eq!(runtime.callback(), "https://localhost:8088/auth/callback");
    }

    #[test]
    fn provider_methods_and_exact_bytes_are_closed_before_transport() {
        let runtime = RuntimeEndpoints::loopback();
        assert!(runtime.allows_provider_request("GET", DEV_DISCOVERY_URL));
        assert!(runtime.allows_provider_request("GET", DEV_JWKS_URL));
        assert!(runtime.allows_provider_request("POST", DEV_TOKEN_URL));
        for (method, uri) in [
            ("GET", DEV_TOKEN_URL),
            ("POST", DEV_DISCOVERY_URL),
            ("POST", DEV_JWKS_URL),
            ("HEAD", DEV_JWKS_URL),
            ("GET", DEV_AUTH_URL),
            ("get", DEV_JWKS_URL),
            ("GET", "https://attacker.example.invalid/certs"),
            (
                "GET",
                "http://127.0.0.1:8089/realms/other/protocol/openid-connect/certs",
            ),
            (
                "GET",
                "http://localhost:8089/realms/rio-synthetic/protocol/openid-connect/certs",
            ),
            (
                "GET",
                "http://127.0.0.1:8089/realms/rio-synthetic/protocol/openid-connect/certs?x=1",
            ),
            (
                "GET",
                "http://127.0.0.1:8089/realms/rio-synthetic/protocol/openid-connect/certs#x",
            ),
        ] {
            assert!(!runtime.allows_provider_request(method, uri));
        }
    }

    #[test]
    fn browser_origin_preserves_exact_relative_absolute_and_http2_rules() {
        let runtime = RuntimeEndpoints::loopback();
        assert!(runtime.request_matches(None, None, Some("localhost:8088"), false));
        assert!(runtime.request_matches(
            Some("https"),
            Some("localhost:8088"),
            Some("localhost:8088"),
            false
        ));
        assert!(runtime.request_matches(Some("https"), Some("localhost:8088"), None, true));
        for (scheme, authority, host, http2) in [
            (None, None, None, false),
            (None, None, None, true),
            (Some("https"), Some("localhost:8088"), None, false),
            (
                Some("http"),
                Some("localhost:8088"),
                Some("localhost:8088"),
                true,
            ),
            (None, Some("localhost:8088"), Some("localhost:8088"), true),
            (Some("https"), None, Some("localhost:8088"), true),
            (None, None, Some("LOCALHOST:8088"), false),
            (None, None, Some("localhost:8088 "), false),
            (
                Some("https"),
                Some("attacker.example.invalid"),
                Some("localhost:8088"),
                true,
            ),
            (
                Some("https"),
                Some("localhost:8088"),
                Some("attacker.example.invalid"),
                true,
            ),
        ] {
            assert!(!runtime.request_matches(scheme, authority, host, http2));
        }
    }

    #[test]
    fn provider_metadata_cannot_substitute_an_endpoint_or_omit_token() {
        let runtime = RuntimeEndpoints::loopback();
        assert!(runtime.metadata_matches(
            DEV_ISSUER,
            DEV_AUTH_URL,
            Some(DEV_TOKEN_URL),
            DEV_JWKS_URL
        ));
        for (issuer, auth, token, jwks) in [
            (ISSUER, DEV_AUTH_URL, Some(DEV_TOKEN_URL), DEV_JWKS_URL),
            (DEV_ISSUER, AUTH, Some(DEV_TOKEN_URL), DEV_JWKS_URL),
            (DEV_ISSUER, DEV_AUTH_URL, None, DEV_JWKS_URL),
            (DEV_ISSUER, DEV_AUTH_URL, Some(TOKEN), DEV_JWKS_URL),
            (DEV_ISSUER, DEV_AUTH_URL, Some(DEV_TOKEN_URL), JWKS),
        ] {
            assert!(!runtime.metadata_matches(issuer, auth, token, jwks));
        }
    }

    #[test]
    fn planned_profile_derives_exact_paths_and_cannot_use_dev_endpoints()
    -> Result<(), StagingPlanError> {
        let plan = StagingEndpointPlan::from_origins(BFF, IDP)?;
        assert!(plan.metadata_matches(ISSUER, AUTH, Some(TOKEN), JWKS));
        assert!(plan.allows_provider_request("GET", DISCOVERY));
        assert!(plan.allows_provider_request("GET", JWKS));
        assert!(plan.allows_provider_request("POST", TOKEN));
        assert!(!plan.allows_provider_request("GET", DEV_JWKS_URL));
        assert!(!plan.allows_provider_request("POST", DEV_TOKEN_URL));
        assert!(!plan.allows_provider_request("GET", AUTH));
        assert!(!plan.metadata_matches(
            DEV_ISSUER,
            DEV_AUTH_URL,
            Some(DEV_TOKEN_URL),
            DEV_JWKS_URL
        ));
        assert!(plan.request_matches(None, None, Some("rio.example.invalid"), false));
        assert!(plan.request_matches(Some("https"), Some("rio.example.invalid"), None, true));
        assert!(!plan.request_matches(None, None, Some("localhost:8088"), false));
        let test_only = plan.test_endpoints();
        assert!(Arc::ptr_eq(&plan.inner, &test_only.inner));
        assert_eq!(test_only.origin(), BFF);
        assert_eq!(test_only.callback(), CALLBACK);
        assert_eq!(test_only.client_id(), "rio-bff-staging");
        Ok(())
    }

    #[test]
    fn planned_origins_reject_normalization_controls_ports_ip_and_local_hosts() {
        for origin in [
            "",
            "http://rio.example.invalid",
            "HTTPS://rio.example.invalid",
            "https://RIO.example.invalid",
            "https://rio.example.invalid/",
            "https://rio.example.invalid:443",
            "https://rio.example.invalid:8443",
            "https://user@rio.example.invalid",
            "https://user:secret@rio.example.invalid",
            "https://rio.example.invalid?x=1",
            "https://rio.example.invalid#fragment",
            "https://rio.example.invalid/path/../",
            "https://rio.example.invalid.",
            "https://rio%2eexample.invalid",
            "https://rio.example.invalid\\x",
            " https://rio.example.invalid",
            "https://rio.example.invalid\n",
            "https://127.0.0.1",
            "https://2130706433",
            "https://0x7f.0.0.0x1",
            "https://[::1]",
            "https://localhost",
            "https://rio.localhost",
            "https://rio.local",
            "https://*.example.invalid",
            "https://río.example.invalid",
            "https://-rio.example.invalid",
            "https://rio-.example.invalid",
            "https://rio..example.invalid",
            "https://rio.example.123",
        ] {
            assert!(matches!(
                StagingEndpointPlan::from_origins(origin, IDP),
                Err(StagingPlanError::InvalidOrigin)
            ));
            assert!(matches!(
                StagingEndpointPlan::from_origins(BFF, origin),
                Err(StagingPlanError::InvalidOrigin)
            ));
        }
        let oversized_label = format!("https://{}.example.invalid", "a".repeat(64));
        assert!(StagingEndpointPlan::from_origins(&oversized_label, IDP).is_err());
        let oversized_host = format!(
            "https://{}.{}.{}.{}.invalid",
            "a".repeat(63),
            "b".repeat(63),
            "c".repeat(63),
            "d".repeat(63)
        );
        assert!(StagingEndpointPlan::from_origins(&oversized_host, IDP).is_err());
    }

    #[test]
    fn plan_requires_separate_cookie_hosts_and_has_fixed_errors() {
        assert!(matches!(
            StagingEndpointPlan::from_origins(BFF, BFF),
            Err(StagingPlanError::HostIsolation)
        ));
        for error in [
            StagingPlanError::InvalidOrigin,
            StagingPlanError::HostIsolation,
            StagingPlanError::InvalidDocument,
            StagingPlanError::EndpointBinding,
        ] {
            assert!(!error.to_string().contains(PRIVATE));
            assert!(!error.to_string().contains("https://"));
        }
        assert_eq!(
            StagingPlanError::HostIsolation.to_string(),
            "COOKIE_HOST_ISOLATION"
        );
    }

    #[test]
    fn endpoint_document_checks_actual_bindings_not_only_field_presence()
    -> Result<(), StagingPlanError> {
        let raw = document().to_string();
        let plan = StagingEndpointPlan::from_endpoint_json(raw.as_bytes())?;
        assert!(plan.metadata_matches(ISSUER, AUTH, Some(TOKEN), JWKS));
        for field in [
            "idpIssuer",
            "callbackUrl",
            "discoveryUrl",
            "authorizationUrl",
            "tokenUrl",
            "jwksUrl",
        ] {
            let mut changed = document();
            changed[field] = json!("https://attacker.example.invalid/");
            assert!(
                StagingEndpointPlan::from_endpoint_json(changed.to_string().as_bytes()).is_err()
            );
        }
        let mut callback = document();
        callback["callbackUrl"] = json!("https://identity.example.invalid/auth/callback");
        assert!(matches!(
            StagingEndpointPlan::from_endpoint_json(callback.to_string().as_bytes()),
            Err(StagingPlanError::EndpointBinding)
        ));
        Ok(())
    }

    #[test]
    fn endpoint_document_rejects_missing_duplicate_unknown_and_coerced_fields() {
        for field in [
            "bffOrigin",
            "idpIssuer",
            "callbackUrl",
            "discoveryUrl",
            "authorizationUrl",
            "tokenUrl",
            "jwksUrl",
        ] {
            let mut missing = document();
            if let Some(object) = missing.as_object_mut() {
                object.remove(field);
            }
            assert!(matches!(
                StagingEndpointPlan::from_endpoint_json(missing.to_string().as_bytes()),
                Err(StagingPlanError::InvalidDocument)
            ));
            for wrong_type in [Value::Null, json!(true), json!(0), json!([]), json!({})] {
                let mut changed = document();
                changed[field] = wrong_type;
                assert!(matches!(
                    StagingEndpointPlan::from_endpoint_json(changed.to_string().as_bytes()),
                    Err(StagingPlanError::InvalidDocument)
                ));
            }
        }
        let raw = document().to_string();
        for appended in [
            format!(r#","bffOrigin":"{BFF}""#),
            format!(r#","bff\u004frigin":"{BFF}""#),
            format!(r#","clientSecret":"{PRIVATE}""#),
            r#","launchSupported":true"#.to_owned(),
        ] {
            let duplicate_or_extra = format!("{}{}{}", &raw[..raw.len() - 1], appended, "}");
            assert!(matches!(
                StagingEndpointPlan::from_endpoint_json(duplicate_or_extra.as_bytes()),
                Err(StagingPlanError::InvalidDocument)
            ));
        }
    }

    #[test]
    fn endpoint_document_is_bounded_utf8_json_without_raw_failure_diagnostics()
    -> Result<(), StagingPlanError> {
        let raw = document().to_string();
        assert!(raw.len() < ENDPOINT_DOCUMENT_LIMIT);
        let exact_limit = format!("{raw}{}", " ".repeat(ENDPOINT_DOCUMENT_LIMIT - raw.len()));
        assert!(StagingEndpointPlan::from_endpoint_json(exact_limit.as_bytes()).is_ok());
        let over_limit = format!("{exact_limit} ");
        assert!(matches!(
            StagingEndpointPlan::from_endpoint_json(over_limit.as_bytes()),
            Err(StagingPlanError::InvalidDocument)
        ));
        for raw in [
            b"".as_slice(),
            b"{".as_slice(),
            b"null".as_slice(),
            b"\xff".as_slice(),
        ] {
            let error = StagingEndpointPlan::from_endpoint_json(raw).err();
            assert_eq!(error, Some(StagingPlanError::InvalidDocument));
        }
        let secret_input = format!(r#"{{"private":"{PRIVATE}"}}"#);
        let error = StagingEndpointPlan::from_endpoint_json(secret_input.as_bytes())
            .err()
            .ok_or(StagingPlanError::InvalidDocument)?;
        assert!(!error.to_string().contains(PRIVATE));
        assert!(!format!("{error:?}").contains(PRIVATE));
        Ok(())
    }

    #[test]
    fn plan_summary_never_includes_origins_or_grants_runtime_or_personal_access()
    -> Result<(), StagingPlanError> {
        let plan = StagingEndpointPlan::from_origins(BFF, IDP)?;
        let summary = plan.summary();
        assert_eq!(summary["mode"], "PLAN_ONLY");
        assert_eq!(
            summary["boundary"],
            json!({
                "launchSupported": false, "deployAllowed": false, "account1": "HOLD",
                "humanAcceptance": "HOLD", "personalAccounts": false,
                "publicRegistration": false, "contact": false,
                "operativeAuthority": "NONE", "deployment": "HOLD"
            })
        );
        if let Some(checks) = summary["checks"].as_object() {
            assert!(checks.values().all(|value| value == &json!(false)));
        } else {
            return Err(StagingPlanError::InvalidDocument);
        }
        let serialized = summary.to_string();
        assert!(!serialized.contains(BFF));
        assert!(!serialized.contains(IDP));
        assert!(!serialized.contains("rio-bff-staging"));
        assert!(!serialized.contains(PRIVATE));
        Ok(())
    }
}
