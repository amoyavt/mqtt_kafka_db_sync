# File tree
```
└─ postgres/
  ├─ postgresql.conf
  ├─ pg_hba.conf
  └─ init/
     └─ 01-create-debezium-user.sql
```

# What each file does
- **docker-compose.yml** — Runs Postgres with explicit configs and bootstraps initial SQL
- **postgres/postgresql.conf** — Server settings (logical replication, logging, auth)
- **postgres/pg_hba.conf** — Client access rules (who/where/how can connect)
- **postgres/init/01-create-debezium-user.sql** — One-time bootstrap: least-privilege Debezium user and read grants

# docker-compose.yml — Service: postgres - parameters explained

- **image**: `postgres:16-alpine` — Postgres 16 on a small base
- **container_name**: `pg16` — Stable name for `docker logs pg16`
- **ports**: `"5432:5432"` — Expose Postgres to host
- **environment**
  - `POSTGRES_USER` — Initial superuser created on first init (currently: `app`)
  - `POSTGRES_PASSWORD` — Password for that user (currently: `app_password_here`)
  - `POSTGRES_DB` — Default DB created at init (currently: `appdb`)
  - `POSTGRES_INITDB_ARGS` — Applies only on first init:
    - `--auth-host=scram-sha-256` → modern password hashing
    - `--data-checksums` → on-disk corruption detection
- **command**: `-c config_file=/etc/postgresql/postgresql.conf` — Force Postgres to use your mounted config
- **healthcheck**
  - `pg_isready -U app -d appdb -h localhost` — Reports healthy only when the DB accepts connections (good for deps)
- **volumes**
  - `./postgres/postgresql.conf:/etc/postgresql/postgresql.conf:ro` — Server config (read-only)
  - `./postgres/pg_hba.conf:/etc/postgresql/pg_hba.conf:ro` — Access rules (read-only)
  - `./postgres/init:/docker-entrypoint-initdb.d:ro` — Any .sql here runs once on first init
  - `pg_data:/var/lib/postgresql/data` — Persistent data volume (survives restarts)
- **restart**: `unless-stopped` — Auto-restart on crash/host reboot
- **volumes**: `pg_data` — Named volume definition for persistence

Tuning rule of thumb: start with the above; raise max_* and wal_keep_size only if you add more connectors or see WAL churn under lag.

# postgres/postgresql.conf — key settings
- `listen_addresses = '*'` — Accept TCP connections from any interface (needed in Docker)
- `wal_level = logical` — Required for Debezium/CDC (logical decoding)
- `max_wal_senders = 10` — Max concurrent replication clients
- `max_replication_slots = 10` — Reserve slots (≥ number of CDC consumers/connectors)
- `wal_keep_size = 1024MB` — WAL retention cushion so slow consumers don't break slots
- `wal_writer_delay = 10ms` — Lower CDC latency by flushing WAL more often (optional)
- `password_encryption = scram-sha-256` — Modern password hashing for new users
- `hba_file = '/etc/postgresql/pg_hba.conf'` — Point to your mounted HBA file
- `log_min_duration_statement = 500ms` — Log queries slower than 500ms
- `log_line_prefix = '%m [%p] %u@%d %r '` — Useful log context (time, pid, user@db, remote addr)

Tuning rule of thumb: start with the above; raise max_* and wal_keep_size only if you add more connectors or see WAL churn under lag.

# postgres/pg_hba.conf — access control rules

```
local all all trust
```
Local socket auth inside the container. Fine for dev; in prod prefer peer or SCRAM + users.

```
host all all 0.0.0.0/0 scram-sha-256
```
Allow TCP connections from anywhere using SCRAM. Tighten CIDR in prod (e.g., your Docker network).

```
host replication all 0.0.0.0/0 scram-sha-256
```
Allow replication clients (Debezium) over TCP with SCRAM.

Production hardening: replace 0.0.0.0/0 with your private CIDR, enable TLS, and switch to hostssl.

# postgres/init/01-create-debezium-user.sql — one-time bootstrap

- `CREATE ROLE debezium WITH LOGIN REPLICATION ...`  
  Minimal privileges to create a logical replication slot and stream WAL

- `GRANT USAGE ON SCHEMA public TO debezium;`  
  Access to schema metadata

- `GRANT SELECT ON ALL TABLES IN SCHEMA public TO debezium;`  
  Snapshot/read existing tables

- `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO debezium;`  
  Ensures future tables are readable without manual grants

- `(Optional) CREATE PUBLICATION dbz_publication FOR ALL TABLES;`  
  Precreate the publication if you don't let Debezium manage it

# Volumes — do you need them?
- **Config volumes** (postgresql.conf, pg_hba.conf, init/): Not strictly required for CDC, but they make the setup explicit, repeatable, and secure. You could replace with `command: -c key=val` and skip init SQL, but you'll lose clarity/least-privilege.

- **Data volume** (pg_data): Strongly recommended. Without it, recreating the container wipes your database.

# When to add more later (not now)
- Lots of connectors or high lag → bump `max_replication_slots`, `max_wal_senders`, and `wal_keep_size`
- Security hardening → TLS + stricter `pg_hba.conf`
- Tables without PK but needing UPDATE/DELETE events → `ALTER TABLE ... REPLICA IDENTITY FULL`

That's the whole picture—clean, explicit, and ready for Debezium.