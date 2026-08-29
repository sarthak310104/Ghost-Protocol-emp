-- Run once after `alembic upgrade head` has created the base tables.
-- Converts the high-volume telemetry tables into Timescale hypertables
-- partitioned on their timestamp column, and sets a retention-friendly
-- chunk interval. Everything else (graph, incidents, RAG metadata) stays
-- as plain Postgres tables -- only raw telemetry needs hypertable scale.

CREATE EXTENSION IF NOT EXISTS timescaledb;

SELECT create_hypertable('spans', 'started_at', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
SELECT create_hypertable('metric_points', 'recorded_at', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);

-- Compress chunks older than 7 days to keep long retention affordable.
ALTER TABLE spans SET (timescaledb.compress, timescaledb.compress_segmentby = 'workspace_id, service_name');
ALTER TABLE metric_points SET (timescaledb.compress, timescaledb.compress_segmentby = 'workspace_id, service_name, metric_name');

SELECT add_compression_policy('spans', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('metric_points', INTERVAL '7 days', if_not_exists => TRUE);
