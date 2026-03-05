"""
Professional Monitoring Service Integration for HomeSecure
This template can be adapted for various monitoring services (ADT, SimpliSafe, Ring, etc.)

Place in: custom_components/homesecure/monitoring.py
"""
import logging
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
import aiohttp
import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

# Monitoring service protocols
PROTOCOL_CONTACT_ID = "contact_id"  # Industry standard (SIA)
PROTOCOL_ALARM_NET = "alarm_net"    # Honeywell/Ademco
PROTOCOL_SIA = "sia"                 # Security Industry Association
PROTOCOL_WEBHOOK = "webhook"         # Custom webhook

class MonitoringService:
    """Base class for professional monitoring service integration."""
    
    def __init__(self, hass: HomeAssistant, config: Dict[str, Any]):
        """Initialize monitoring service."""
        self.hass = hass
        self.config = config
        self.enabled = config.get('enabled', False)
        self.protocol = config.get('protocol', PROTOCOL_WEBHOOK)
        self.endpoint = config.get('endpoint')
        self.account_id = config.get('account_id')
        self.api_key = config.get('api_key')
        self.test_mode = config.get('test_mode', False)
        self._session = async_get_clientsession(hass)
    
    async def send_event(self, event_type: str, zone: Optional[str] = None, 
                        user: Optional[str] = None, details: Optional[Dict] = None) -> bool:
        """Send event to monitoring service."""
        if not self.enabled:
            _LOGGER.debug("Monitoring service not enabled")
            return False
        
        try:
            if self.protocol == PROTOCOL_CONTACT_ID:
                return await self._send_contact_id(event_type, zone, user, details)
            elif self.protocol == PROTOCOL_ALARM_NET:
                return await self._send_alarm_net(event_type, zone, user, details)
            elif self.protocol == PROTOCOL_SIA:
                return await self._send_sia(event_type, zone, user, details)
            elif self.protocol == PROTOCOL_WEBHOOK:
                return await self._send_webhook(event_type, zone, user, details)
            else:
                _LOGGER.error(f"Unknown protocol: {self.protocol}")
                return False
        except Exception as e:
            _LOGGER.error(f"Error sending event to monitoring service: {e}")
            return False
    
    async def _send_contact_id(self, event_type: str, zone: Optional[str], 
                               user: Optional[str], details: Optional[Dict]) -> bool:
        """Send event using Contact ID protocol (SIA DC-05)."""
        # Contact ID event codes
        event_codes = {
            'arm_away': '3401',      # Armed Away
            'arm_home': '3441',      # Armed Stay
            'disarm': '1401',        # Disarm by User
            'triggered': '1130',     # Burglary
            'entry_delay': '1134',   # Entry/Exit Delay
            'duress': '1121',        # Duress Alarm
            'fire': '1110',          # Fire Alarm
            'medical': '1100',       # Medical Alarm
            'panic': '1120',         # Panic Alarm
            'tamper': '1383',        # Sensor Tamper
            'low_battery': '1384',   # Low Battery
            'ac_loss': '1301',       # AC Power Loss
            'test': '1602',          # Periodic Test
        }
        
        code = event_codes.get(event_type, '1570')  # Default: Unknown event
        
        # Zone number (pad to 3 digits)
        zone_num = zone if zone else '000'
        if isinstance(zone_num, str) and not zone_num.isdigit():
            zone_num = '001'  # Default zone
        zone_num = str(zone_num).zfill(3)
        
        # User number (pad to 4 digits)
        user_num = user if user else '0000'
        if isinstance(user_num, str) and not user_num.isdigit():
            user_num = '0001'  # Default user
        user_num = str(user_num).zfill(4)
        
        # Build Contact ID message
        # Format: ACCT[4]MT[2]Q[1]XYZ[3]GG[2]CCC[3]S
        account = str(self.account_id).zfill(4)
        message_type = '18'  # Event
        qualifier = '1' if 'restore' in event_type else '1'  # 1=new, 3=restore
        event_code = code
        group_partition = '00'  # Partition/area
        zone_code = zone_num
        
        message = f"{account}{message_type}{qualifier}{event_code}{group_partition}{zone_code}"
        
        _LOGGER.info(f"Sending Contact ID: {message}")
        
        # Send via TCP/IP or HTTP depending on service
        if self.endpoint.startswith('http'):
            return await self._send_http_post({
                'protocol': 'contact_id',
                'message': message,
                'account': account,
                'event_type': event_type
            })
        else:
            return await self._send_tcp(message)
    
    async def _send_alarm_net(self, event_type: str, zone: Optional[str],
                             user: Optional[str], details: Optional[Dict]) -> bool:
        """Send event using AlarmNet protocol (Honeywell)."""
        # AlarmNet uses similar codes to Contact ID but with different format
        payload = {
            'account_id': self.account_id,
            'event_type': event_type,
            'zone': zone,
            'user': user,
            'timestamp': datetime.now().isoformat(),
            'details': details
        }
        
        return await self._send_http_post(payload)
    
    async def _send_sia(self, event_type: str, zone: Optional[str],
                       user: Optional[str], details: Optional[Dict]) -> bool:
        """Send event using SIA protocol (DC-09)."""
        # SIA event codes
        sia_codes = {
            'arm_away': 'CA',        # Closing (Away)
            'arm_home': 'CG',        # Closing (Stay)
            'disarm': 'OP',          # Opening
            'triggered': 'BA',       # Burglary Alarm
            'entry_delay': 'BE',     # Burglary Entry/Exit
            'duress': 'HA',          # Hold-up/Duress
            'fire': 'FA',            # Fire Alarm
            'panic': 'PA',           # Panic Alarm
            'test': 'RP',            # Automatic Test
        }
        
        code = sia_codes.get(event_type, 'BA')
        
        # SIA message format: "\nACCT"SEQ"TIME"CODE[zone]
        account = str(self.account_id).zfill(4)
        seq = '0001'  # Sequence number
        timestamp = datetime.now().strftime('%H:%M:%S')
        zone_str = f"[{zone}]" if zone else ""
        
        message = f'\n{account}"{seq}"{timestamp}"{code}{zone_str}'
        
        _LOGGER.info(f"Sending SIA: {message}")
        
        if self.endpoint.startswith('http'):
            return await self._send_http_post({
                'protocol': 'sia',
                'message': message,
                'account': account
            })
        else:
            return await self._send_tcp(message)
    
    async def _send_webhook(self, event_type: str, zone: Optional[str],
                           user: Optional[str], details: Optional[Dict]) -> bool:
        """Send event using custom webhook."""
        payload = {
            'account_id': self.account_id,
            'event_type': event_type,
            'zone': zone,
            'user': user,
            'timestamp': datetime.now().isoformat(),
            'test_mode': self.test_mode,
            'details': details or {}
        }
        
        return await self._send_http_post(payload)
    
    async def _send_http_post(self, payload: Dict[str, Any]) -> bool:
        """Send event via HTTP POST."""
        if not self.endpoint:
            _LOGGER.error("No endpoint configured")
            return False
        
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'HomeAssistant-SecureAlarm/1.0'
        }
        
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        
        try:
            async with self._session.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status in [200, 201, 202]:
                    _LOGGER.info(f"Successfully sent event to monitoring service")
                    return True
                else:
                    _LOGGER.error(f"Monitoring service returned status {response.status}")
                    text = await response.text()
                    _LOGGER.error(f"Response: {text}")
                    return False
        except aiohttp.ClientError as e:
            _LOGGER.error(f"HTTP error sending to monitoring service: {e}")
            return False
    
    async def _send_tcp(self, message: str) -> bool:
        """Send event via TCP socket."""
        try:
            host, port = self.endpoint.split(':')
            port = int(port)
            
            reader, writer = await asyncio.open_connection(host, port)
            
            writer.write(message.encode())
            await writer.drain()
            
            # Wait for acknowledgment
            data = await asyncio.wait_for(reader.read(100), timeout=5.0)
            
            writer.close()
            await writer.wait_closed()
            
            _LOGGER.info(f"Successfully sent event via TCP")
            return True
        except Exception as e:
            _LOGGER.error(f"TCP error sending to monitoring service: {e}")
            return False
    
    async def test_connection(self) -> bool:
        """Test connection to monitoring service."""
        return await self.send_event('test', zone='000', user='test', details={
            'test': True,
            'timestamp': datetime.now().isoformat()
        })
    
    async def heartbeat(self) -> bool:
        """Send periodic heartbeat/test signal."""
        return await self.send_event('test', details={'heartbeat': True})


class MonitoringCoordinator:
    """Coordinator for managing monitoring service integration."""
    
    def __init__(self, hass: HomeAssistant, database, monitoring_config: Dict[str, Any]):
        """Initialize monitoring coordinator."""
        self.hass = hass
        self.database = database
        self.monitoring = MonitoringService(hass, monitoring_config)
        self._heartbeat_task = None
        
        # Start heartbeat if enabled
        if monitoring_config.get('heartbeat_enabled', False):
            interval = monitoring_config.get('heartbeat_interval', 3600)  # 1 hour default
            self._heartbeat_task = hass.loop.create_task(
                self._heartbeat_loop(interval)
            )
    
    async def _heartbeat_loop(self, interval: int):
        """Periodic heartbeat loop."""
        while True:
            await asyncio.sleep(interval)
            await self.monitoring.heartbeat()
    
    async def handle_alarm_event(self, event_type: str, zone: Optional[str] = None,
                                 user: Optional[str] = None, details: Optional[Dict] = None) -> bool:
        """Handle alarm event and forward to monitoring service."""
        # Log to database first
        self.database.log_event(
            event_type=f"monitoring_{event_type}",
            zone_entity_id=zone,
            user_name=user,
            details=json.dumps(details) if details else None
        )
        
        # Send to monitoring service
        success = await self.monitoring.send_event(event_type, zone, user, details)
        
        if not success:
            _LOGGER.warning(f"Failed to send {event_type} to monitoring service")
            # Could implement retry logic here
        
        return success
    
    def stop(self):
        """Stop monitoring coordinator."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()


# Example configuration in configuration.yaml
"""
homesecure:
  monitoring:
    enabled: true
    protocol: contact_id  # or alarm_net, sia, webhook
    endpoint: "https://monitoring.example.com/api/events"
    # OR for TCP: "monitoring.example.com:5000"
    account_id: "1234"
    api_key: "your-api-key-here"
    test_mode: false
    heartbeat_enabled: true
    heartbeat_interval: 3600  # seconds
"""