-- One row per vehicle that crosses the counting line.
CREATE TABLE IF NOT EXISTS vehicle_events (
    id           BIGSERIAL PRIMARY KEY,
    vehicle_id   BIGINT      NOT NULL,            -- tracker id
    vehicle_type TEXT,                            -- car / truck / bus / motorcycle
    color        TEXT        NOT NULL DEFAULT 'unknown',
    direction    TEXT        NOT NULL,            -- IN / OUT
    ts           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vehicle_events_ts ON vehicle_events (ts DESC);
