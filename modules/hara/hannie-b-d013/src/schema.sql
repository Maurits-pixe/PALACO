PRAGMA user_version=13;
CREATE TABLE calendars(id TEXT PRIMARY KEY, owner TEXT NOT NULL, tenant TEXT NOT NULL, write_acl INTEGER NOT NULL);
CREATE TABLE grants(id TEXT PRIMARY KEY, calendar_id TEXT NOT NULL REFERENCES calendars(id), owner TEXT NOT NULL, tenant TEXT NOT NULL, session TEXT NOT NULL, generation INTEGER NOT NULL, expires_at INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('ACTIVE','REVOKED')), action TEXT NOT NULL);
CREATE TABLE approvals(id TEXT PRIMARY KEY, grant_id TEXT NOT NULL REFERENCES grants(id), request_digest TEXT NOT NULL, context_digest TEXT NOT NULL, expires_at INTEGER NOT NULL, consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed IN (0,1)));
CREATE TABLE audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('DECISION','REVOKE')), operation_id TEXT UNIQUE, grant_id TEXT NOT NULL REFERENCES grants(id), binding TEXT NOT NULL);
CREATE TABLE decisions(operation_id TEXT PRIMARY KEY REFERENCES audit(operation_id), audit_seq INTEGER UNIQUE NOT NULL REFERENCES audit(seq), request_digest TEXT NOT NULL, context_digest TEXT NOT NULL, binding TEXT NOT NULL, precommit_observed_at INTEGER NOT NULL);
CREATE TABLE events(id TEXT PRIMARY KEY, calendar_id TEXT NOT NULL REFERENCES calendars(id), revision INTEGER NOT NULL CHECK(revision=1), title TEXT NOT NULL);
CREATE TABLE versions(event_id TEXT PRIMARY KEY REFERENCES events(id), revision INTEGER NOT NULL CHECK(revision=1), snapshot_digest TEXT NOT NULL);
CREATE TABLE receipts(operation_id TEXT PRIMARY KEY REFERENCES decisions(operation_id), binding TEXT NOT NULL);
