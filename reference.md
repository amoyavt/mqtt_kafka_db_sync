# CDC Pipeline Reference Documentation

## Official Documentation

### Debezium PostgreSQL Connector
- **URL**: https://debezium.io/documentation/reference/stable/connectors/postgresql.html
- **Description**: Complete reference for PostgreSQL CDC connector configuration, requirements, and features. Covers logical decoding setup, connector properties, and troubleshooting.

### Kafka Docker Setup Guide
- **URL**: https://docs.docker.com/guides/kafka/
- **Description**: Official Docker guide for Kafka deployment using KRaft mode. Includes Docker Compose examples and best practices for development environments.

### Debezium Architecture Overview
- **URL**: https://debezium.io/documentation/reference/stable/architecture.html
- **Description**: Comprehensive overview of Debezium's architecture, how it integrates with Kafka Connect, and CDC principles.

### Confluent Kafka Connect Documentation
- **URL**: https://docs.confluent.io/platform/current/kafka/deployment.html
- **Description**: Production deployment best practices for Kafka clusters, including sizing, configuration, and monitoring recommendations.

## Key Configuration Resources

### PostgreSQL CDC Requirements
- **Logical decoding enabled**: `wal_level = logical`
- **Replication slots**: `max_replication_slots = 10`
- **WAL senders**: `max_wal_senders = 10`
- **Output plugin**: `pgoutput` (recommended, PostgreSQL 10+)

### Docker Compose Best Practices
- **URL**: https://github.com/conduktor/kafka-stack-docker-compose
- **Description**: Production-ready Kafka stack Docker Compose files with various configurations for different use cases.

## Performance and Scaling Insights

### Small-Scale Kafka Deployment
- **Replication Factor**: 2-3 for production, 1 acceptable for development
- **Partitions**: Over-provision (2-4 per topic for 1-2 consumers)
- **Memory**: Kafka uses heap carefully - 6GB max heap recommended
- **Storage**: File system cache is critical for performance

### Consumer Best Practices
- **URL**: https://www.groundcover.com/blog/kafka-consumer-best-practices
- **Description**: Modern consumer patterns, rebalancing strategies, and performance optimization for 2025.

### Cost Optimization for Small Projects
- **URL**: https://stackoverflow.blog/2024/09/04/best-practices-for-cost-efficient-kafka-clusters/
- **Description**: Resource optimization strategies, payload compression, and eliminating inactive resources.

## Practical Implementation Examples

### Medium Tutorial: Postgres + Debezium + Kafka
- **URL**: https://medium.com/@parasharprasoon.950/how-to-set-up-cdc-with-kafka-debezium-and-postgres-70a907b8ca20
- **Description**: Step-by-step tutorial with practical Docker Compose setup and connector configuration examples.

### Materialize CDC Guide
- **URL**: https://materialize.com/docs/ingest-data/postgres/postgres-debezium/
- **Description**: Production-focused guide for PostgreSQL CDC using Kafka and Debezium with real-world configurations.

## Container Orchestration Analysis

### Docker Compose vs Standalone Deployment
**Docker Compose Advantages:**
- Simplified multi-container orchestration
- Consistent development environments
- Easy networking between services
- Fast setup and teardown

**Performance Considerations:**
- Container networking adds minimal latency
- File system cache sharing in containerized environments
- Resource overhead is minimal for development use cases

### Kafka UI Tools
- **Kafka UI**: https://github.com/provectuslabs/kafka-ui
- **Description**: Modern web UI for Apache Kafka management and monitoring. Supports topics, consumers, connectors, and schema registry.

## Architecture Decision Summary

### Final Stack for 1-2 Consumers:
1. **Kafka**: Single broker with KRaft mode (no ZooKeeper)
2. **Schema Registry**: Confluent Schema Registry for Avro schema management
3. **Kafka Connect**: Debezium connector for PostgreSQL
4. **Kafka UI**: Web interface for monitoring and management
5. **Consumer Apps**: 1-2 lightweight consumers

### Key Configuration Decisions:
- **Topic Strategy**: Auto-create per table with 4 partitions
- **Serialization**: Avro format with Schema Registry
- **CDC Scope**: ALL tables across ALL schemas
- **Partitioning**: 4 partitions per topic (optimal for 1-2 consumers)
- **Retention**: 7 days (604800000ms) for development

### Debezium Security Configuration:
- **READ-ONLY access**: Debezium user has SELECT permissions only
- **No data modification**: User cannot INSERT, UPDATE, or DELETE
- **Publication management**: CREATE permission only for managing replication publications
- **Schema access**: Dynamic grants for all existing and future schemas

## Security Best Practices

### Database User Privileges
- Create dedicated `debezium` user with minimal privileges
- `REPLICATION` privilege for slot management
- `SELECT` on target tables only
- Avoid superuser privileges

### Network Security
- Use internal Docker networks for service communication
- Expose only necessary ports to host
- Consider TLS for production deployments

## Monitoring and Observability

### Key Metrics to Track:
- Replication lag
- Consumer group lag
- Topic partition distribution
- Connector status and errors
- Database replication slot usage

### Tools:
- Kafka UI for visual monitoring (includes Schema Registry integration)
- JMX metrics for detailed performance data
- Database logs for replication slot monitoring

## Deployment Commands

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

### Verify Setup:
- **Kafka UI**: http://localhost:8080
- **Schema Registry**: http://localhost:8081
- **Kafka Connect**: http://localhost:8083/connectors

## Avro Schema Management

### Benefits of Avro with Schema Registry:
- **Schema Evolution**: Backward and forward compatibility
- **Efficient Serialization**: Binary format reduces message size
- **Type Safety**: Strong typing prevents data corruption
- **Schema Versioning**: Track changes over time

### Schema Registry Endpoints:
- **List Subjects**: `GET http://localhost:8081/subjects`
- **Get Schema**: `GET http://localhost:8081/subjects/{subject}/versions/latest`
- **Schema Compatibility**: `POST http://localhost:8081/compatibility/subjects/{subject}/versions/latest`