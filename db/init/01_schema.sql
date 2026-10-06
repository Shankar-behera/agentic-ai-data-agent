-- Schema for the rides demo dataset. Idempotent; safe to re-run on an empty database.
CREATE TABLE IF NOT EXISTS users (
    user_id      INT PRIMARY KEY,
    first_name   TEXT NOT NULL,
    last_name    TEXT NOT NULL,
    email        TEXT,
    phone        TEXT,
    city         TEXT,
    province     TEXT,
    user_type    TEXT NOT NULL CHECK (user_type IN ('rider', 'driver')),
    signup_date  DATE,
    is_active    BOOLEAN
);

CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id     INT PRIMARY KEY,
    driver_id      INT NOT NULL REFERENCES users (user_id),
    make           TEXT,
    model          TEXT,
    year           INT,
    license_plate  TEXT,
    color          TEXT,
    is_active      BOOLEAN
);

CREATE TABLE IF NOT EXISTS rides (
    ride_id              INT PRIMARY KEY,
    rider_id             INT NOT NULL REFERENCES users (user_id),
    driver_id            INT NOT NULL REFERENCES users (user_id),
    requested_at         TIMESTAMP NOT NULL,
    pickup_time          TIMESTAMP,
    dropoff_time         TIMESTAMP,
    pickup_latitude      NUMERIC,
    pickup_longitude     NUMERIC,
    dropoff_latitude     NUMERIC,
    dropoff_longitude    NUMERIC,
    distance_km          NUMERIC,
    fare                 NUMERIC,
    surge_multiplier     NUMERIC,
    status               TEXT NOT NULL,
    cancellation_reason  TEXT
);

CREATE TABLE IF NOT EXISTS ratings (
    rating_id  INT PRIMARY KEY,
    ride_id    INT NOT NULL REFERENCES rides (ride_id),
    rider_id   INT NOT NULL REFERENCES users (user_id),
    driver_id  INT NOT NULL REFERENCES users (user_id),
    rating     INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment    TEXT,
    rated_at   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id      INT PRIMARY KEY,
    ride_id         INT NOT NULL REFERENCES rides (ride_id),
    user_id         INT NOT NULL REFERENCES users (user_id),
    amount          NUMERIC,
    payment_method  TEXT,
    payment_status  TEXT,
    transaction_id  TEXT,
    payment_time    TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rides_rider      ON rides (rider_id);
CREATE INDEX IF NOT EXISTS idx_rides_driver     ON rides (driver_id);
CREATE INDEX IF NOT EXISTS idx_rides_status     ON rides (status);
CREATE INDEX IF NOT EXISTS idx_rides_requested  ON rides (requested_at);
CREATE INDEX IF NOT EXISTS idx_ratings_ride     ON ratings (ride_id);
CREATE INDEX IF NOT EXISTS idx_ratings_driver   ON ratings (driver_id);
CREATE INDEX IF NOT EXISTS idx_payments_ride    ON payments (ride_id);
CREATE INDEX IF NOT EXISTS idx_payments_user    ON payments (user_id);
CREATE INDEX IF NOT EXISTS idx_vehicles_driver  ON vehicles (driver_id);
