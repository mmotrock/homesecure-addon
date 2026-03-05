"""Database management for HomeSecure."""
import sqlite3
import logging
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import bcrypt

from .const import (
    TABLE_USERS,
    TABLE_CONFIG,
    TABLE_EVENTS,
    TABLE_FAILED_ATTEMPTS,
    TABLE_ZONES,
    DEFAULT_ENTRY_DELAY,
    DEFAULT_EXIT_DELAY,
    DEFAULT_ALARM_DURATION,
    MAX_FAILED_ATTEMPTS,
    LOCKOUT_DURATION,
)

_LOGGER = logging.getLogger(__name__)

class AlarmDatabase:
    """Database handler for alarm system."""
    
    def __init__(self, db_path: str):
        """Initialize the database."""
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self) -> None:
        """Initialize database tables."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Users table
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {TABLE_USERS} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                is_duress INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                phone TEXT,
                email TEXT,
                has_separate_lock_pin INTEGER DEFAULT 0,
                lock_pin_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP,
                use_count INTEGER DEFAULT 0
            )
        ''')
        
        # Configuration table
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {TABLE_CONFIG} (
                id INTEGER PRIMARY KEY DEFAULT 1,
                entry_delay INTEGER DEFAULT {DEFAULT_ENTRY_DELAY},
                exit_delay INTEGER DEFAULT {DEFAULT_EXIT_DELAY},
                alarm_duration INTEGER DEFAULT {DEFAULT_ALARM_DURATION},
                trigger_doors TEXT,
                notification_mobile INTEGER DEFAULT 1,
                notification_sms INTEGER DEFAULT 0,
                sms_numbers TEXT,
                lock_delay_home INTEGER DEFAULT 0,
                lock_delay_away INTEGER DEFAULT 60,
                close_delay_home INTEGER DEFAULT 0,
                close_delay_away INTEGER DEFAULT 60,
                auto_lock_on_arm_home INTEGER DEFAULT 0,
                auto_lock_on_arm_away INTEGER DEFAULT 1,
                auto_close_on_arm_home INTEGER DEFAULT 0,
                auto_close_on_arm_away INTEGER DEFAULT 1,
                lock_entities TEXT,
                garage_entities TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Events/audit log table
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {TABLE_EVENTS} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                user_id INTEGER,
                user_name TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                state_from TEXT,
                state_to TEXT,
                zone_entity_id TEXT,
                details TEXT,
                is_duress INTEGER DEFAULT 0
            )
        ''')
        
        # Failed attempts table
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {TABLE_FAILED_ATTEMPTS} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address TEXT,
                user_code TEXT,
                attempt_type TEXT
            )
        ''')
        
        # Zones table
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {TABLE_ZONES} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT UNIQUE NOT NULL,
                zone_name TEXT NOT NULL,
                zone_type TEXT NOT NULL,
                enabled_away INTEGER DEFAULT 1,
                enabled_home INTEGER DEFAULT 1,
                bypassed INTEGER DEFAULT 0,
                bypass_until TIMESTAMP,
                last_state_change TIMESTAMP
            )
        ''')

        # User lock slot assignments - tracks which Z-Wave slot each user is in
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_lock_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                slot_number INTEGER NOT NULL,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_synced TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES alarm_users(id) ON DELETE CASCADE
            )
        ''')

        # User lock slot assignments - tracks which Z-Wave slot each user is in
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_lock_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                slot_number INTEGER NOT NULL,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_synced TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES alarm_users(id) ON DELETE CASCADE
            )
        ''')
        
        # NEW: User lock access tracking - per-lock enable/disable with sync status
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_lock_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                lock_entity_id TEXT NOT NULL,
                enabled INTEGER DEFAULT 0,
                last_synced TIMESTAMP,
                last_sync_success INTEGER DEFAULT 1,
                last_sync_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, lock_entity_id),
                FOREIGN KEY (user_id) REFERENCES alarm_users(id) ON DELETE CASCADE
            )
        ''')
        
        # Create indexes
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_user_lock_access_user 
            ON user_lock_access(user_id)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_user_lock_access_lock 
            ON user_lock_access(lock_entity_id)
        ''')
        
        # Insert default config if not exists
        cursor.execute(f"SELECT COUNT(*) FROM {TABLE_CONFIG}")
        if cursor.fetchone()[0] == 0:
            cursor.execute(f'''
                INSERT INTO {TABLE_CONFIG} (id) VALUES (1)
            ''')
        
        # Create indexes
        cursor.execute(f'''
            CREATE INDEX IF NOT EXISTS idx_events_timestamp 
            ON {TABLE_EVENTS}(timestamp DESC)
        ''')
        
        cursor.execute(f'''
            CREATE INDEX IF NOT EXISTS idx_failed_attempts_timestamp 
            ON {TABLE_FAILED_ATTEMPTS}(timestamp DESC)
        ''')
        
        conn.commit()
        conn.close()
        
        _LOGGER.info("Database initialized successfully")
    
    def hash_pin(self, pin: str) -> str:
        """Hash a PIN using bcrypt."""
        return bcrypt.hashpw(pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def verify_pin(self, pin: str, pin_hash: str) -> bool:
        """Verify a PIN against its hash."""
        try:
            return bcrypt.checkpw(pin.encode('utf-8'), pin_hash.encode('utf-8'))
        except Exception as e:
            _LOGGER.error(f"Error verifying PIN: {e}")
            return False
    
    def add_user(self, name: str, pin: str, is_admin: bool = False, 
                is_duress: bool = False, phone: Optional[str] = None,
                email: Optional[str] = None, has_separate_lock_pin: bool = False,
                lock_pin: Optional[str] = None) -> Optional[int]:
        """Add a new user to the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            pin_hash = self.hash_pin(pin)
            lock_pin_hash = self.hash_pin(lock_pin) if lock_pin else None
            
            cursor.execute(f'''
                INSERT INTO {TABLE_USERS} 
                (name, pin_hash, is_admin, is_duress, phone, email, 
                has_separate_lock_pin, lock_pin_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, pin_hash, int(is_admin), int(is_duress), phone, email,
                int(has_separate_lock_pin), lock_pin_hash))
            
            user_id = cursor.lastrowid
            conn.commit()
            
            self.log_event("user_added", user_id=user_id, user_name=name)
            _LOGGER.info(f"User {name} added with ID {user_id}")
            
            return user_id
        except Exception as e:
            _LOGGER.error(f"Error adding user: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()
    
    def authenticate_user(self, pin: str, code: Optional[str] = None) -> Optional[Dict]:
        """Authenticate a user by PIN (for keypad use only)."""
        if self.is_locked_out():
            _LOGGER.warning("System is locked out due to failed attempts")
            return None
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                SELECT id, name, pin_hash, is_admin, is_duress, enabled
                FROM {TABLE_USERS}
                WHERE enabled = 1
            ''')
            
            users = cursor.fetchall()
            
            for user in users:
                if self.verify_pin(pin, user['pin_hash']):
                    # Update last used
                    cursor.execute(f'''
                        UPDATE {TABLE_USERS}
                        SET last_used = CURRENT_TIMESTAMP,
                            use_count = use_count + 1
                        WHERE id = ?
                    ''', (user['id'],))
                    conn.commit()
                    
                    return {
                        'id': user['id'],
                        'name': user['name'],
                        'is_admin': bool(user['is_admin']),
                        'is_duress': bool(user['is_duress']),
                    }
            
            # Failed authentication
            self.log_failed_attempt(code)
            return None
            
        except Exception as e:
            _LOGGER.error(f"Error authenticating user: {e}")
            return None
        finally:
            conn.close()
    
    def authenticate_user_service(self, pin: str, service_pin: str) -> Optional[Dict]:
        """
        Authenticate for service calls - accepts either user admin PIN or service PIN.
        Service PIN is the auto-generated secure PIN that bypasses user authentication.
        
        Args:
            pin: The PIN provided by the caller
            service_pin: The secure service PIN from config entry
            
        Returns:
            Dict with user info if authenticated, or a service authentication dict
        """
        # First check if it's the service PIN
        if pin == service_pin:
            _LOGGER.debug("Service PIN authenticated successfully")
            return {
                'id': -1,
                'name': 'Service',
                'is_admin': True,
                'is_duress': False,
            }
        
        # Otherwise authenticate as regular user (must be admin)
        user = self.authenticate_user(pin, None)
        
        # Only return if user is admin
        if user and user.get('is_admin'):
            return user
        
        return None
    
    def remove_user(self, user_id: int) -> bool:
        """Remove a user from the database (actually deletes the record)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # First check if this is the last admin
            cursor.execute(f'''
                SELECT COUNT(*) as admin_count
                FROM {TABLE_USERS}
                WHERE is_admin = 1 AND enabled = 1 AND id != ?
            ''', (user_id,))
            
            admin_count = cursor.fetchone()['admin_count']
            
            # Get the user being deleted to check if they're an admin
            cursor.execute(f'''
                SELECT is_admin, name FROM {TABLE_USERS}
                WHERE id = ?
            ''', (user_id,))
            
            user = cursor.fetchone()
            
            if not user:
                _LOGGER.error(f"User {user_id} not found")
                return False
            
            # Prevent deleting the last admin
            if user['is_admin'] and admin_count == 0:
                _LOGGER.error(f"Cannot delete the last admin user ({user['name']})")
                return False
            
            # Delete the user (this will cascade delete lock access due to foreign key)
            cursor.execute(f'''
                DELETE FROM {TABLE_USERS}
                WHERE id = ?
            ''', (user_id,))
            
            conn.commit()
            self.log_event("user_deleted", user_id=user_id, user_name=user['name'])
            _LOGGER.info(f"User {user['name']} (ID: {user_id}) permanently deleted")
            return True
        except Exception as e:
            _LOGGER.error(f"Error removing user: {e}")
            return False
        finally:
            conn.close()
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f"SELECT * FROM {TABLE_CONFIG} WHERE id = 1")
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return {}
        finally:
            conn.close()
    
    def update_config(self, updates: Dict[str, Any]) -> bool:
        """Update configuration."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values())
            
            cursor.execute(f'''
                UPDATE {TABLE_CONFIG}
                SET {set_clause}, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
            ''', values)
            
            conn.commit()
            self.log_event("config_updated", details=json.dumps(updates))
            return True
        except Exception as e:
            _LOGGER.error(f"Error updating config: {e}")
            return False
        finally:
            conn.close()
    
    def log_event(self, event_type: str, user_id: Optional[int] = None,
                  user_name: Optional[str] = None, state_from: Optional[str] = None,
                  state_to: Optional[str] = None, zone_entity_id: Optional[str] = None,
                  details: Optional[str] = None, is_duress: bool = False) -> None:
        """Log an event to the audit log."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                INSERT INTO {TABLE_EVENTS}
                (event_type, user_id, user_name, state_from, state_to, 
                 zone_entity_id, details, is_duress)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (event_type, user_id, user_name, state_from, state_to,
                  zone_entity_id, details, int(is_duress)))
            
            conn.commit()
        except Exception as e:
            _LOGGER.error(f"Error logging event: {e}")
        finally:
            conn.close()
    
    def log_failed_attempt(self, user_code: Optional[str] = None) -> None:
        """Log a failed authentication attempt."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                INSERT INTO {TABLE_FAILED_ATTEMPTS}
                (user_code, attempt_type)
                VALUES (?, 'pin_auth')
            ''', (user_code,))
            
            conn.commit()
        except Exception as e:
            _LOGGER.error(f"Error logging failed attempt: {e}")
        finally:
            conn.close()
    
    def is_locked_out(self) -> bool:
        """Check if system is locked out due to failed attempts."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            lockout_time = datetime.now() - timedelta(seconds=LOCKOUT_DURATION)
            
            cursor.execute(f'''
                SELECT COUNT(*) as count
                FROM {TABLE_FAILED_ATTEMPTS}
                WHERE timestamp > ?
            ''', (lockout_time,))
            
            count = cursor.fetchone()['count']
            return count >= MAX_FAILED_ATTEMPTS
        finally:
            conn.close()
    
    def get_failed_attempts_count(self) -> int:
        """Get recent failed attempts count."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            lockout_time = datetime.now() - timedelta(seconds=LOCKOUT_DURATION)
            
            cursor.execute(f'''
                SELECT COUNT(*) as count
                FROM {TABLE_FAILED_ATTEMPTS}
                WHERE timestamp > ?
            ''', (lockout_time,))
            
            return cursor.fetchone()['count']
        finally:
            conn.close()
    
    def clear_failed_attempts(self) -> None:
        """Clear failed attempts (called on successful auth)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f"DELETE FROM {TABLE_FAILED_ATTEMPTS}")
            conn.commit()
        finally:
            conn.close()
    
    def add_zone(self, entity_id: str, zone_name: str, zone_type: str,
                 enabled_away: bool = True, enabled_home: bool = True) -> bool:
        """Add or update a zone."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                INSERT OR REPLACE INTO {TABLE_ZONES}
                (entity_id, zone_name, zone_type, enabled_away, enabled_home, last_state_change)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (entity_id, zone_name, zone_type, int(enabled_away), int(enabled_home)))
            
            conn.commit()
            return True
        except Exception as e:
            _LOGGER.error(f"Error adding zone: {e}")
            return False
        finally:
            conn.close()
    
    def update_zone_state_change(self, entity_id: str) -> bool:
        """Update the last state change timestamp for a zone."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                UPDATE {TABLE_ZONES}
                SET last_state_change = CURRENT_TIMESTAMP
                WHERE entity_id = ?
            ''', (entity_id,))
            
            conn.commit()
            return True
        except Exception as e:
            _LOGGER.error(f"Error updating zone state change: {e}")
            return False
        finally:
            conn.close()
    
    def get_zones(self, mode: Optional[str] = None) -> List[Dict]:
        """Get all zones, optionally filtered by mode."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            query = f"SELECT * FROM {TABLE_ZONES}"
            
            if mode == "armed_away":
                query += " WHERE enabled_away = 1"
            elif mode == "armed_home":
                query += " WHERE enabled_home = 1"
            
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def set_zone_bypass(self, entity_id: str, bypassed: bool,
                        bypass_duration: Optional[int] = None) -> bool:
        """Set zone bypass status."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            bypass_until = None
            if bypassed and bypass_duration:
                bypass_until = datetime.now() + timedelta(seconds=bypass_duration)
            
            cursor.execute(f'''
                UPDATE {TABLE_ZONES}
                SET bypassed = ?, bypass_until = ?
                WHERE entity_id = ?
            ''', (int(bypassed), bypass_until, entity_id))
            
            conn.commit()
            self.log_event("zone_bypass", zone_entity_id=entity_id,
                          details=f"Bypassed: {bypassed}")
            return True
        except Exception as e:
            _LOGGER.error(f"Error setting zone bypass: {e}")
            return False
        finally:
            conn.close()
    
    def get_recent_events(self, limit: int = 100) -> List[Dict]:
        """Get recent events from audit log."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                SELECT * FROM {TABLE_EVENTS}
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_users(self) -> List[Dict]:
        """Get all users from database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                SELECT u.id, u.name, u.is_admin, u.is_duress, u.enabled, u.phone, u.email,
                    u.has_separate_lock_pin, u.created_at, u.last_used, u.use_count,
                    s.slot_number
                FROM {TABLE_USERS} u
                LEFT JOIN user_lock_slots s ON u.id = s.user_id
                ORDER BY u.name
            ''')
            
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def update_user(self, user_id: int, name: Optional[str] = None,
                pin: Optional[str] = None, is_admin: Optional[bool] = None,
                phone: Optional[str] = None, email: Optional[str] = None,
                has_separate_lock_pin: Optional[bool] = None,
                lock_pin: Optional[str] = None) -> bool:
        """Update user information."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            updates = []
            values = []
            
            if name is not None:
                updates.append("name = ?")
                values.append(name)
            
            if pin is not None:
                updates.append("pin_hash = ?")
                values.append(self.hash_pin(pin))
            
            if is_admin is not None:
                updates.append("is_admin = ?")
                values.append(int(is_admin))
            
            if phone is not None:
                updates.append("phone = ?")
                values.append(phone)
            
            if email is not None:
                updates.append("email = ?")
                values.append(email)
            
            if has_separate_lock_pin is not None:
                updates.append("has_separate_lock_pin = ?")
                values.append(int(has_separate_lock_pin))
            
            if lock_pin is not None:
                updates.append("lock_pin_hash = ?")
                values.append(self.hash_pin(lock_pin))
            
            if not updates:
                return False
            
            values.append(user_id)
            
            cursor.execute(f'''
                UPDATE {TABLE_USERS}
                SET {", ".join(updates)}
                WHERE id = ?
            ''', values)
            
            conn.commit()
            
            self.log_event("user_updated", user_id=user_id)
            return cursor.rowcount > 0
        except Exception as e:
            _LOGGER.error(f"Error updating user: {e}")
            return False
        finally:
            conn.close()

    def get_user_lock_pin(self, user_id: int) -> Optional[str]:
        """Get user's lock PIN hash if they have a separate one."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                SELECT lock_pin_hash, has_separate_lock_pin
                FROM {TABLE_USERS}
                WHERE id = ? AND enabled = 1
            ''', (user_id,))
            
            row = cursor.fetchone()
            if row and row['has_separate_lock_pin']:
                return row['lock_pin_hash']
            return None
        finally:
            conn.close()

    def authenticate_lock_pin(self, pin: str) -> Optional[Dict]:
        """Authenticate a user by their lock PIN."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                SELECT id, name, lock_pin_hash
                FROM {TABLE_USERS}
                WHERE enabled = 1 AND has_separate_lock_pin = 1
            ''')
            
            users = cursor.fetchall()
            
            for user in users:
                if user['lock_pin_hash'] and self.verify_pin(pin, user['lock_pin_hash']):
                    return {
                        'id': user['id'],
                        'name': user['name'],
                    }
            
            return None
        except Exception as e:
            _LOGGER.error(f"Error authenticating lock PIN: {e}")
            return None
        finally:
            conn.close()

    def set_user_lock_access(self, user_id: int, lock_entity_id: str, can_access: bool) -> bool:
        """Set whether a user can access a specific lock (deprecated - now all or nothing)."""
        # This is now a no-op since we don't do per-lock access
        # Keeping for backward compatibility
        return True
    
    # def get_user_lock_access(self, user_id: int) -> List[str]:
    #     """Get list of lock entity IDs the user can access (deprecated)."""
    #     # Now returns empty list - lock access is all or nothing
    #     return []

    def get_user_lock_access(self, user_id: int) -> Dict[str, Dict[str, Any]]:
        """
        Get lock access status for a user.
        
        Returns:
            Dict mapping lock_entity_id to access info:
            {
                'lock.front_door': {
                    'enabled': True,
                    'last_synced': '2024-01-15 10:30:00',
                    'last_sync_success': True,
                    'last_sync_error': None
                }
            }
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT lock_entity_id, enabled, last_synced, 
                       last_sync_success, last_sync_error
                FROM user_lock_access
                WHERE user_id = ?
            ''', (user_id,))
            
            result = {}
            for row in cursor.fetchall():
                result[row['lock_entity_id']] = {
                    'enabled': bool(row['enabled']),
                    'last_synced': row['last_synced'],
                    'last_sync_success': bool(row['last_sync_success']),
                    'last_sync_error': row['last_sync_error']
                }
            
            return result
        finally:
            conn.close()
    
    def set_user_lock_access(self, user_id: int, lock_entity_id: str, 
                            enabled: bool) -> bool:
        """
        Set lock access for a user (updates DB immediately).
        
        Args:
            user_id: User ID
            lock_entity_id: Lock entity ID
            enabled: True to enable, False to disable
            
        Returns:
            True if successful
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO user_lock_access 
                (user_id, lock_entity_id, enabled, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, lock_entity_id) 
                DO UPDATE SET 
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
            ''', (user_id, lock_entity_id, int(enabled)))
            
            conn.commit()
            return True
        except Exception as e:
            _LOGGER.error(f"Error setting lock access: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def update_lock_sync_status(self, user_id: int, lock_entity_id: str,
                                success: bool, error_msg: Optional[str] = None) -> bool:
        """
        Update the sync status for a user's lock access.
        
        Args:
            user_id: User ID
            lock_entity_id: Lock entity ID
            success: True if sync succeeded
            error_msg: Error message if failed
            
        Returns:
            True if successful
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE user_lock_access
                SET last_synced = CURRENT_TIMESTAMP,
                    last_sync_success = ?,
                    last_sync_error = ?
                WHERE user_id = ? AND lock_entity_id = ?
            ''', (int(success), error_msg, user_id, lock_entity_id))
            
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            _LOGGER.error(f"Error updating sync status: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def get_all_user_lock_access(self) -> List[Dict[str, Any]]:
        """
        Get all user lock access records (for periodic sync).
        
        Returns:
            List of dicts with user_id, lock_entity_id, enabled, etc.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT ula.*, u.name as user_name, u.enabled as user_enabled,
                       uls.slot_number
                FROM user_lock_access ula
                JOIN alarm_users u ON ula.user_id = u.id
                LEFT JOIN user_lock_slots uls ON ula.user_id = uls.user_id
                WHERE u.enabled = 1
            ''')
            
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def initialize_user_lock_access(self, user_id: int, lock_entity_ids: List[str]) -> bool:
        """
        Initialize lock access records for a new user (all enabled by default).
        Called after successfully syncing user to locks.
        
        Args:
            user_id: User ID
            lock_entity_ids: List of lock entity IDs that were synced
            
        Returns:
            True if successful
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            for lock_entity_id in lock_entity_ids:
                cursor.execute('''
                    INSERT INTO user_lock_access 
                    (user_id, lock_entity_id, enabled, last_synced, last_sync_success)
                    VALUES (?, ?, 1, CURRENT_TIMESTAMP, 1)
                    ON CONFLICT(user_id, lock_entity_id) 
                    DO UPDATE SET 
                        enabled = 1,
                        last_synced = CURRENT_TIMESTAMP,
                        last_sync_success = 1,
                        last_sync_error = NULL
                ''', (user_id, lock_entity_id))
            
            conn.commit()
            return True
        except Exception as e:
            _LOGGER.error(f"Error initializing lock access: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def clear_user_lock_access(self, user_id: int) -> bool:
        """
        Clear all lock access records for a user (called on user deletion).
        
        Args:
            user_id: User ID
            
        Returns:
            True if successful
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                DELETE FROM user_lock_access
                WHERE user_id = ?
            ''', (user_id,))
            
            conn.commit()
            return True
        except Exception as e:
            _LOGGER.error(f"Error clearing lock access: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def get_lock_sync_config(self) -> int:
        """
        Get the lock sync interval from config.
        
        Returns:
            Interval in seconds (default 3600 = 1 hour)
        """
        config = self.get_config()
        return config.get('lock_sync_interval', 3600)
    
    def set_lock_sync_config(self, interval: int) -> bool:
        """
        Set the lock sync interval.
        
        Args:
            interval: Interval in seconds
            
        Returns:
            True if successful
        """
        return self.update_config({'lock_sync_interval': interval})
    
    def assign_lock_slot(self, user_id: int, slot_number: int) -> bool:
        """Assign a lock slot to a user."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO user_lock_slots (user_id, slot_number, last_synced)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, slot_number))
            
            conn.commit()
            return True
        except Exception as e:
            _LOGGER.error(f"Error assigning lock slot: {e}")
            return False
        finally:
            conn.close()
    
    def get_user_lock_slot(self, user_id: int) -> Optional[int]:
        """Get the lock slot assigned to a user."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT slot_number FROM user_lock_slots
                WHERE user_id = ?
            ''', (user_id,))
            
            row = cursor.fetchone()
            return row['slot_number'] if row else None
        finally:
            conn.close()
    
    def get_assigned_slots(self) -> List[int]:
        """Get all currently assigned slot numbers."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT slot_number FROM user_lock_slots')
            return [row['slot_number'] for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def remove_lock_slot(self, user_id: int) -> bool:
        """Remove lock slot assignment for a user."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM user_lock_slots WHERE user_id = ?', (user_id,))
            conn.commit()
            return True
        except Exception as e:
            _LOGGER.error(f"Error removing lock slot: {e}")
            return False
        finally:
            conn.close()

    def log_entry_point_event(self, event_type: str, entity_id: str, 
                            entity_name: str, user_id: Optional[int] = None,
                            user_name: Optional[str] = None, 
                            details: Optional[Dict] = None) -> None:
        """
        Log entry point events (doors, locks, garages).
        
        Args:
            event_type: Type of event (door_locked, door_unlocked, garage_opened, etc.)
            entity_id: Entity ID that triggered the event
            entity_name: Friendly name of the entity
            user_id: User ID if known
            user_name: User name if known
            details: Additional event details
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                INSERT INTO {TABLE_EVENTS}
                (event_type, user_id, user_name, zone_entity_id, details)
                VALUES (?, ?, ?, ?, ?)
            ''', (event_type, user_id, user_name, entity_id, 
                json.dumps({
                    'entity_name': entity_name,
                    **(details or {})
                })))
            
            conn.commit()
        except Exception as e:
            _LOGGER.error(f"Error logging entry point event: {e}")
        finally:
            conn.close()

    def get_events_filtered(self, event_types: Optional[List[str]] = None,
                        entity_id: Optional[str] = None,
                        user_id: Optional[int] = None,
                        start_date: Optional[datetime] = None,
                        end_date: Optional[datetime] = None,
                        limit: int = 100) -> List[Dict]:
        """
        Get filtered events with pagination.
        
        Args:
            event_types: List of event types to filter by
            entity_id: Filter by specific entity
            user_id: Filter by specific user
            start_date: Filter events after this date
            end_date: Filter events before this date
            limit: Maximum number of events to return
            
        Returns:
            List of event dictionaries
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            query = f"SELECT * FROM {TABLE_EVENTS} WHERE 1=1"
            params = []
            
            if event_types:
                placeholders = ','.join(['?' for _ in event_types])
                query += f" AND event_type IN ({placeholders})"
                params.extend(event_types)
            
            if entity_id:
                query += " AND zone_entity_id = ?"
                params.append(entity_id)
            
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            
            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date.isoformat())
            
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date.isoformat())
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            
            events = []
            for row in cursor.fetchall():
                event = dict(row)
                # Parse details JSON if present
                if event.get('details'):
                    try:
                        event['details'] = json.loads(event['details'])
                    except:
                        pass
                events.append(event)
            
            return events
        finally:
            conn.close()

    def get_event_types(self) -> List[str]:
        """Get all unique event types in the database."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                SELECT DISTINCT event_type 
                FROM {TABLE_EVENTS}
                ORDER BY event_type
            ''')
            
            return [row['event_type'] for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_event_stats(self, days: int = 7) -> Dict[str, Any]:
        """
        Get event statistics for the last N days.
        
        Returns:
            Dict with event counts by type, by user, etc.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cutoff = datetime.now() - timedelta(days=days)
            
            # Events by type
            cursor.execute(f'''
                SELECT event_type, COUNT(*) as count
                FROM {TABLE_EVENTS}
                WHERE timestamp > ?
                GROUP BY event_type
                ORDER BY count DESC
            ''', (cutoff.isoformat(),))
            
            by_type = {row['event_type']: row['count'] for row in cursor.fetchall()}
            
            # Events by user
            cursor.execute(f'''
                SELECT user_name, COUNT(*) as count
                FROM {TABLE_EVENTS}
                WHERE timestamp > ? AND user_name IS NOT NULL
                GROUP BY user_name
                ORDER BY count DESC
            ''', (cutoff.isoformat(),))
            
            by_user = {row['user_name']: row['count'] for row in cursor.fetchall()}
            
            # Total events
            cursor.execute(f'''
                SELECT COUNT(*) as total
                FROM {TABLE_EVENTS}
                WHERE timestamp > ?
            ''', (cutoff.isoformat(),))
            
            total = cursor.fetchone()['total']
            
            return {
                'total_events': total,
                'by_type': by_type,
                'by_user': by_user,
                'period_days': days
            }
        finally:
            conn.close()