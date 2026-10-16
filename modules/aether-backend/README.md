# AETHER Rust Vault — local preview

This is a new, isolated backend candidate; the previous AETHER frontend source was not present in this checkout. It provides a small JSON API that encrypts UTF-8 plaintext with AES-256-GCM (`ring`) and persists only ciphertext and its nonce in SQLite (`rusqlite`). It does not replace or modify Bastion.

## Run locally

Use Rust 1.90 or newer. Generate a fresh 32-byte key outside the repository and start the backend:

```sh
export AETHER_MASTER_KEY="$(openssl rand -base64 32)"
cargo run --package aether-backend
```

The service listens only on `127.0.0.1:3006`. The SQLite file defaults to `modules/aether-backend/.aether-data/vault.sqlite3`; set `AETHER_DB_PATH` or `AETHER_PORT` to override the local path or port. Set the same key again after restarting to retain access to data. Losing or changing the key makes stored ciphertext unrecoverable; key rotation and recovery are not implemented.

The service uses plain HTTP on loopback for this preview. CORS allows only the launcher’s two local AETHER origins (`https://localhost:5174` and `https://127.0.0.1:5174`); this is a browser policy, not authentication. Do not expose the port through ngrok, a reverse proxy, or a network interface, and do not use real or shared secrets. There is no authentication, authorization, TLS, production key-management system, or frontend integration in this candidate.

## API

- `GET /health` returns the launcher identity with `status: "preview-only"`.
- `POST /api/encrypt` accepts `{"plaintext":"..."}` (1–65,536 UTF-8 bytes), stores the encrypted blob, and returns its ID, Base64 ciphertext, Base64 nonce, and creation time.
- `GET /api/secrets/{id}` returns the stored encrypted blob. No decryption endpoint is exposed.

The AES-GCM associated data binds each ciphertext to its UUID. Encryption uses a fresh cryptographically random 96-bit nonce per record. The master key is read from `AETHER_MASTER_KEY`; no key is hardcoded, returned, or stored in SQLite. The process zeroizes its in-memory key and request plaintext buffers on a best-effort basis; this does not guarantee removal of copies made by the operating system, allocator, or runtime.

## Checks

```sh
cargo fmt --all -- --check
cargo test --package aether-backend
cargo clippy --package aether-backend --all-targets -- -D warnings
```
