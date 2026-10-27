FROM rust:1.98.1-bookworm AS build
WORKDIR /app
COPY services/rio-accounts/Cargo.toml services/rio-accounts/Cargo.lock ./
RUN mkdir src && printf 'fn main() {}' > src/main.rs && printf '' > src/lib.rs
RUN --mount=type=cache,target=/usr/local/cargo/registry cargo build --release --locked
COPY services/rio-accounts/src/ src/
COPY services/rio-accounts/migrations/ migrations/
RUN --mount=type=cache,target=/usr/local/cargo/registry touch src/main.rs src/lib.rs && \
    cargo build --release --locked

FROM python:3.13-slim-bookworm AS fixture
RUN apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY verification/rio-accounts/fixture.py verification/rio-accounts/fixture.py
CMD ["python", "verification/rio-accounts/fixture.py", "prepare"]

FROM debian:bookworm-slim AS gateway
RUN apt-get update && apt-get install -y --no-install-recommends socat curl && rm -rf /var/lib/apt/lists/*
USER 1000:1000
CMD ["socat", "TCP-LISTEN:8087,fork,reuseaddr,bind=0.0.0.0", "TCP:127.0.0.1:8088"]

FROM debian:bookworm-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app/target/release/rio-accounts-dev /usr/local/bin/rio-accounts-dev
USER 1000:1000
EXPOSE 8088
HEALTHCHECK --interval=10s --timeout=3s --start-period=120s CMD curl --fail --silent --cacert /app/verification/rio-accounts/.runtime/tls-cert.pem https://localhost:8088/healthz > /dev/null
CMD ["sh", "-ec", "set -a; . /app/verification/rio-accounts/.runtime/bff.env; exec rio-accounts-dev"]
