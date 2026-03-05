#!/usr/bin/env python3
"""
HomeSecure Log Aggregation Service
Aggregates logs from the integration and makes them queryable in HA
"""
import asyncio
import logging
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/homesecure/homesecure.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('homesecure.log_service')

class LogAggregator:
    """Aggregates and stores logs from HomeSecure integration."""
    
    def __init__(self, db_path: str = "/data/homesecure_logs.db"):
        self.db_path = db_path
        self.init_database()
        
    def init_database(self):
        """Initialize log database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                level TEXT NOT NULL,
                component TEXT NOT NULL,
                message TEXT NOT NULL,
                details TEXT
            )
        ''')
        
        # Create index for faster queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_logs_timestamp 
            ON logs(timestamp DESC)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_logs_component 
            ON logs(component)
        ''')
        
        conn.commit()
        conn.close()
        
        logger.info(f"Log database initialized at {self.db_path}")
    
    def add_log(self, level: str, component: str, message: str, 
                details: Optional[Dict] = None):
        """Add a log entry."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO logs (level, component, message, details)
                VALUES (?, ?, ?, ?)
            ''', (level, component, message, 
                  json.dumps(details) if details else None))
            
            conn.commit()
        except Exception as e:
            logger.error(f"Error adding log entry: {e}")
        finally:
            conn.close()
    
    def get_logs(self, component: Optional[str] = None, 
                 level: Optional[str] = None,
                 since: Optional[str] = None,
                 limit: int = 100) -> List[Dict]:
        """Query logs."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM logs WHERE 1=1"
        params = []
        
        if component:
            query += " AND component = ?"
            params.append(component)
        
        if level:
            query += " AND level = ?"
            params.append(level)
        
        if since:
            query += " AND timestamp > ?"
            params.append(since)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        try:
            cursor.execute(query, params)
            logs = [dict(row) for row in cursor.fetchall()]
            return logs
        except Exception as e:
            logger.error(f"Error querying logs: {e}")
            return []
        finally:
            conn.close()
    
    def cleanup_old_logs(self, days: int = 30):
        """Delete logs older than specified days."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
            cursor.execute('''
                DELETE FROM logs 
                WHERE timestamp < datetime(?, 'unixepoch')
            ''', (cutoff,))
            
            deleted = cursor.rowcount
            conn.commit()
            logger.info(f"Cleaned up {deleted} old log entries")
        except Exception as e:
            logger.error(f"Error cleaning up logs: {e}")
        finally:
            conn.close()


class HomeAssistantLogMonitor:
    """Monitors Home Assistant logs for HomeSecure entries."""
    
    def __init__(self, aggregator: LogAggregator):
        self.aggregator = aggregator
        self.log_file = Path("/config/home-assistant.log")
        self.last_position = 0
        
    async def monitor(self):
        """Monitor HA log file for HomeSecure entries."""
        logger.info("Starting Home Assistant log monitor...")
        
        # Get initial file position
        if self.log_file.exists():
            self.last_position = self.log_file.stat().st_size
        
        while True:
            try:
                await self.check_for_new_logs()
                await asyncio.sleep(1)  # Check every second
            except Exception as e:
                logger.error(f"Error monitoring logs: {e}")
                await asyncio.sleep(5)
    
    async def check_for_new_logs(self):
        """Check for new log entries."""
        if not self.log_file.exists():
            return
        
        current_size = self.log_file.stat().st_size
        
        # File was truncated
        if current_size < self.last_position:
            self.last_position = 0
        
        # No new data
        if current_size == self.last_position:
            return
        
        # Read new log entries
        with open(self.log_file, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(self.last_position)
            new_lines = f.readlines()
            self.last_position = f.tell()
        
        # Process HomeSecure log entries
        for line in new_lines:
            if 'homesecure' in line.lower():
                self.process_log_line(line)
    
    def process_log_line(self, line: str):
        """Process a HomeSecure log line."""
        try:
            # Parse log line
            # Format: YYYY-MM-DD HH:MM:SS LEVEL [component] message
            parts = line.strip().split(' ', 4)
            if len(parts) < 5:
                return
            
            timestamp = f"{parts[0]} {parts[1]}"
            level = parts[2]
            component_part = parts[3]
            message = parts[4] if len(parts) > 4 else ""
            
            # Extract component from [custom_components.homesecure.xxx]
            component = "homesecure"
            if '[' in component_part and ']' in component_part:
                component_full = component_part.strip('[]')
                if 'homesecure' in component_full:
                    component = component_full.split('.')[-1]
            
            # Store in database
            self.aggregator.add_log(
                level=level,
                component=component,
                message=message
            )
            
        except Exception as e:
            logger.error(f"Error processing log line: {e}")


async def main():
    """Main log service loop."""
    logger.info("Starting HomeSecure Log Aggregation Service...")
    
    aggregator = LogAggregator()
    monitor = HomeAssistantLogMonitor(aggregator)
    
    # Cleanup old logs daily
    async def cleanup_task():
        while True:
            await asyncio.sleep(24 * 60 * 60)  # Once per day
            aggregator.cleanup_old_logs(days=30)
    
    # Run monitor and cleanup concurrently
    await asyncio.gather(
        monitor.monitor(),
        cleanup_task()
    )


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Log service stopped")