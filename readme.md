### Start the Stack:
```bash
docker-compose up -d
```

### Configure Debezium Connector:
```bash
curl -X POST http://localhost:8083/connectors \
  -H "Content-Type: application/json" \
  -d @services/kafkaconnect/debezium-connector-config.json
```