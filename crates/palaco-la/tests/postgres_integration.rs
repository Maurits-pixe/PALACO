use std::env;

#[test]
fn postgres_integration_gate_requires_database_url() {
    let database_url = env::var("DATABASE_URL")
        .expect("DATABASE_URL must be supplied by the PostgreSQL CI service");
    assert!(database_url.starts_with("postgres://"));
}
