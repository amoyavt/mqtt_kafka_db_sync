## Network Configuration

**Server (Windows/WSL):** `192.168.1.6` (Wi-Fi interface)
**Jetson IoT Device:** `192.168.1.236`

## Server Setup (Windows/WSL)

### 1. Start the Stack:
```bash
docker-compose up -d
```

### 2. Configure Debezium Connector:
```bash
curl -X POST http://localhost:8083/connectors -H "Content-Type: application/json" -d @services/kafkaconnect/debezium-connector-config.json
```

Check connector status
```bash
  curl -X GET http://localhost:8083/connectors/postgres-connector/status
```
List all connectors
```bash
  # List all connectors
  curl -X GET http://localhost:8083/connectors
```

### 3. Test Database Changes:
```bash
# Connect to PostgreSQL
docker exec -it pg16 psql -U app -d appdb

# Insert test data
INSERT INTO test (description) VALUES ('Test from server');
```

## IoT Device Setup (Jetson)

### 1. Clone repository on Jetson:
```bash
ssh nvidia@192.168.1.236
git clone https://github.com/amoyavt/mqtt_kafka_db_sync.git
cd mqtt_kafka_db_sync
```

### 2. Start IoT services on Jetson:
```bash
cd replica/
docker compose up -d
```

### 3. Monitor sync logs:
```bash
docker logs -f iot-sync
```

## Monitoring & Testing

### Server Monitoring:
- Kafka UI: http://localhost:8080
- MQTT Explorer: http://localhost:4000
- PostgreSQL: localhost:5432

### IoT Device Monitoring:
- Replica DB: 192.168.1.236:5433
- PgAdmin: http://192.168.1.236:5051

### Test Replication:
```sql
-- On server (192.168.1.6:5432)
INSERT INTO test (description) VALUES ('Replicated data test');

-- Check on Jetson (192.168.1.236:5433)  
SELECT * FROM test;
```