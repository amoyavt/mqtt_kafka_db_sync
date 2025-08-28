#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import signal
import time
from typing import Dict, Any, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    raise ImportError("paho-mqtt not installed. Run: pip install paho-mqtt")

try:
    import asyncpg
except ImportError:
    raise ImportError("asyncpg not installed. Run: pip install asyncpg")


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IoTReplicaService:
    def __init__(self):
        # MQTT Configuration
        self.mqtt_host = os.getenv('MQTT_HOST', 'localhost')
        self.mqtt_port = int(os.getenv('MQTT_PORT', '1883'))
        self.mqtt_topic_prefix = os.getenv('MQTT_TOPIC_PREFIX', 'db')
        
        # PostgreSQL Configuration
        self.pg_host = os.getenv('POSTGRES_HOST', 'localhost')
        self.pg_port = int(os.getenv('POSTGRES_PORT', '5432'))
        self.pg_user = os.getenv('POSTGRES_USER', 'replica')
        self.pg_password = os.getenv('POSTGRES_PASSWORD', 'replica_password')
        self.pg_database = os.getenv('POSTGRES_DB', 'replica_db')
        
        # Internal components
        self.mqtt_client: Optional[mqtt.Client] = None
        self.db_pool: Optional[asyncpg.Pool] = None
        self.message_buffer = asyncio.Queue(maxsize=500)
        self.running = True
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    async def _setup_database(self) -> None:
        """Initialize PostgreSQL connection pool and create tables"""
        try:
            # Create connection pool
            self.db_pool = await asyncpg.create_pool(
                host=self.pg_host,
                port=self.pg_port,
                user=self.pg_user,
                password=self.pg_password,
                database=self.pg_database,
                min_size=2,
                max_size=10,
                command_timeout=60
            )
            
            # Initialize database schema
            await self._init_database_schema()
            
            logger.info(f"Database pool created for {self.pg_host}:{self.pg_port}/{self.pg_database}")
            
        except Exception as e:
            logger.error(f"Failed to setup database: {e}")
            raise
    
    async def _init_database_schema(self):
        """Initialize database schema with metadata tables"""
        async with self.db_pool.acquire() as conn:
            # Create sync metadata table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS _sync_metadata (
                    table_name VARCHAR(255) PRIMARY KEY,
                    last_sync_timestamp BIGINT NOT NULL,
                    total_records INTEGER DEFAULT 0,
                    last_error TEXT DEFAULT NULL,
                    sync_status VARCHAR(20) DEFAULT 'active' 
                        CHECK (sync_status IN ('active', 'paused', 'error')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create sync log table for monitoring
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS _sync_log (
                    id SERIAL PRIMARY KEY,
                    table_name VARCHAR(255) NOT NULL,
                    operation VARCHAR(20) NOT NULL 
                        CHECK (operation IN ('insert', 'update', 'delete', 'error')),
                    record_id TEXT,
                    timestamp BIGINT NOT NULL,
                    payload JSONB,
                    error_message TEXT DEFAULT NULL,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sync_log_table_timestamp 
                ON _sync_log (table_name, timestamp)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sync_log_processed_at 
                ON _sync_log (processed_at)
            """)
            
            logger.info("Database schema initialized")
    
    def _setup_mqtt(self) -> None:
        """Initialize MQTT client and subscribe to database topics"""
        try:
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_message = self._on_mqtt_message
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            
            # Connect to MQTT broker
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
            self.mqtt_client.loop_start()
            
            logger.info(f"Connected to MQTT broker at {self.mqtt_host}:{self.mqtt_port}")
            
        except Exception as e:
            logger.error(f"Failed to setup MQTT client: {e}")
            raise
    
    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Successfully connected to MQTT broker")
            # Subscribe to all database change topics
            topic_pattern = f"{self.mqtt_topic_prefix}/+/+"  # db/table/operation
            client.subscribe(topic_pattern, qos=1)
            logger.info(f"Subscribed to topic pattern: {topic_pattern}")
        else:
            logger.error(f"Failed to connect to MQTT broker with code {rc}")
    
    def _on_mqtt_disconnect(self, client, userdata, rc):
        logger.warning(f"Disconnected from MQTT broker with code {rc}")
    
    def _on_mqtt_message(self, client, userdata, message):
        """MQTT message callback - adds messages to internal buffer"""
        try:
            # Parse topic: db/table_name/operation
            topic_parts = message.topic.split('/')
            if len(topic_parts) < 3:
                logger.warning(f"Invalid topic format: {message.topic}")
                return
                
            payload = json.loads(message.payload.decode('utf-8'))
            
            # Add to internal buffer for async processing
            asyncio.create_task(self.message_buffer.put({
                'topic': message.topic,
                'table_name': topic_parts[1],
                'operation': topic_parts[2], 
                'payload': payload,
                'timestamp': time.time(),
                'qos': message.qos
            }))
            
            logger.debug(f"Buffered message from topic {message.topic}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse MQTT message JSON: {e}")
        except Exception as e:
            logger.error(f"Error buffering MQTT message: {e}")
    
    async def _sync_processor(self):
        """Async processor that handles buffered messages and syncs to local DB"""
        logger.info("Sync processor started")
        
        while self.running:
            try:
                # Get message from buffer with timeout
                message = await asyncio.wait_for(
                    self.message_buffer.get(), 
                    timeout=1.0
                )
                
                # Process the message
                await self._process_sync_message(message)
                
            except asyncio.TimeoutError:
                # No messages in buffer, continue loop
                continue
            except Exception as e:
                logger.error(f"Error in sync processor: {e}")
                await asyncio.sleep(1)  # Brief pause on error
        
        logger.info("Sync processor stopped")
    
    async def _process_sync_message(self, message: Dict[str, Any]):
        """Process a single sync message and update local database"""
        async with self.db_pool.acquire() as conn:
            try:
                table_name = message['table_name']
                operation = message['operation']
                payload = message['payload']
                
                logger.info(f"Processing {operation} for table {table_name}")
                
                # Ensure table exists
                await self._ensure_table_exists(conn, table_name, payload.get('data', {}))
                
                # Apply operation
                if operation == 'insert':
                    await self._handle_insert(conn, table_name, payload)
                elif operation == 'update':
                    await self._handle_update(conn, table_name, payload)
                elif operation == 'delete':
                    await self._handle_delete(conn, table_name, payload)
                else:
                    logger.warning(f"Unknown operation: {operation}")
                
                # Log the operation
                await self._log_sync_operation(conn, message, None)
                
                # Update sync metadata
                await self._update_sync_metadata(conn, table_name, message['timestamp'])
                
            except Exception as e:
                logger.error(f"Error processing sync message: {e}")
                logger.error(f"Message: {json.dumps(message, indent=2, default=str)}")
                
                # Log the error
                await self._log_sync_operation(conn, message, str(e))
    
    async def _ensure_table_exists(self, conn: asyncpg.Connection, table_name: str, sample_data: Dict[str, Any]):
        """Dynamically create table based on first data sample"""
        try:
            # Check if table exists
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = $1 AND table_schema = 'public'
                )
            """, table_name)
            
            if not exists:
                # Create table dynamically based on data structure
                columns = []
                for key, value in sample_data.items():
                    if isinstance(value, int):
                        columns.append(f"{key} INTEGER")
                    elif isinstance(value, float):
                        columns.append(f"{key} REAL")
                    elif isinstance(value, bool):
                        columns.append(f"{key} BOOLEAN")
                    else:
                        columns.append(f"{key} TEXT")
                
                # Add metadata columns
                columns.extend([
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ])
                
                create_sql = f"CREATE TABLE {table_name} ({', '.join(columns)})"
                await conn.execute(create_sql)
                
                logger.info(f"Created table {table_name} with columns: {columns}")
                
        except Exception as e:
            logger.error(f"Error ensuring table exists: {e}")
            raise
    
    async def _handle_insert(self, conn: asyncpg.Connection, table_name: str, payload: Dict[str, Any]):
        """Handle insert operation"""
        data = payload.get('data', {})
        if not data:
            return
            
        columns = list(data.keys())
        placeholders = ', '.join([f'${i+1}' for i in range(len(columns))])
        values = list(data.values())
        
        # Use UPSERT for idempotency
        if 'id' in data:
            conflict_clause = f"ON CONFLICT (id) DO UPDATE SET {', '.join([f'{col} = EXCLUDED.{col}' for col in columns])}"
        else:
            conflict_clause = "ON CONFLICT DO NOTHING"
            
        sql = f"""
            INSERT INTO {table_name} ({', '.join(columns)}) 
            VALUES ({placeholders}) 
            {conflict_clause}
        """
        
        await conn.execute(sql, *values)
        logger.debug(f"Inserted record into {table_name}")
    
    async def _handle_update(self, conn: asyncpg.Connection, table_name: str, payload: Dict[str, Any]):
        """Handle update operation"""
        data = payload.get('data', {})
        after_data = data.get('after', {}) if isinstance(data, dict) and 'after' in data else data
        
        if not after_data:
            return
            
        columns = list(after_data.keys())
        placeholders = ', '.join([f'${i+1}' for i in range(len(columns))])
        values = list(after_data.values())
        
        # Use UPSERT for updates
        if 'id' in after_data:
            conflict_clause = f"ON CONFLICT (id) DO UPDATE SET {', '.join([f'{col} = EXCLUDED.{col}' for col in columns])}"
        else:
            conflict_clause = "ON CONFLICT DO NOTHING"
            
        sql = f"""
            INSERT INTO {table_name} ({', '.join(columns)}) 
            VALUES ({placeholders}) 
            {conflict_clause}
        """
        
        await conn.execute(sql, *values)
        logger.debug(f"Updated record in {table_name}")
    
    async def _handle_delete(self, conn: asyncpg.Connection, table_name: str, payload: Dict[str, Any]):
        """Handle delete operation"""
        data = payload.get('data', {})
        
        if not data or 'id' not in data:
            logger.warning(f"Cannot delete from {table_name}: no ID provided")
            return
            
        sql = f"DELETE FROM {table_name} WHERE id = $1"
        await conn.execute(sql, data['id'])
        
        logger.debug(f"Deleted record from {table_name}")
    
    async def _log_sync_operation(self, conn: asyncpg.Connection, message: Dict[str, Any], error: Optional[str]):
        """Log sync operation for monitoring"""
        try:
            payload_data = message['payload'].get('data', {})
            record_id = payload_data.get('id') if isinstance(payload_data, dict) else None
            
            await conn.execute("""
                INSERT INTO _sync_log 
                (table_name, operation, record_id, timestamp, payload, error_message)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, 
                message['table_name'],
                message['operation'] if error is None else 'error',
                str(record_id) if record_id else None,
                int(message['timestamp'] * 1000),
                json.dumps(message['payload']),
                error
            )
        except Exception as e:
            logger.error(f"Error logging sync operation: {e}")
    
    async def _update_sync_metadata(self, conn: asyncpg.Connection, table_name: str, timestamp: float):
        """Update sync metadata for table"""
        try:
            # Get record count
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {table_name}")
            
            # Update metadata
            await conn.execute("""
                INSERT INTO _sync_metadata 
                (table_name, last_sync_timestamp, total_records, updated_at) 
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                ON CONFLICT (table_name) 
                DO UPDATE SET 
                    last_sync_timestamp = EXCLUDED.last_sync_timestamp,
                    total_records = EXCLUDED.total_records,
                    updated_at = CURRENT_TIMESTAMP
            """, table_name, int(timestamp * 1000), count)
            
        except Exception as e:
            logger.error(f"Error updating sync metadata: {e}")
    
    async def run(self):
        """Main async run method"""
        logger.info("Starting IoT Replica Service...")
        
        try:
            # Setup components
            await self._setup_database()
            self._setup_mqtt()
            
            # Start sync processor task
            sync_task = asyncio.create_task(self._sync_processor())
            
            logger.info("IoT Replica Service started successfully")
            
            # Keep running until signal received
            while self.running:
                await asyncio.sleep(1)
            
            # Cleanup
            sync_task.cancel()
            await self._cleanup()
            
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
        finally:
            await self._cleanup()
    
    async def _cleanup(self):
        """Cleanup resources"""
        logger.info("Cleaning up...")
        
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            logger.info("MQTT client disconnected")
        
        if self.db_pool:
            await self.db_pool.close()
            logger.info("Database pool closed")
        
        logger.info("Cleanup completed")


def main():
    """Main entry point"""
    service = IoTReplicaService()
    
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        logger.info("Service interrupted by user")
    except Exception as e:
        logger.error(f"Service failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())