"""
Database backups and restore verification.

A backup nobody has ever restored is a hypothesis, not a safety net. Everything
here exists so the hypothesis can be tested from the UI without a shell on the
host: `create_backup` writes a `pg_dump` archive plus a manifest, and
`verify_backup` restores that archive into a scratch database, counts what came
back, and throws the scratch database away.

Two manifest fields are worth explaining:

- **Row counts.** A restore that "succeeds" into an empty database is the
  failure mode that looks most like success. Recording counts at dump time and
  comparing them after a test restore is what turns "it ran" into "it worked".
- **An encryption-key fingerprint.** Plaid access tokens are Fernet-encrypted
  with a key that lives in the environment, never in the dump. Restoring into a
  stack whose `ENCRYPTION_KEY` differs yields a database that looks perfect and
  whose every bank connection fails on the next sync. The fingerprint makes
  that mismatch visible before the restore rather than days after it.
"""

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.config import get_settings

settings = get_settings()

# Tables whose row counts are recorded and re-checked after a test restore.
# Deliberately the ones whose loss would actually hurt.
COUNTED_TABLES = (
    "households",
    "users",
    "household_members",
    "institution_connections",
    "accounts",
    "transactions",
    "categories",
    "category_groups",
    "categorization_rules",
    "budgets",
    "budget_lines",
    "net_worth_snapshots",
    "security_events",
)

FILENAME = re.compile(r"^raven-\d{8}T\d{6}Z\.dump$")
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class BackupInfo:
    name: str
    created_at: str
    bytes: int
    sha256: str
    app_version: str | None = None
    encryption_fingerprint: str | None = None
    row_counts: dict[str, int] | None = None
    verified_at: str | None = None
    verify_ok: bool | None = None
    verify_error: str | None = None


class BackupError(RuntimeError):
    """A backup or restore step failed in a way worth showing a person."""


def backup_dir() -> Path:
    return Path(settings.backup_dir)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def encryption_fingerprint() -> str:
    """
    A stable, non-reversible identifier for the key that encrypts provider
    tokens. Short enough to eyeball, long enough not to collide.
    """
    from app.security import fernet_key

    return hashlib.sha256(fernet_key()).hexdigest()[:16]


def libpq_dsn(database: str | None = None) -> tuple[str, str | None]:
    """
    Turn the app's SQLAlchemy URL into something libpq understands, returning
    the password separately so it is never placed on a command line where
    `ps` would show it.
    """
    parts = urlsplit(settings.database_url)
    password = unquote(parts.password) if parts.password else None
    user = unquote(parts.username) if parts.username else "postgres"
    host = parts.hostname or "postgres"
    port = parts.port or 5432
    name = database if database is not None else parts.path.lstrip("/")
    return f"postgresql://{user}@{host}:{port}/{name}", password


def _env(password: str | None) -> dict[str, str]:
    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password
    # Never let a hung TCP connect masquerade as a slow dump.
    env.setdefault("PGCONNECT_TIMEOUT", "10")
    return env


async def _run(
    *args: str, password: str | None, timeout: int | None = None
) -> tuple[int, str]:
    """Run a libpq tool, returning its exit code and trailing stderr."""
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=_env(password),
        )
    except FileNotFoundError as exc:
        raise BackupError(
            f"{args[0]} is not installed in this image. Backups need the "
            "PostgreSQL client tools."
        ) from exc
    try:
        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout or settings.backup_timeout_seconds
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise BackupError(
            f"{Path(args[0]).name} exceeded "
            f"{timeout or settings.backup_timeout_seconds}s and was stopped."
        ) from None
    return process.returncode or 0, (stderr or b"").decode()[-600:].strip()


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(name: str) -> Path:
    return backup_dir() / f"{name}.json"


def _write_manifest(info: BackupInfo) -> None:
    path = _manifest_path(info.name)
    path.write_text(json.dumps(asdict(info), indent=2))
    path.chmod(0o600)


def _read_manifest(name: str) -> dict:
    try:
        return json.loads(_manifest_path(name).read_text())
    except (OSError, ValueError):
        return {}


async def _row_counts() -> dict[str, int]:
    """
    Count from the live database through the app's own pool. Doing this
    separately from the dump keeps `pg_dump` a plain subprocess, and the small
    race against concurrent writes is acceptable — the counts are a smoke test,
    not an accounting record.
    """
    from sqlalchemy import text

    from app.database import SessionLocal

    counts: dict[str, int] = {}
    async with SessionLocal() as db:
        for table in COUNTED_TABLES:
            try:
                # Table names come from the constant above, never from input.
                # The identifier is selected only from COUNTED_TABLES above.
                result = await db.execute(
                    text(f'SELECT count(*) FROM "{table}"')  # nosec B608
                )
                counts[table] = int(result.scalar_one())
            except Exception:  # noqa: BLE001 - a missing table is not fatal here
                await db.rollback()
    return counts


async def create_backup(app_version: str | None = None) -> BackupInfo:
    """Write a compressed custom-format dump and its manifest."""
    directory = backup_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(
            f"Cannot write to {directory}: {exc}. Mount a writable volume at that path."
        ) from exc

    stamp = _now().strftime("%Y%m%dT%H%M%SZ")
    name = f"raven-{stamp}.dump"
    target = directory / name
    partial = directory / f"{name}.partial"
    dsn, password = libpq_dsn()

    counts = await _row_counts()
    code, stderr = await _run(
        "pg_dump",
        "--dbname",
        dsn,
        "--format=custom",
        "--compress=9",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(partial),
        password=password,
    )
    if code != 0:
        partial.unlink(missing_ok=True)
        raise BackupError(f"pg_dump failed: {stderr or 'no detail'}")

    # Only publish the final name once the dump is complete, so a crash or a
    # killed container can never leave something that looks restorable.
    partial.replace(target)
    target.chmod(0o600)

    info = BackupInfo(
        name=name,
        created_at=_now().isoformat(),
        bytes=target.stat().st_size,
        sha256=_digest(target),
        app_version=app_version,
        encryption_fingerprint=encryption_fingerprint(),
        row_counts=counts,
    )
    _write_manifest(info)
    prune_backups()
    return info


def list_backups() -> list[BackupInfo]:
    directory = backup_dir()
    if not directory.is_dir():
        return []
    found: list[BackupInfo] = []
    for path in directory.iterdir():
        if not FILENAME.match(path.name):
            continue
        manifest = _read_manifest(path.name)
        stat = path.stat()
        found.append(
            BackupInfo(
                name=path.name,
                created_at=manifest.get("created_at")
                or datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                bytes=stat.st_size,
                sha256=manifest.get("sha256", ""),
                app_version=manifest.get("app_version"),
                encryption_fingerprint=manifest.get("encryption_fingerprint"),
                row_counts=manifest.get("row_counts"),
                verified_at=manifest.get("verified_at"),
                verify_ok=manifest.get("verify_ok"),
                verify_error=manifest.get("verify_error"),
            )
        )
    return sorted(found, key=lambda item: item.name, reverse=True)


def resolve(name: str) -> Path:
    """Map a backup name to its path, refusing anything not of our own making."""
    if not FILENAME.match(name):
        raise BackupError("Not a backup file name.")
    path = backup_dir() / name
    if not path.is_file():
        raise BackupError("That backup no longer exists.")
    return path


def delete_backup(name: str) -> None:
    resolve(name).unlink()
    _manifest_path(name).unlink(missing_ok=True)


def prune_backups(keep: int | None = None) -> list[str]:
    """Keep the newest N archives; delete the rest with their manifests."""
    limit = settings.backup_keep if keep is None else keep
    if limit <= 0:
        return []
    removed = []
    for stale in list_backups()[limit:]:
        try:
            delete_backup(stale.name)
            removed.append(stale.name)
        except (BackupError, OSError):
            continue
    return removed


async def verify_backup(name: str) -> dict:
    """
    Restore an archive into a scratch database, count what arrived, then throw
    the scratch database away.

    This is the whole point of the module. It is non-destructive: production
    tables are never touched, so it is safe to run on a schedule and safe to
    expose as a button.
    """
    path = resolve(name)
    manifest = _read_manifest(name)
    started = time.monotonic()

    expected_digest = manifest.get("sha256")
    actual_digest = _digest(path)
    if expected_digest and expected_digest != actual_digest:
        result = {
            "ok": False,
            "error": (
                "The archive on disk no longer matches the checksum recorded "
                "when it was written. Treat it as corrupt."
            ),
        }
        _record_verification(name, manifest, result)
        return result

    scratch = f"raven_verify_{_now().strftime('%H%M%S')}_{os.getpid() % 10000}"
    admin_dsn, password = libpq_dsn("postgres")
    scratch_dsn, _ = libpq_dsn(scratch)

    code, stderr = await _run(
        "psql",
        "--dbname",
        admin_dsn,
        "--quiet",
        "--no-psqlrc",
        "--set=ON_ERROR_STOP=1",
        "--command",
        f'CREATE DATABASE "{scratch}"',
        password=password,
    )
    if code != 0:
        result = {
            "ok": False,
            "error": (
                "Could not create a scratch database to restore into: "
                f"{stderr or 'no detail'}"
            ),
        }
        _record_verification(name, manifest, result)
        return result

    try:
        code, stderr = await _run(
            "pg_restore",
            "--dbname",
            scratch_dsn,
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            str(path),
            password=password,
        )
        if code != 0:
            result = {"ok": False, "error": f"pg_restore failed: {stderr}"}
            _record_verification(name, manifest, result)
            return result
        restored = await _scratch_counts(scratch_dsn, password)
    finally:
        # Always reclaim the scratch database, including after a failure.
        await _run(
            "psql",
            "--dbname",
            admin_dsn,
            "--quiet",
            "--no-psqlrc",
            "--command",
            f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)',
            password=password,
        )

    expected = manifest.get("row_counts") or {}
    shortfalls = {
        table: {"expected": count, "restored": restored.get(table, 0)}
        for table, count in expected.items()
        # More rows than the manifest recorded is normal: the database keeps
        # taking writes after a dump. Fewer means something was lost.
        if restored.get(table, 0) < count
    }
    key_matches = (
        manifest.get("encryption_fingerprint") == encryption_fingerprint()
        if manifest.get("encryption_fingerprint")
        else None
    )

    result = {
        "ok": not shortfalls,
        "restored_counts": restored,
        "expected_counts": expected,
        "shortfalls": shortfalls,
        "encryption_key_matches": key_matches,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "error": (
            "Rows are missing from the restored copy: " + ", ".join(sorted(shortfalls))
            if shortfalls
            else None
        ),
    }
    _record_verification(name, manifest, result)
    return result


async def _scratch_counts(dsn: str, password: str | None) -> dict[str, int]:
    """
    Count rows in the restored copy. Uses asyncpg directly rather than the
    app's engine, which is bound to the production database.
    """
    import asyncpg

    counts: dict[str, int] = {}
    connection = await asyncpg.connect(dsn, password=password, timeout=15)
    try:
        for table in COUNTED_TABLES:
            try:
                counts[table] = int(
                    # The identifier is selected only from COUNTED_TABLES above.
                    await connection.fetchval(
                        f'SELECT count(*) FROM "{table}"'  # nosec B608
                    )
                )
            except asyncpg.PostgresError:
                counts[table] = 0
    finally:
        await connection.close()
    return counts


def _record_verification(name: str, manifest: dict, result: dict) -> None:
    """Remember the outcome so the UI can show when a backup was last proven."""
    manifest.update(
        {
            "name": name,
            "verified_at": _now().isoformat(),
            "verify_ok": bool(result.get("ok")),
            "verify_error": result.get("error"),
        }
    )
    try:
        _manifest_path(name).write_text(json.dumps(manifest, indent=2))
    except OSError:
        pass
