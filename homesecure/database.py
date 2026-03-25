"""
HomeSecure Container Database
Identical schema to the HA integration's database.py, but with all
homeassistant.* imports removed.  Runs directly in the container process.
"""
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import bcrypt

_LOGGER = logging.getLogger(__name__)

# ── table names ───────────────────────────────────────────────────────────────
TABLE_USERS          = "alarm_users"
TABLE_CONFIG         = "alarm_config"
TABLE_EVENTS         = "alarm_events"
TABLE_FAILED_ATTEMPTS = "failed_attempts"
TABLE_ZONES          = "alarm_zones"

# ── defaults ──────────────────────────────────────────────────────────────────
DEFAULT_ENTRY_DELAY   = 30
DEFAULT_EXIT_DELAY    = 60
DEFAULT_ALARM_DURATION = 300
MAX_FAILED_ATTEMPTS   = 5
LOCKOUT_DURATION      = 300  # seconds
MAX_EVENTS            = 10_000  # rows kept in alarm_events before pruning

# ── valid config column names (allowlist for update_config) ───────────────────
VALID_CONFIG_KEYS = {
    "entry_delay", "exit_delay", "alarm_duration",
    "notification_mobile", "notification_sms", "sms_numbers",
    "lock_delay_home", "lock_delay_away",
    "close_delay_home", "close_delay_away",
    "auto_lock_on_arm_home", "auto_lock_on_arm_away",
    "auto_close_on_arm_home", "auto_close_on_arm_away",
    "lock_entities", "garage_entities", "lock_sync_interval",
    "service_pin",
    # security / behaviour settings (new in v2.0)
    "max_failed_attempts", "lockout_duration",
    "alarm_auto_action", "require_pin_to_arm",
    "log_retention_days",
}

# ── config value bounds (validated in update_config) ─────────────────────────
CONFIG_BOUNDS: Dict[str, tuple] = {
    "entry_delay":         (0,   300),
    "exit_delay":          (0,   300),
    "alarm_duration":      (30,  3600),
    "lock_delay_home":     (0,   600),
    "lock_delay_away":     (0,   600),
    "close_delay_home":    (0,   600),
    "close_delay_away":    (0,   600),
    "lock_sync_interval":  (60,  86400),
    "max_failed_attempts": (3,   20),
    "lockout_duration":    (60,  3600),
    "log_retention_days":  (7,   365),
}


class AlarmDatabase:
    """SQLite database for the HomeSecure container service."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_database()

    # ------------------------------------------------------------------ #
    #  Connection helpers                                                  #
    # ------------------------------------------------------------------ #

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")   # safe with WAL
        return conn

    # ------------------------------------------------------------------ #
    #  Schema                                                              #
    # ------------------------------------------------------------------ #

    def _init_database(self) -> None:
        with self._conn() as conn:
            cur = conn.cursor()

            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_USERS} (
                    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                    name                 TEXT NOT NULL,
                    pin_hash             TEXT NOT NULL,
                    is_admin             INTEGER DEFAULT 0,
                    is_duress            INTEGER DEFAULT 0,
                    enabled              INTEGER DEFAULT 1,
                    phone                TEXT,
                    email                TEXT,
                    has_separate_lock_pin INTEGER DEFAULT 0,
                    lock_pin_hash        TEXT,
                    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used            TIMESTAMP,
                    use_count            INTEGER DEFAULT 0
                )
            """)

            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_CONFIG} (
                    id                     INTEGER PRIMARY KEY DEFAULT 1,
                    entry_delay            INTEGER DEFAULT {DEFAULT_ENTRY_DELAY},
                    exit_delay             INTEGER DEFAULT {DEFAULT_EXIT_DELAY},
                    alarm_duration         INTEGER DEFAULT {DEFAULT_ALARM_DURATION},
                    trigger_doors          TEXT,
                    notification_mobile    INTEGER DEFAULT 1,
                    notification_sms       INTEGER DEFAULT 0,
                    sms_numbers            TEXT,
                    lock_delay_home        INTEGER DEFAULT 0,
                    lock_delay_away        INTEGER DEFAULT 60,
                    close_delay_home       INTEGER DEFAULT 0,
                    close_delay_away       INTEGER DEFAULT 60,
                    auto_lock_on_arm_home  INTEGER DEFAULT 0,
                    auto_lock_on_arm_away  INTEGER DEFAULT 1,
                    auto_close_on_arm_home INTEGER DEFAULT 0,
                    auto_close_on_arm_away INTEGER DEFAULT 1,
                    lock_entities          TEXT,
                    garage_entities        TEXT,
                    lock_sync_interval     INTEGER DEFAULT 3600,
                    -- security / behaviour (user-configurable)
                    max_failed_attempts    INTEGER DEFAULT 5,
                    lockout_duration       INTEGER DEFAULT 300,
                    alarm_auto_action      TEXT    DEFAULT 'none',
                    require_pin_to_arm     INTEGER DEFAULT 0,
                    log_retention_days     INTEGER DEFAULT 90,
                    updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_EVENTS} (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type     TEXT NOT NULL,
                    user_id        INTEGER,
                    user_name      TEXT,
                    timestamp      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    state_from     TEXT,
                    state_to       TEXT,
                    zone_entity_id TEXT,
                    details        TEXT,
                    is_duress      INTEGER DEFAULT 0
                )
            """)

            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_FAILED_ATTEMPTS} (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ip_address   TEXT,
                    user_code    TEXT,
                    attempt_type TEXT
                )
            """)

            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_ZONES} (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id         TEXT UNIQUE NOT NULL,
                    zone_name         TEXT NOT NULL,
                    zone_type         TEXT NOT NULL,
                    enabled_away      INTEGER DEFAULT 1,
                    enabled_home      INTEGER DEFAULT 1,
                    bypassed          INTEGER DEFAULT 0,
                    bypass_until      TIMESTAMP,
                    last_state_change TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_lock_slots (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL UNIQUE,
                    slot_number INTEGER NOT NULL,
                    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_synced TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES alarm_users(id) ON DELETE CASCADE
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_lock_access (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id           INTEGER NOT NULL,
                    lock_entity_id    TEXT NOT NULL,
                    enabled           INTEGER DEFAULT 0,
                    last_synced       TIMESTAMP,
                    last_sync_success INTEGER DEFAULT 1,
                    last_sync_error   TEXT,
                    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, lock_entity_id),
                    FOREIGN KEY (user_id) REFERENCES alarm_users(id) ON DELETE CASCADE
                )
            """)

            # Indexes
            for ddl in [
                f"CREATE INDEX IF NOT EXISTS idx_events_ts ON {TABLE_EVENTS}(timestamp DESC)",
                f"CREATE INDEX IF NOT EXISTS idx_failed_ts ON {TABLE_FAILED_ATTEMPTS}(timestamp DESC)",
                "CREATE INDEX IF NOT EXISTS idx_ula_user ON user_lock_access(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_ula_lock ON user_lock_access(lock_entity_id)",
            ]:
                cur.execute(ddl)

            # Seed config row
            cur.execute(f"SELECT COUNT(*) FROM {TABLE_CONFIG}")
            if cur.fetchone()[0] == 0:
                cur.execute(f"INSERT INTO {TABLE_CONFIG} (id) VALUES (1)")

            # ── schema migrations: add new columns to existing databases ──
            existing_cols = {
                row[1] for row in cur.execute(f"PRAGMA table_info({TABLE_CONFIG})")
            }
            migrations = [
                ("max_failed_attempts", "INTEGER DEFAULT 5"),
                ("lockout_duration",    "INTEGER DEFAULT 300"),
                ("alarm_auto_action",   "TEXT    DEFAULT 'none'"),
                ("require_pin_to_arm",  "INTEGER DEFAULT 0"),
                ("log_retention_days",  "INTEGER DEFAULT 90"),
            ]
            for col, col_def in migrations:
                if col not in existing_cols:
                    cur.execute(
                        f"ALTER TABLE {TABLE_CONFIG} ADD COLUMN {col} {col_def}"
                    )
                    _LOGGER.info("Schema migration: added column %s to %s", col, TABLE_CONFIG)

            conn.commit()
        _LOGGER.info("Database initialised at %s", self.db_path)

    # ------------------------------------------------------------------ #
    #  PIN helpers                                                         #
    # ------------------------------------------------------------------ #

    def hash_pin(self, pin: str) -> str:
        return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()

    def verify_pin(self, pin: str, pin_hash: str) -> bool:
        try:
            return bcrypt.checkpw(pin.encode(), pin_hash.encode())
        except Exception as exc:
            _LOGGER.error("verify_pin error: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    #  Users                                                               #
    # ------------------------------------------------------------------ #

    def add_user(
        self,
        name: str,
        pin: str,
        is_admin: bool = False,
        is_duress: bool = False,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        has_separate_lock_pin: bool = False,
        lock_pin: Optional[str] = None,
    ) -> Optional[int]:
        with self._conn() as conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    f"""
                    INSERT INTO {TABLE_USERS}
                    (name, pin_hash, is_admin, is_duress, phone, email,
                     has_separate_lock_pin, lock_pin_hash)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        name,
                        self.hash_pin(pin),
                        int(is_admin),
                        int(is_duress),
                        phone,
                        email,
                        int(has_separate_lock_pin),
                        self.hash_pin(lock_pin) if lock_pin else None,
                    ),
                )
                conn.commit()
                uid = cur.lastrowid
                self.log_event("user_added", user_id=uid, user_name=name)
                return uid
            except Exception as exc:
                _LOGGER.error("add_user error: %s", exc)
                return None

    def authenticate_user(
        self, pin: str, code: Optional[str] = None
    ) -> Optional[Dict]:
        """Authenticate by PIN — keypad / user-facing only."""
        cfg = self.get_config()
        max_attempts   = int(cfg.get("max_failed_attempts", MAX_FAILED_ATTEMPTS))
        lockout_secs   = int(cfg.get("lockout_duration",    LOCKOUT_DURATION))
        if self.is_locked_out(max_attempts, lockout_secs):
            _LOGGER.warning("System locked out due to too many failed attempts")
            return None
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT id,name,pin_hash,is_admin,is_duress FROM {TABLE_USERS} WHERE enabled=1"
            )
            for row in cur.fetchall():
                if self.verify_pin(pin, row["pin_hash"]):
                    cur.execute(
                        f"UPDATE {TABLE_USERS} SET last_used=CURRENT_TIMESTAMP, use_count=use_count+1 WHERE id=?",
                        (row["id"],),
                    )
                    conn.commit()
                    return {
                        "id": row["id"],
                        "name": row["name"],
                        "is_admin": bool(row["is_admin"]),
                        "is_duress": bool(row["is_duress"]),
                    }
            self.log_failed_attempt(code)
            return None

    def authenticate_user_service(
        self, pin: str, service_pin: str
    ) -> Optional[Dict]:
        """Authenticate for service / API calls (accepts service PIN or admin PIN).
        Uses hmac.compare_digest for the service PIN check to prevent timing attacks (H1).
        """
        import hmac
        if service_pin and hmac.compare_digest(pin, service_pin):
            return {"id": -1, "name": "Service", "is_admin": True, "is_duress": False}
        user = self.authenticate_user(pin)
        return user if (user and user.get("is_admin")) else None

    def get_users(self) -> List[Dict]:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT u.id, u.name, u.is_admin, u.is_duress, u.enabled,
                       u.phone, u.email, u.has_separate_lock_pin,
                       u.created_at, u.last_used, u.use_count, s.slot_number
                FROM {TABLE_USERS} u
                LEFT JOIN user_lock_slots s ON u.id = s.user_id
                ORDER BY u.name
                """
            )
            return [dict(r) for r in cur.fetchall()]

    def remove_user(self, user_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT is_admin, name FROM {TABLE_USERS} WHERE id=?", (user_id,)
            )
            user = cur.fetchone()
            if not user:
                return False
            if user["is_admin"]:
                cur.execute(
                    f"SELECT COUNT(*) FROM {TABLE_USERS} WHERE is_admin=1 AND enabled=1 AND id!=?",
                    (user_id,),
                )
                if cur.fetchone()[0] == 0:
                    _LOGGER.error("Cannot delete the last admin user")
                    return False
            cur.execute(f"DELETE FROM {TABLE_USERS} WHERE id=?", (user_id,))
            conn.commit()
            self.log_event("user_deleted", user_id=user_id, user_name=user["name"])
            return True

    def update_user(
        self,
        user_id: int,
        name: Optional[str] = None,
        pin: Optional[str] = None,
        is_admin: Optional[bool] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        has_separate_lock_pin: Optional[bool] = None,
        lock_pin: Optional[str] = None,
    ) -> bool:
        updates, values = [], []
        if name is not None:
            updates.append("name=?"); values.append(name)
        if pin is not None:
            updates.append("pin_hash=?"); values.append(self.hash_pin(pin))
        if is_admin is not None:
            updates.append("is_admin=?"); values.append(int(is_admin))
        if phone is not None:
            updates.append("phone=?"); values.append(phone)
        if email is not None:
            updates.append("email=?"); values.append(email)
        if has_separate_lock_pin is not None:
            updates.append("has_separate_lock_pin=?"); values.append(int(has_separate_lock_pin))
        if lock_pin is not None:
            updates.append("lock_pin_hash=?"); values.append(self.hash_pin(lock_pin))
        if not updates:
            return False
        values.append(user_id)
        with self._conn() as conn:
            try:
                conn.execute(
                    f"UPDATE {TABLE_USERS} SET {', '.join(updates)} WHERE id=?",
                    values,
                )
                conn.commit()
                self.log_event("user_updated", user_id=user_id)
                return True
            except Exception as exc:
                _LOGGER.error("update_user error: %s", exc)
                return False

    def set_user_enabled(self, user_id: int, enabled: bool) -> bool:
        with self._conn() as conn:
            try:
                conn.execute(
                    f"UPDATE {TABLE_USERS} SET enabled=? WHERE id=?",
                    (int(enabled), user_id),
                )
                conn.commit()
                return True
            except Exception as exc:
                _LOGGER.error("set_user_enabled error: %s", exc)
                return False

    # ------------------------------------------------------------------ #
    #  Configuration                                                       #
    # ------------------------------------------------------------------ #

    def get_config(self) -> Dict[str, Any]:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM {TABLE_CONFIG} WHERE id=1")
            row = cur.fetchone()
            return dict(row) if row else {}

    def update_config(self, updates: Dict[str, Any]) -> bool:
        if not updates:
            return False

        # Allowlist: reject any key not in the known set (C3 — prevents SQL injection)
        invalid_keys = set(updates) - VALID_CONFIG_KEYS
        if invalid_keys:
            _LOGGER.error("update_config: rejected unknown keys: %s", invalid_keys)
            return False

        # Bounds validation (M5 — prevents nonsensical values)
        for key, (lo, hi) in CONFIG_BOUNDS.items():
            if key in updates:
                val = updates[key]
                if not isinstance(val, int) or not (lo <= val <= hi):
                    _LOGGER.error(
                        "update_config: %s=%r out of bounds [%d, %d]", key, val, lo, hi
                    )
                    return False

        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values())
        with self._conn() as conn:
            try:
                conn.execute(
                    f"UPDATE {TABLE_CONFIG} SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=1",
                    values,
                )
                conn.commit()
                self.log_event("config_updated", details=json.dumps(updates))
                return True
            except Exception as exc:
                _LOGGER.error("update_config error: %s", exc)
                return False

    def get_lock_sync_config(self) -> int:
        return self.get_config().get("lock_sync_interval", 3600)

    # ------------------------------------------------------------------ #
    #  Events / audit log                                                  #
    # ------------------------------------------------------------------ #

    def log_event(
        self,
        event_type: str,
        user_id: Optional[int] = None,
        user_name: Optional[str] = None,
        state_from: Optional[str] = None,
        state_to: Optional[str] = None,
        zone_entity_id: Optional[str] = None,
        details: Optional[str] = None,
        is_duress: bool = False,
    ) -> None:
        with self._conn() as conn:
            try:
                conn.execute(
                    f"""
                    INSERT INTO {TABLE_EVENTS}
                    (event_type,user_id,user_name,state_from,state_to,
                     zone_entity_id,details,is_duress)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (event_type, user_id, user_name, state_from, state_to,
                     zone_entity_id, details, int(is_duress)),
                )
                conn.commit()
                # Prune old events to prevent unbounded table growth (M1)
                self._prune_events(conn)
            except Exception as exc:
                _LOGGER.error("log_event error: %s", exc)

    def _prune_events(self, conn: sqlite3.Connection) -> None:
        """Keep only the most recent MAX_EVENTS rows and respect log_retention_days."""
        try:
            cfg = self.get_config()
            retention_days = int(cfg.get("log_retention_days", 90))
            cutoff = datetime.now() - timedelta(days=retention_days)
            # Delete by age first
            conn.execute(
                f"DELETE FROM {TABLE_EVENTS} WHERE timestamp < ?",
                (cutoff.isoformat(),),
            )
            # Then cap absolute count
            conn.execute(
                f"DELETE FROM {TABLE_EVENTS} WHERE id NOT IN "
                f"(SELECT id FROM {TABLE_EVENTS} ORDER BY timestamp DESC LIMIT ?)",
                (MAX_EVENTS,),
            )
            conn.commit()
        except Exception as exc:
            _LOGGER.debug("_prune_events error (non-fatal): %s", exc)

    def log_failed_attempt(self, user_code: Optional[str] = None) -> None:
        # H3: never store the actual PIN — store only a masked hint (e.g. "1****")
        # so the log is useful for diagnosing keypad errors without leaking near-correct PINs.
        hint: Optional[str] = None
        if user_code:
            hint = user_code[0] + "*" * (len(user_code) - 1) if len(user_code) > 1 else "*"
        with self._conn() as conn:
            try:
                conn.execute(
                    f"INSERT INTO {TABLE_FAILED_ATTEMPTS} (user_code,attempt_type) VALUES (?,'pin_auth')",
                    (hint,),
                )
                conn.commit()
            except Exception as exc:
                _LOGGER.error("log_failed_attempt error: %s", exc)

    def is_locked_out(
        self,
        max_attempts: int = MAX_FAILED_ATTEMPTS,
        lockout_secs: int = LOCKOUT_DURATION,
    ) -> bool:
        cutoff = datetime.now() - timedelta(seconds=lockout_secs)
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT COUNT(*) FROM {TABLE_FAILED_ATTEMPTS} WHERE timestamp > ?",
                (cutoff,),
            )
            return cur.fetchone()[0] >= max_attempts

    def get_failed_attempts_count(
        self,
        lockout_secs: int = LOCKOUT_DURATION,
    ) -> int:
        cutoff = datetime.now() - timedelta(seconds=lockout_secs)
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT COUNT(*) FROM {TABLE_FAILED_ATTEMPTS} WHERE timestamp > ?",
                (cutoff,),
            )
            return cur.fetchone()[0]

    def clear_failed_attempts(self) -> None:
        with self._conn() as conn:
            conn.execute(f"DELETE FROM {TABLE_FAILED_ATTEMPTS}")
            conn.commit()

    def get_recent_events(self, limit: int = 100) -> List[Dict]:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT * FROM {TABLE_EVENTS} ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_events_filtered(
        self,
        event_types: Optional[List[str]] = None,
        entity_id: Optional[str] = None,
        user_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict]:
        query = f"SELECT * FROM {TABLE_EVENTS} WHERE 1=1"
        params: List[Any] = []
        if event_types:
            query += f" AND event_type IN ({','.join('?'*len(event_types))})"
            params.extend(event_types)
        if entity_id:
            query += " AND zone_entity_id=?"
            params.append(entity_id)
        if user_id:
            query += " AND user_id=?"
            params.append(user_id)
        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date.isoformat())
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = []
            for r in cur.fetchall():
                row = dict(r)
                if row.get("details"):
                    try:
                        row["details"] = json.loads(row["details"])
                    except Exception:
                        pass
                rows.append(row)
            return rows

    def get_event_types(self) -> List[str]:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT DISTINCT event_type FROM {TABLE_EVENTS} ORDER BY event_type"
            )
            return [r["event_type"] for r in cur.fetchall()]

    def get_event_stats(self, days: int = 7) -> Dict[str, Any]:
        cutoff = datetime.now() - timedelta(days=days)
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT event_type, COUNT(*) AS c FROM {TABLE_EVENTS} WHERE timestamp>? GROUP BY event_type ORDER BY c DESC",
                (cutoff.isoformat(),),
            )
            by_type = {r["event_type"]: r["c"] for r in cur.fetchall()}
            cur.execute(
                f"SELECT user_name, COUNT(*) AS c FROM {TABLE_EVENTS} WHERE timestamp>? AND user_name IS NOT NULL GROUP BY user_name ORDER BY c DESC",
                (cutoff.isoformat(),),
            )
            by_user = {r["user_name"]: r["c"] for r in cur.fetchall()}
            cur.execute(
                f"SELECT COUNT(*) FROM {TABLE_EVENTS} WHERE timestamp>?",
                (cutoff.isoformat(),),
            )
            total = cur.fetchone()[0]
        return {"total_events": total, "by_type": by_type, "by_user": by_user, "period_days": days}

    # ------------------------------------------------------------------ #
    #  Zones                                                               #
    # ------------------------------------------------------------------ #

    def add_zone(
        self,
        entity_id: str,
        zone_name: str,
        zone_type: str,
        enabled_away: bool = True,
        enabled_home: bool = True,
    ) -> bool:
        with self._conn() as conn:
            try:
                conn.execute(
                    f"""
                    INSERT OR REPLACE INTO {TABLE_ZONES}
                    (entity_id,zone_name,zone_type,enabled_away,enabled_home,last_state_change)
                    VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)
                    """,
                    (entity_id, zone_name, zone_type, int(enabled_away), int(enabled_home)),
                )
                conn.commit()
                return True
            except Exception as exc:
                _LOGGER.error("add_zone error: %s", exc)
                return False

    def get_zones(self, mode: Optional[str] = None) -> List[Dict]:
        query = f"SELECT * FROM {TABLE_ZONES}"
        if mode == "armed_away":
            query += " WHERE enabled_away=1"
        elif mode == "armed_home":
            query += " WHERE enabled_home=1"
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(query)
            return [dict(r) for r in cur.fetchall()]

    def set_zone_bypass(
        self,
        entity_id: str,
        bypassed: bool,
        bypass_duration: Optional[int] = None,
    ) -> bool:
        bypass_until = None
        if bypassed and bypass_duration:
            bypass_until = datetime.now() + timedelta(seconds=bypass_duration)
        with self._conn() as conn:
            try:
                conn.execute(
                    f"UPDATE {TABLE_ZONES} SET bypassed=?, bypass_until=? WHERE entity_id=?",
                    (int(bypassed), bypass_until, entity_id),
                )
                conn.commit()
                self.log_event("zone_bypass", zone_entity_id=entity_id,
                               details=f"Bypassed:{bypassed}")
                return True
            except Exception as exc:
                _LOGGER.error("set_zone_bypass error: %s", exc)
                return False

    # ------------------------------------------------------------------ #
    #  Lock slots / access                                                 #
    # ------------------------------------------------------------------ #

    def assign_lock_slot(self, user_id: int, slot_number: int) -> bool:
        with self._conn() as conn:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO user_lock_slots (user_id,slot_number,last_synced) VALUES (?,?,CURRENT_TIMESTAMP)",
                    (user_id, slot_number),
                )
                conn.commit()
                return True
            except Exception as exc:
                _LOGGER.error("assign_lock_slot error: %s", exc)
                return False

    def get_user_lock_slot(self, user_id: int) -> Optional[int]:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT slot_number FROM user_lock_slots WHERE user_id=?", (user_id,)
            )
            row = cur.fetchone()
            return row["slot_number"] if row else None

    def get_assigned_slots(self) -> List[int]:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT slot_number FROM user_lock_slots")
            return [r["slot_number"] for r in cur.fetchall()]

    def remove_lock_slot(self, user_id: int) -> bool:
        with self._conn() as conn:
            try:
                conn.execute("DELETE FROM user_lock_slots WHERE user_id=?", (user_id,))
                conn.commit()
                return True
            except Exception as exc:
                _LOGGER.error("remove_lock_slot error: %s", exc)
                return False

    def get_user_lock_access(self, user_id: int) -> Dict[str, Dict]:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT lock_entity_id,enabled,last_synced,last_sync_success,last_sync_error FROM user_lock_access WHERE user_id=?",
                (user_id,),
            )
            return {
                r["lock_entity_id"]: {
                    "enabled": bool(r["enabled"]),
                    "last_synced": r["last_synced"],
                    "last_sync_success": bool(r["last_sync_success"]),
                    "last_sync_error": r["last_sync_error"],
                }
                for r in cur.fetchall()
            }

    def set_user_lock_access(self, user_id: int, lock_entity_id: str, enabled: bool) -> bool:
        with self._conn() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO user_lock_access (user_id,lock_entity_id,enabled,updated_at)
                    VALUES (?,?,?,CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id,lock_entity_id)
                    DO UPDATE SET enabled=excluded.enabled, updated_at=CURRENT_TIMESTAMP
                    """,
                    (user_id, lock_entity_id, int(enabled)),
                )
                conn.commit()
                return True
            except Exception as exc:
                _LOGGER.error("set_user_lock_access error: %s", exc)
                return False

    def update_lock_sync_status(
        self,
        user_id: int,
        lock_entity_id: str,
        success: bool,
        error_msg: Optional[str] = None,
    ) -> bool:
        with self._conn() as conn:
            try:
                conn.execute(
                    """
                    UPDATE user_lock_access
                    SET last_synced=CURRENT_TIMESTAMP, last_sync_success=?, last_sync_error=?
                    WHERE user_id=? AND lock_entity_id=?
                    """,
                    (int(success), error_msg, user_id, lock_entity_id),
                )
                conn.commit()
                return True
            except Exception as exc:
                _LOGGER.error("update_lock_sync_status error: %s", exc)
                return False

    def initialize_user_lock_access(self, user_id: int, lock_entity_ids: List[str]) -> bool:
        with self._conn() as conn:
            try:
                for eid in lock_entity_ids:
                    conn.execute(
                        """
                        INSERT INTO user_lock_access
                        (user_id,lock_entity_id,enabled,last_synced,last_sync_success)
                        VALUES (?,?,1,CURRENT_TIMESTAMP,1)
                        ON CONFLICT(user_id,lock_entity_id)
                        DO UPDATE SET enabled=1, last_synced=CURRENT_TIMESTAMP,
                                      last_sync_success=1, last_sync_error=NULL
                        """,
                        (user_id, eid),
                    )
                conn.commit()
                return True
            except Exception as exc:
                _LOGGER.error("initialize_user_lock_access error: %s", exc)
                return False

    def get_all_user_lock_access(self) -> List[Dict]:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT ula.*, u.name AS user_name, u.enabled AS user_enabled, uls.slot_number
                FROM user_lock_access ula
                JOIN alarm_users u ON ula.user_id = u.id
                LEFT JOIN user_lock_slots uls ON ula.user_id = uls.user_id
                WHERE u.enabled = 1
                """
            )
            return [dict(r) for r in cur.fetchall()]
