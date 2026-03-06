"""
Lock Manager for HomeSecure
Manages Z-Wave JS lock user codes synced with security panel users
Uses zwave-js-server-python for direct Z-Wave JS Server communication

Place in: custom_components/homesecure/lock_manager.py
"""
import logging
from typing import Optional, Dict, List, Any
import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from zwave_js_server.client import Client as ZwaveClient
from zwave_js_server.model.node import Node as ZwaveNode
from zwave_js_server.model.value import Value as ZwaveValue
from zwave_js_server.const import CommandClass

_LOGGER = logging.getLogger(__name__)


class LockManager:
    """Manages lock codes for Z-Wave JS locks synced with alarm users."""
    
    def __init__(self, hass: HomeAssistant, database, coordinator, 
                 zwave_server_url: str = "ws://localhost:3000"):
        """Initialize lock manager."""
        self.hass = hass
        self.database = database
        self.coordinator = coordinator
        self._zwave_server_url = zwave_server_url
        self._zwave_client: Optional[ZwaveClient] = None
        self._owns_client = False  # Track if we created the client (vs borrowed from HA)
        self._managed_locks: List[str] = []
        self._lock_nodes: Dict[str, ZwaveNode] = {}
        self._sync_lock = asyncio.Lock()
        self._pin_cache: Dict[int, str] = {}
        
    async def async_setup(self) -> None:
        """Set up lock manager and connect to Z-Wave JS Server."""
        await self._connect_zwave_server()
        await self._discover_locks()
        _LOGGER.info(f"Lock manager initialized with {len(self._managed_locks)} locks")
    
    async def _connect_zwave_server(self) -> None:
        """Connect to Z-Wave JS Server using HA's existing client."""
        try:
            # Try to use Home Assistant's existing Z-Wave JS client
            if "zwave_js" in self.hass.data:
                _LOGGER.info("Z-Wave JS found in hass.data")
                _LOGGER.info(f"Available keys in zwave_js data: {list(self.hass.data['zwave_js'].keys())}")
                
                # Get all Z-Wave JS config entries
                zwave_entries = [
                    entry for entry in self.hass.config_entries.async_entries()
                    if entry.domain == "zwave_js"
                ]
                
                _LOGGER.info(f"Found {len(zwave_entries)} Z-Wave JS config entries")
                
                if zwave_entries:
                    for entry in zwave_entries:
                        _LOGGER.info(f"Checking entry: {entry.entry_id} - {entry.title}")
                        
                        # Try different possible keys where the client might be stored
                        entry_data = self.hass.data["zwave_js"].get(entry.entry_id)
                        
                        if entry_data:
                            _LOGGER.info(f"Entry data found, keys: {list(entry_data.keys())}")
                            
                            # Try to get client from various possible locations
                            client = entry_data.get("client")
                            if not client:
                                # Sometimes it's nested differently
                                client = entry_data.get("driver")
                            
                            if client:
                                self._zwave_client = client
                                self._owns_client = False
                                _LOGGER.info("✓ Using existing Z-Wave JS client from Home Assistant")
                                
                                # Check if driver is ready
                                if hasattr(self._zwave_client, 'driver') and self._zwave_client.driver:
                                    _LOGGER.info(f"✓ Driver ready, version: {self._zwave_client.version.driver_version}")
                                    return
                                else:
                                    _LOGGER.warning("Client found but driver not ready or accessible")
                                    # Continue to fallback
                            else:
                                _LOGGER.warning(f"No 'client' or 'driver' key in entry data")
                        else:
                            _LOGGER.warning(f"Entry {entry.entry_id} not found in zwave_js data")
            else:
                _LOGGER.info("'zwave_js' not in hass.data")
            
            # Fallback: Create our own connection
            _LOGGER.warning(f"Creating new Z-Wave JS connection to {self._zwave_server_url}")
            session = async_get_clientsession(self.hass)
            self._zwave_client = ZwaveClient(self._zwave_server_url, session)
            
            _LOGGER.info("Connecting to Z-Wave JS server...")
            await self._zwave_client.connect()
            self._owns_client = True
            
            _LOGGER.info(f"Connection established, server version: {self._zwave_client.version}")
            
            # Check if we can access the driver immediately
            if self._zwave_client.driver:
                _LOGGER.info("✓ Driver available immediately!")
                _LOGGER.info(f"✓ Driver version: {self._zwave_client.version.driver_version}")
                _LOGGER.info(f"✓ Controller has {len(self._zwave_client.driver.controller.nodes)} nodes")
                return
            
            # Wait for driver ready event
            _LOGGER.info("Driver not ready yet, waiting for driver ready event...")
            
            driver_ready = asyncio.Event()
            
            def on_driver_ready(event_data):
                _LOGGER.info("Driver ready event received!")
                driver_ready.set()
            
            # Listen for driver ready event using the correct API
            self._zwave_client.driver_events.on("driver ready", lambda: on_driver_ready(None))
            
            # Wait up to 30 seconds for driver ready event
            try:
                await asyncio.wait_for(driver_ready.wait(), timeout=30.0)
                _LOGGER.info("✓ Driver is ready!")
                _LOGGER.info(f"✓ Driver version: {self._zwave_client.version.driver_version}")
                _LOGGER.info(f"✓ Controller has {len(self._zwave_client.driver.controller.nodes)} nodes")
                return
            except asyncio.TimeoutError:
                _LOGGER.error("Timeout waiting for driver ready event")
            
            # Last resort: check driver state one more time
            if self._zwave_client.driver:
                _LOGGER.warning("Driver became available without event notification")
                _LOGGER.info(f"✓ Driver version: {self._zwave_client.version.driver_version}")
                _LOGGER.info(f"✓ Controller has {len(self._zwave_client.driver.controller.nodes)} nodes")
                return
            
            _LOGGER.error("Z-Wave JS driver not available after 30 seconds")
            _LOGGER.error("The Z-Wave JS server may still be starting up or having issues")
            _LOGGER.error("Lock features will not be available")
            self._zwave_client = None
            
        except Exception as e:
            _LOGGER.error(f"Failed to connect to Z-Wave JS Server: {e}", exc_info=True)
            _LOGGER.error("Lock management features will not be available")
            self._zwave_client = None
    
    async def async_shutdown(self) -> None:
        """Disconnect from Z-Wave JS Server."""
        # Only disconnect if we created the client ourselves
        if self._zwave_client and self._owns_client:
            await self._zwave_client.disconnect()
            _LOGGER.info("Disconnected from Z-Wave JS Server")
        elif self._zwave_client:
            _LOGGER.debug("Using shared Z-Wave JS client, not disconnecting")
    
    async def _discover_locks(self) -> None:
        """Discover Z-Wave JS locks (excludes garage doors)."""
        self._managed_locks = []
        self._lock_nodes = {}
        
        _LOGGER.warning("=== LOCK DISCOVERY DEBUG START ===")
        
        if not self._zwave_client:
            _LOGGER.error("Z-Wave client is None - cannot discover locks")
            _LOGGER.error("Lock features will not be available")
            return
        
        if not self._zwave_client.driver:
            _LOGGER.error("Z-Wave driver is None - cannot discover locks")
            _LOGGER.error("Lock features will not be available")
            return
        
        _LOGGER.info(f"Z-Wave driver ready, controller has {len(self._zwave_client.driver.controller.nodes)} nodes")
        
        all_lock_entities = self.hass.states.async_entity_ids('lock')
        _LOGGER.warning(f"Found {len(all_lock_entities)} total lock entities: {all_lock_entities}")
        
        for entity_id in all_lock_entities:
            state = self.hass.states.get(entity_id)
            if not state:
                _LOGGER.warning(f"  - {entity_id}: No state object found")
                continue
            
            _LOGGER.warning(f"  - Checking {entity_id}:")
            _LOGGER.warning(f"    Attributes: {state.attributes}")
            
            if 'garage' in entity_id.lower():
                _LOGGER.warning(f"    SKIPPING (contains 'garage')")
                continue
            
            node_id = state.attributes.get('node_id')
            if node_id is None:
                _LOGGER.warning(f"    No node_id attribute - this may not be a Z-Wave JS lock")
                _LOGGER.warning(f"    Integration: {state.attributes.get('integration')}")
                continue
            
            _LOGGER.warning(f"    node_id: {node_id}")
            
            node = self._zwave_client.driver.controller.nodes.get(node_id)
            if not node:
                _LOGGER.warning(f"    Node {node_id} not found in Z-Wave controller")
                _LOGGER.warning(f"    Available nodes: {list(self._zwave_client.driver.controller.nodes.keys())}")
                continue
            
            _LOGGER.warning(f"    Node found: {node.device_config.description}")
            _LOGGER.warning(f"    Command classes: {list(node.command_classes.keys())}")
            
            if CommandClass.DOOR_LOCK in node.command_classes:
                self._managed_locks.append(entity_id)
                self._lock_nodes[entity_id] = node
                _LOGGER.warning(f"    ✓ ADDED to managed locks")
            else:
                _LOGGER.warning(f"    ✗ No DOOR_LOCK command class (has: {list(node.command_classes.keys())})")
        
        _LOGGER.warning(f"=== LOCK DISCOVERY COMPLETE: {len(self._managed_locks)} locks managed ===")
        _LOGGER.warning(f"Managed lock entities: {self._managed_locks}")
        _LOGGER.warning(f"Managed lock nodes: {[(eid, node.node_id) for eid, node in self._lock_nodes.items()]}")
    
    def _get_node_from_entity(self, entity_id: str) -> Optional[ZwaveNode]:
        """Get Z-Wave node from entity ID."""
        return self._lock_nodes.get(entity_id)
    
    def _get_usercode_value(self, node: ZwaveNode, slot: int) -> Optional[ZwaveValue]:
        """Get the usercode value for a specific slot."""
        for value in node.values.values():
            if (value.command_class == CommandClass.USER_CODE and
                value.property_ == "userCode" and
                value.property_key == slot):
                return value
        return None
    
    async def get_user_pin_from_lock(self, user_id: int, lock_entity_id: Optional[str] = None) -> Optional[str]:
        """Retrieve the actual PIN for a user from Z-Wave JS."""
        if user_id == -1 or not self._managed_locks:
            return None
        
        slot = await self.hass.async_add_executor_job(
            self.database.get_user_lock_slot,
            user_id
        )
        
        if slot is None:
            _LOGGER.debug(f"No slot assigned for user {user_id}")
            return None
        
        target_lock = lock_entity_id or self._managed_locks[0]
        node = self._get_node_from_entity(target_lock)
        
        if not node:
            _LOGGER.warning(f"No Z-Wave node found for {target_lock}")
            return None
        
        try:
            usercode_value = self._get_usercode_value(node, slot)
            if not usercode_value:
                _LOGGER.debug(f"No usercode value for slot {slot} on {target_lock}")
                return None
            
            value_data = usercode_value.value
            if isinstance(value_data, str):
                pin = value_data.split(':')[0]
                if pin and pin != "0" * len(pin):
                    _LOGGER.debug(f"Retrieved PIN for user {user_id} from slot {slot}: {len(pin)} digits")
                    return pin
            
        except Exception as e:
            _LOGGER.warning(f"Failed to get usercode from {target_lock} slot {slot}: {e}")
        
        return None
    
    async def get_user_lock_status(self, user_id: int) -> Dict[str, Any]:
        """Get the lock enablement status for a user across all locks."""
        if user_id == -1:
            return {}
        
        slot = await self.hass.async_add_executor_job(
            self.database.get_user_lock_slot,
            user_id
        )
        
        if slot is None:
            return {}
        
        status = {}
        for lock_entity_id in self._managed_locks:
            node = self._get_node_from_entity(lock_entity_id)
            if not node:
                status[lock_entity_id] = False
                continue
            
            try:
                usercode_value = self._get_usercode_value(node, slot)
                if usercode_value and usercode_value.value:
                    value_data = str(usercode_value.value)
                    pin = value_data.split(':')[0] if ':' in value_data else value_data
                    status[lock_entity_id] = bool(pin and pin != "0" * len(pin))
                else:
                    status[lock_entity_id] = False
                    
            except Exception as e:
                _LOGGER.warning(f"Error getting lock status for {lock_entity_id}: {e}")
                status[lock_entity_id] = False
        
        return status
    
    async def set_user_lock_enabled(self, user_id: int, lock_entity_id: str, enabled: bool) -> bool:
        """Enable or disable a user on a specific lock."""
        success = await self.hass.async_add_executor_job(
            self.database.set_user_lock_access,
            user_id,
            lock_entity_id,
            enabled
        )
        
        if not success:
            _LOGGER.error(f"Failed to update DB for user {user_id} lock {lock_entity_id}")
            return False
        
        self.hass.async_create_task(
            self._sync_lock_access_background(user_id, lock_entity_id, enabled)
        )
        
        return True
    
    async def _sync_lock_access_background(self, user_id: int, lock_entity_id: str, enabled: bool) -> None:
        """Background task to sync lock access to Z-Wave JS."""
        slot = await self.hass.async_add_executor_job(
            self.database.get_user_lock_slot,
            user_id
        )
        
        if slot is None:
            await self.hass.async_add_executor_job(
                self.database.update_lock_sync_status,
                user_id,
                lock_entity_id,
                False,
                "No slot assigned"
            )
            return
        
        users = await self.hass.async_add_executor_job(self.database.get_users)
        user = next((u for u in users if u['id'] == user_id), None)
        
        if not user:
            await self.hass.async_add_executor_job(
                self.database.update_lock_sync_status,
                user_id,
                lock_entity_id,
                False,
                "User not found"
            )
            return
        
        try:
            if enabled:
                # Try PIN cache first
                pin = self._pin_cache.get(user_id)

                # Try retrieving from any other managed lock
                if not pin:
                    for other_lock in self._managed_locks:
                        if other_lock != lock_entity_id:
                            pin = await self.get_user_pin_from_lock(user_id, other_lock)
                            if pin:
                                _LOGGER.debug(f"Retrieved PIN for user {user_id} from {other_lock}")
                                break

                # Last resort: try the target lock itself (re-read)
                if not pin:
                    pin = await self.get_user_pin_from_lock(user_id, lock_entity_id)

                if not pin:
                    _LOGGER.warning(
                        f"No PIN available for user {user_id} on {lock_entity_id}. "
                        f"User must be re-added with a PIN to sync to this lock."
                    )
                    await self.hass.async_add_executor_job(
                        self.database.update_lock_sync_status,
                        user_id,
                        lock_entity_id,
                        False,
                        "No PIN available - user must be re-saved with PIN"
                    )
                    return
                
                success = await self._set_lock_code(lock_entity_id, slot, user['name'], pin)
                await self.hass.async_add_executor_job(
                    self.database.update_lock_sync_status,
                    user_id,
                    lock_entity_id,
                    success,
                    None if success else "Failed to set code"
                )
                if success:
                    _LOGGER.info(f"✓ Synced user {user['name']} to {lock_entity_id}")
            else:
                success = await self._clear_lock_code(lock_entity_id, slot)
                await self.hass.async_add_executor_job(
                    self.database.update_lock_sync_status,
                    user_id,
                    lock_entity_id,
                    success,
                    None if success else "Failed to clear code"
                )
                if success:
                    _LOGGER.info(f"✓ Cleared user {user['name']} from {lock_entity_id}")
                    
        except Exception as e:
            _LOGGER.error(f"Error syncing lock access: {e}")
            await self.hass.async_add_executor_job(
                self.database.update_lock_sync_status,
                user_id,
                lock_entity_id,
                False,
                str(e)
            )
    
    async def _find_available_slot(self, lock_entity_id: str) -> Optional[int]:
        """Find the first available code slot on a lock."""
        assigned_slots = await self.hass.async_add_executor_job(
            self.database.get_assigned_slots
        )
        
        node = self._get_node_from_entity(lock_entity_id)
        if not node:
            return None
        
        occupied_slots = set()
        for value in node.values.values():
            if (value.command_class == CommandClass.USER_CODE and
                value.property_ == "userCode" and
                value.property_key is not None):
                if value.value:
                    value_data = str(value.value)
                    pin = value_data.split(':')[0] if ':' in value_data else value_data
                    if pin and pin != "0" * len(pin):
                        occupied_slots.add(value.property_key)
        
        for slot in range(1, 31):
            if slot not in assigned_slots and slot not in occupied_slots:
                return slot
        
        for slot in range(1, 31):
            if slot not in occupied_slots:
                return slot
        
        _LOGGER.warning("No available slots found on lock")
        return None
    
    async def sync_user_to_locks(self, user_id: int, pin: Optional[str] = None,
                                 lock_pin: Optional[str] = None) -> None:
        """Sync a user to all locks."""
        async with self._sync_lock:
            users = await self.hass.async_add_executor_job(self.database.get_users)
            user = next((u for u in users if u['id'] == user_id), None)
            
            if not user:
                _LOGGER.error(f"User {user_id} not found")
                return
            
            if not user['enabled']:
                await self._remove_user_from_locks(user_id, user['name'])
                return
            
            code_to_use = None
            if user.get('has_separate_lock_pin') and lock_pin:
                code_to_use = lock_pin
            elif pin:
                code_to_use = pin
            else:
                _LOGGER.warning(f"No PIN available for user {user['name']}")
                return
            
            if not code_to_use or len(code_to_use) < 4:
                _LOGGER.error(f"Invalid PIN for {user['name']}")
                return
            
            slot = await self.hass.async_add_executor_job(
                self.database.get_user_lock_slot,
                user_id
            )
            
            if slot is None and self._managed_locks:
                slot = await self._find_available_slot(self._managed_locks[0])
                if slot is None:
                    _LOGGER.error(f"No available slots for user {user['name']}")
                    return
                
                await self.hass.async_add_executor_job(
                    self.database.assign_lock_slot,
                    user_id,
                    slot
                )
                _LOGGER.info(f"Assigned slot {slot} to user {user['name']}")
            
            success_count = 0
            synced_locks = []
            for lock_entity_id in self._managed_locks:
                if await self._set_lock_code(lock_entity_id, slot, user['name'], code_to_use):
                    success_count += 1
                    synced_locks.append(lock_entity_id)
            
            _LOGGER.info(f"Synced {user['name']} to {success_count}/{len(self._managed_locks)} locks in slot {slot}")
            
            if synced_locks:
                await self.hass.async_add_executor_job(
                    self.database.initialize_user_lock_access,
                    user_id,
                    synced_locks
                )
    
    async def sync_user_to_new_locks(self, user_id: int) -> Dict[str, Any]:
        """Sync a user to newly discovered locks."""
        async with self._sync_lock:
            users = await self.hass.async_add_executor_job(self.database.get_users)
            user = next((u for u in users if u['id'] == user_id), None)
            
            if not user:
                return {"success": False, "message": "User not found"}
            
            if not user['enabled']:
                return {"success": False, "message": "User is disabled"}
            
            slot = await self.hass.async_add_executor_job(
                self.database.get_user_lock_slot,
                user_id
            )
            
            if slot is None:
                return {"success": False, "message": "User has no slot assigned"}
            
            pin = self._pin_cache.get(user_id)
            if not pin:
                for lock_entity_id in self._managed_locks:
                    pin = await self.get_user_pin_from_lock(user_id, lock_entity_id)
                    if pin:
                        break
            
            if not pin:
                return {"success": False, "message": "No PIN available"}
            
            db_access = await self.hass.async_add_executor_job(
                self.database.get_user_lock_access,
                user_id
            )
            
            new_locks = []
            for lock_entity_id in self._managed_locks:
                if lock_entity_id not in db_access:
                    new_locks.append(lock_entity_id)
                    continue
                
                if not db_access[lock_entity_id].get('last_sync_success', True):
                    new_locks.append(lock_entity_id)
                    continue
                
                if db_access[lock_entity_id].get('enabled', False):
                    actual_pin = await self.get_user_pin_from_lock(user_id, lock_entity_id)
                    if not actual_pin:
                        new_locks.append(lock_entity_id)
            
            if not new_locks:
                return {"success": True, "message": "Already synced to all locks", "synced": 0}
            
            success_count = 0
            for lock_entity_id in new_locks:
                if await self._set_lock_code(lock_entity_id, slot, user['name'], pin):
                    success_count += 1
                    await self.hass.async_add_executor_job(
                        self.database.set_user_lock_access,
                        user_id,
                        lock_entity_id,
                        True
                    )
                    await self.hass.async_add_executor_job(
                        self.database.update_lock_sync_status,
                        user_id,
                        lock_entity_id,
                        True,
                        None
                    )
            
            return {
                "success": True,
                "message": f"Synced to {success_count} of {len(new_locks)} lock(s)",
                "synced": success_count,
                "total_new": len(new_locks)
            }
    
    def _get_userid_status_value(self, node: ZwaveNode, slot: int) -> Optional[ZwaveValue]:
        """Get the userIdStatus value for a specific slot."""
        for value in node.values.values():
            if (value.command_class == CommandClass.USER_CODE and
                value.property_ == "userIdStatus" and
                value.property_key == slot):
                return value
        return None

    async def _set_lock_code(self, lock_entity_id: str, slot: int,
                            name: str, pin: str) -> bool:
        """Set a user code on a Z-Wave JS lock.
        
        Z-Wave USER_CODE command class requires setting both the userIdStatus
        (to 1=enabled) AND the userCode value. Setting just the code string
        is not enough on most locks.
        """
        _LOGGER.info(f"Setting lock code: {lock_entity_id}, slot {slot}, name: {name}, PIN length: {len(pin)}")

        try:
            node = self._get_node_from_entity(lock_entity_id)
            if not node:
                _LOGGER.error(f"No Z-Wave node found for {lock_entity_id}")
                return False

            # Set userIdStatus to 1 (enabled) first
            status_value = self._get_userid_status_value(node, slot)
            if status_value:
                try:
                    await node.async_set_value(status_value.value_id, 1)
                    _LOGGER.debug(f"Set userIdStatus=1 for slot {slot} on {lock_entity_id}")
                except Exception as e:
                    _LOGGER.warning(f"Could not set userIdStatus for slot {slot}: {e}")

            # Set the user code
            usercode_value = self._get_usercode_value(node, slot)
            if not usercode_value:
                _LOGGER.error(f"No usercode value found for slot {slot} on {lock_entity_id}")
                return False

            await node.async_set_value(usercode_value.value_id, pin)
            _LOGGER.info(f"Successfully set lock code for {name} in slot {slot} on {lock_entity_id}")
            return True

        except Exception as e:
            _LOGGER.error(f"Failed to set lock code on {lock_entity_id} slot {slot}: {type(e).__name__}: {str(e)}")
            return False
    
    async def _clear_lock_code(self, lock_entity_id: str, slot: int) -> bool:
        """Clear a user code from a Z-Wave JS lock."""
        try:
            node = self._get_node_from_entity(lock_entity_id)
            if not node:
                return False

            # Set userIdStatus to 0 (disabled/available) first
            status_value = self._get_userid_status_value(node, slot)
            if status_value:
                try:
                    await node.async_set_value(status_value.value_id, 0)
                except Exception as e:
                    _LOGGER.warning(f"Could not clear userIdStatus for slot {slot}: {e}")

            # Clear the user code
            usercode_value = self._get_usercode_value(node, slot)
            if not usercode_value:
                return False

            await node.async_set_value(usercode_value.value_id, "")
            _LOGGER.debug(f"Cleared slot {slot} on {lock_entity_id}")
            return True

        except Exception as e:
            _LOGGER.debug(f"Failed to clear lock code slot {slot}: {e}")
            return False
    
    async def _remove_user_from_locks(self, user_id: int, user_name: str) -> None:
        """Remove a user's codes from all locks."""
        slot = await self.hass.async_add_executor_job(
            self.database.get_user_lock_slot,
            user_id
        )
        
        if slot is None:
            return
        
        for lock_entity_id in self._managed_locks:
            await self._clear_lock_code(lock_entity_id, slot)
        
        await self.hass.async_add_executor_job(
            self.database.remove_lock_slot,
            user_id
        )
        
        _LOGGER.info(f"Removed {user_name} from all locks (slot {slot})")
    
    async def remove_user_from_locks(self, user_id: int) -> None:
        """Remove a user from all locks."""
        async with self._sync_lock:
            users = await self.hass.async_add_executor_job(self.database.get_users)
            user = next((u for u in users if u['id'] == user_id), None)
            
            user_name = user['name'] if user else f"User {user_id}"
            await self._remove_user_from_locks(user_id, user_name)
    
    async def sync_all_users(self) -> Dict[str, Any]:
        """Sync all enabled users to locks."""
        async with self._sync_lock:
            users = await self.hass.async_add_executor_job(self.database.get_users)
            enabled_users = [u for u in users if u['enabled']]
            
            results = {
                'total': len(enabled_users),
                'synced': 0,
                'skipped': 0,
                'errors': []
            }
            
            for user in enabled_users:
                cached_pin = self._pin_cache.get(user['id'])
                
                if not cached_pin:
                    results['skipped'] += 1
                    results['errors'].append(f"No PIN available for {user['name']}")
                    continue
                
                try:
                    await self.sync_user_to_locks(
                        user['id'],
                        pin=cached_pin if not user.get('has_separate_lock_pin') else None,
                        lock_pin=cached_pin if user.get('has_separate_lock_pin') else None
                    )
                    results['synced'] += 1
                except Exception as e:
                    results['errors'].append(f"Failed to sync {user['name']}: {str(e)}")
            
            return results
    
    def cache_pin(self, user_id: int, pin: str, is_lock_pin: bool = False) -> None:
        """Temporarily cache a PIN for sync operations."""
        self._pin_cache[user_id] = pin
        _LOGGER.debug(f"Cached {'lock ' if is_lock_pin else ''}PIN for user {user_id}")
    
    def clear_pin_cache(self, user_id: Optional[int] = None) -> None:
        """Clear cached PINs."""
        if user_id is None:
            self._pin_cache.clear()
        else:
            self._pin_cache.pop(user_id, None)
    
    def get_managed_locks(self) -> List[str]:
        """Get list of managed lock entities."""
        return self._managed_locks.copy()
    
    async def verify_user_lock_access(self, user_id: int) -> Dict[str, Any]:
        """Verify user's lock access against actual Z-Wave state."""
        slot = await self.hass.async_add_executor_job(
            self.database.get_user_lock_slot,
            user_id
        )
        
        if slot is None:
            return {"success": False, "message": "No slot assigned", "differences": []}
        
        db_access = await self.hass.async_add_executor_job(
            self.database.get_user_lock_access,
            user_id
        )
        
        differences = []
        verified_count = 0
        
        for lock_entity_id in self._managed_locks:
            try:
                pin = await self.get_user_pin_from_lock(user_id, lock_entity_id)
                actual_enabled = bool(pin)
                
                db_state = db_access.get(lock_entity_id, {})
                expected_enabled = db_state.get('enabled', False)
                
                if actual_enabled != expected_enabled:
                    differences.append({
                        'lock': lock_entity_id,
                        'expected': expected_enabled,
                        'actual': actual_enabled,
                        'action': 'updated_db'
                    })
                    
                    await self.hass.async_add_executor_job(
                        self.database.set_user_lock_access,
                        user_id,
                        lock_entity_id,
                        actual_enabled
                    )
                
                await self.hass.async_add_executor_job(
                    self.database.update_lock_sync_status,
                    user_id,
                    lock_entity_id,
                    True,
                    None
                )
                
                verified_count += 1
                
            except Exception as e:
                _LOGGER.warning(f"Error verifying {lock_entity_id}: {e}")
                await self.hass.async_add_executor_job(
                    self.database.update_lock_sync_status,
                    user_id,
                    lock_entity_id,
                    False,
                    str(e)
                )
        
        return {
            "success": True,
            "verified_count": verified_count,
            "total_locks": len(self._managed_locks),
            "differences": differences
        }
    
    async def periodic_lock_sync(self) -> Dict[str, Any]:
        """Periodic background sync of all user lock access."""
        _LOGGER.debug("Starting periodic lock sync")
        
        all_access = await self.hass.async_add_executor_job(
            self.database.get_all_user_lock_access
        )
        
        results = {
            'total_records': len(all_access),
            'verified': 0,
            'differences_found': 0,
            'errors': 0
        }
        
        users_to_verify = set(record['user_id'] for record in all_access)
        
        for user_id in users_to_verify:
            try:
                verify_result = await self.verify_user_lock_access(user_id)
                if verify_result['success']:
                    results['verified'] += 1
                    if verify_result['differences']:
                        results['differences_found'] += len(verify_result['differences'])
                else:
                    results['errors'] += 1
            except Exception as e:
                _LOGGER.error(f"Error in periodic sync for user {user_id}: {e}")
                results['errors'] += 1
        
        _LOGGER.info(f"Periodic lock sync complete: {results}")
        return results
    
    async def get_lock_status(self) -> Dict[str, Any]:
        """Get status of all locks and their codes."""
        status = {
            'locks': [],
            'total_locks': len(self._managed_locks),
            'assigned_slots': await self.hass.async_add_executor_job(
                self.database.get_assigned_slots
            )
        }
        
        for lock_entity_id in self._managed_locks:
            state = self.hass.states.get(lock_entity_id)
            node = self._get_node_from_entity(lock_entity_id)
            
            codes = {}
            if node:
                for value in node.values.values():
                    if (value.command_class == CommandClass.USER_CODE and
                        value.property_ == "userCode" and
                        value.property_key is not None):
                        if value.value:
                            codes[value.property_key] = str(value.value)
            
            lock_info = {
                'entity_id': lock_entity_id,
                'name': state.attributes.get('friendly_name', lock_entity_id) if state else lock_entity_id,
                'state': state.state if state else 'unknown',
                'codes': codes
            }
            status['locks'].append(lock_info)
        
        return status