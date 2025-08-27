#!/usr/bin/env python3
import json
import logging
import os
import signal
import sys
from typing import Dict, Any

try:
    from kafka import KafkaConsumer  # type: ignore
except ImportError:
    raise ImportError("kafka-python not installed. Run: pip install kafka-python")

try:
    import paho.mqtt.client as mqtt  # type: ignore
except ImportError:
    raise ImportError("paho-mqtt not installed. Run: pip install paho-mqtt")


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class KafkaMQTTTranslator:
    def __init__(self) -> None:
        self.kafka_bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9093')
        self.mqtt_host = os.getenv('MQTT_HOST', 'mosquitto')
        self.mqtt_port = int(os.getenv('MQTT_PORT', '1883'))
        self.kafka_topics = os.getenv('KAFKA_TOPICS', 'test').split(',')
        self.mqtt_topic_prefix = os.getenv('MQTT_TOPIC_PREFIX', 'db')
        
        self.kafka_consumer: KafkaConsumer[bytes, bytes] | None = None
        self.mqtt_client: mqtt.Client | None = None
        self.running = True
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def _setup_mqtt(self) -> None:
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
        
        try:
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
            self.mqtt_client.loop_start()
            logger.info(f"Connected to MQTT broker at {self.mqtt_host}:{self.mqtt_port}")
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise
    
    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Successfully connected to MQTT broker")
        else:
            logger.error(f"Failed to connect to MQTT broker with code {rc}")
    
    def _on_mqtt_disconnect(self, client, userdata, rc):
        logger.warning(f"Disconnected from MQTT broker with code {rc}")
    
    def _setup_kafka(self):
        try:
            self.kafka_consumer = KafkaConsumer(
                *self.kafka_topics,
                bootstrap_servers=self.kafka_bootstrap_servers,
                auto_offset_reset='latest',
                enable_auto_commit=True,
                group_id='kafka-mqtt-translator',
                value_deserializer=lambda m: json.loads(m.decode('utf-8')) if m else None,
                key_deserializer=lambda m: m.decode('utf-8') if m else None
            )
            logger.info(f"Connected to Kafka at {self.kafka_bootstrap_servers}")
            logger.info(f"Subscribed to topics: {self.kafka_topics}")
        except Exception as e:
            logger.error(f"Failed to setup Kafka consumer: {e}")
            raise
    
    def _transform_debezium_message(self, kafka_message) -> Dict[str, Any]:
        try:
            payload = kafka_message.value
            table_name = kafka_message.topic
            
            # Debug logging to see actual message structure
            logger.info(f"Raw Kafka message: {json.dumps(payload, indent=2, default=str)}")
            
            if 'payload' in payload:
                debezium_payload = payload['payload']
                operation = debezium_payload.get('op', 'unknown')
                
                operation_map = {
                    'c': 'insert',
                    'u': 'update', 
                    'd': 'delete',
                    'r': 'read'
                }
                
                operation_name = operation_map.get(operation, operation)
                
                mqtt_payload = {
                    'table': table_name,
                    'operation': operation_name,
                    'timestamp': debezium_payload.get('ts_ms'),
                    'data': {}
                }
                
                if operation_name in ['insert', 'read']:
                    mqtt_payload['data'] = debezium_payload.get('after', {})
                elif operation_name == 'update':
                    mqtt_payload['data'] = {
                        'before': debezium_payload.get('before', {}),
                        'after': debezium_payload.get('after', {})
                    }
                elif operation_name == 'delete':
                    mqtt_payload['data'] = debezium_payload.get('before', {})
                
                return mqtt_payload
            
            else:
                # Check if it's a direct Debezium message without wrapper
                if 'op' in payload:
                    operation = payload.get('op', 'unknown')
                    operation_map = {
                        'c': 'insert',
                        'u': 'update', 
                        'd': 'delete',
                        'r': 'read'
                    }
                    
                    operation_name = operation_map.get(operation, operation)
                    
                    mqtt_payload = {
                        'table': table_name,
                        'operation': operation_name,
                        'timestamp': payload.get('ts_ms'),
                        'data': {}
                    }
                    
                    if operation_name in ['insert', 'read']:
                        mqtt_payload['data'] = payload.get('after', {})
                    elif operation_name == 'update':
                        mqtt_payload['data'] = {
                            'before': payload.get('before', {}),
                            'after': payload.get('after', {})
                        }
                    elif operation_name == 'delete':
                        mqtt_payload['data'] = payload.get('before', {})
                    
                    return mqtt_payload
                
                return {
                    'table': table_name,
                    'operation': 'unknown',
                    'data': payload,
                    'timestamp': None
                }
                
        except Exception as e:
            logger.error(f"Error transforming message: {e}")
            return {
                'table': kafka_message.topic,
                'operation': 'error',
                'error': str(e),
                'raw_data': str(kafka_message.value)
            }
    
    def _publish_to_mqtt(self, table_name: str, operation: str, payload: Dict[str, Any]) -> None:
        if self.mqtt_client is None:
            logger.error("MQTT client not initialized")
            return
            
        mqtt_topic = f"{self.mqtt_topic_prefix}/{table_name}/{operation}"
        
        try:
            result = self.mqtt_client.publish(
                mqtt_topic, 
                json.dumps(payload, default=str),
                qos=1
            )
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Published to MQTT topic '{mqtt_topic}': {operation}")
            else:
                logger.error(f"Failed to publish to MQTT topic '{mqtt_topic}': {result.rc}")
                
        except Exception as e:
            logger.error(f"Error publishing to MQTT: {e}")
    
    def run(self) -> None:
        logger.info("Starting Kafka-MQTT Translator...")
        
        try:
            self._setup_mqtt()
            self._setup_kafka()
            
            if self.kafka_consumer is None:
                logger.error("Kafka consumer not initialized")
                return
            
            logger.info("Translator started successfully. Waiting for messages...")
            
            for message in self.kafka_consumer:
                if not self.running:
                    break
                
                try:
                    # Skip empty or None messages
                    if message.value is None:
                        logger.warning("Received empty message, skipping...")
                        continue
                        
                    logger.info(f"Received message from Kafka topic '{message.topic}'")
                    
                    transformed_payload = self._transform_debezium_message(message)
                    table_name = transformed_payload['table']
                    operation = transformed_payload['operation']
                    
                    self._publish_to_mqtt(table_name, operation, transformed_payload)
                    
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    continue
                
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            self._cleanup()
    
    def _cleanup(self) -> None:
        logger.info("Cleaning up...")
        
        if self.kafka_consumer:
            self.kafka_consumer.close()
            logger.info("Kafka consumer closed")
        
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            logger.info("MQTT client disconnected")
        
        logger.info("Cleanup completed")


if __name__ == "__main__":
    translator = KafkaMQTTTranslator()
    translator.run()