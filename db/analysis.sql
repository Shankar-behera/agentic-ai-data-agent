-- ============================================================
-- analysis.sql  —  Rides project exploratory analysis
-- Database: rides_db
-- Run:  psql -h localhost -p 5432 -U postgres -d rides_db -f db/analysis.sql
-- ============================================================

\pset pager off
\echo '=== 1. REVENUE BY CITY (top 15) ==='
SELECT u.city,
       COUNT(DISTINCT p.payment_id)            AS payments,
       ROUND(SUM(p.amount), 2)                 AS total_revenue,
       ROUND(AVG(p.amount), 2)                 AS avg_payment
FROM payments p
JOIN rides r ON r.ride_id = p.ride_id
JOIN users u ON u.user_id = p.user_id
WHERE p.payment_status = 'completed'
GROUP BY u.city
ORDER BY total_revenue DESC
LIMIT 15;

\echo ''
\echo '=== 2. REVENUE BY PROVINCE ==='
SELECT u.province,
       COUNT(DISTINCT p.payment_id) AS payments,
       ROUND(SUM(p.amount), 2)      AS total_revenue,
       ROUND(AVG(p.amount), 2)      AS avg_payment
FROM payments p
JOIN rides r ON r.ride_id = p.ride_id
JOIN users u ON u.user_id = p.user_id
WHERE p.payment_status = 'completed'
GROUP BY u.province
ORDER BY total_revenue DESC;

\echo ''
\echo '=== 3. TOP 20 DRIVERS BY AVG RATING (min 5 ratings) ==='
SELECT r.driver_id,
       u.first_name || ' ' || u.last_name AS driver_name,
       u.city,
       COUNT(*)                            AS num_ratings,
       ROUND(AVG(r.rating), 2)             AS avg_rating
FROM ratings r
JOIN users u ON u.user_id = r.driver_id
GROUP BY r.driver_id, u.first_name, u.last_name, u.city
HAVING COUNT(*) >= 5
ORDER BY avg_rating DESC, num_ratings DESC
LIMIT 20;

\echo ''
\echo '=== 4. BOTTOM 20 DRIVERS BY AVG RATING (min 5 ratings) ==='
SELECT r.driver_id,
       u.first_name || ' ' || u.last_name AS driver_name,
       u.city,
       COUNT(*)                            AS num_ratings,
       ROUND(AVG(r.rating), 2)             AS avg_rating
FROM ratings r
JOIN users u ON u.user_id = r.driver_id
GROUP BY r.driver_id, u.first_name, u.last_name, u.city
HAVING COUNT(*) >= 5
ORDER BY avg_rating ASC, num_ratings DESC
LIMIT 20;

\echo ''
\echo '=== 5. RIDES BY STATUS ==='
SELECT status, COUNT(*) AS rides,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM rides
GROUP BY status
ORDER BY rides DESC;

\echo ''
\echo '=== 6. CANCELLATION REASONS ==='
SELECT cancellation_reason, COUNT(*) AS rides
FROM rides
WHERE status = 'cancelled'
GROUP BY cancellation_reason
ORDER BY rides DESC;

\echo ''
\echo '=== 7. CANCELLATION RATE BY HOUR OF DAY (requested_at) ==='
SELECT EXTRACT(HOUR FROM requested_at)::int AS hour_of_day,
       COUNT(*)                                    AS total_rides,
       SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
       ROUND(100.0 * SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END)
             / COUNT(*), 2)                        AS cancel_pct
FROM rides
GROUP BY hour_of_day
ORDER BY hour_of_day;

\echo ''
\echo '=== 8. SURGE MULTIPLIER — FREQUENCY & FARE IMPACT ==='
SELECT surge_multiplier,
       COUNT(*)                        AS rides,
       ROUND(AVG(distance_km), 2)      AS avg_distance_km,
       ROUND(AVG(fare), 2)             AS avg_fare,
       ROUND(AVG(fare / NULLIF(distance_km, 0)), 2) AS avg_fare_per_km
FROM rides
WHERE status = 'completed'
GROUP BY surge_multiplier
ORDER BY surge_multiplier;

\echo ''
\echo '=== 9. PAYMENT METHOD MIX ==='
SELECT payment_method,
       COUNT(*)                                AS payments,
       ROUND(SUM(amount), 2)                   AS total_amount,
       ROUND(AVG(amount), 2)                   AS avg_amount,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM payments
GROUP BY payment_method
ORDER BY payments DESC;

\echo ''
\echo '=== 10. PAYMENT STATUS MIX ==='
SELECT payment_status,
       COUNT(*)              AS payments,
       ROUND(SUM(amount), 2) AS total_amount
FROM payments
GROUP BY payment_status
ORDER BY payments DESC;

\echo ''
\echo '=== 11. RIDE DURATION DISTRIBUTION (completed, minutes) ==='
WITH d AS (
    SELECT EXTRACT(EPOCH FROM (dropoff_time - pickup_time))/60.0 AS mins
    FROM rides
    WHERE status = 'completed'
      AND pickup_time IS NOT NULL
      AND dropoff_time IS NOT NULL
)
SELECT
    ROUND(MIN(mins)::numeric, 1)                      AS min_min,
    ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY mins)::numeric, 1) AS p25,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY mins)::numeric, 1) AS median,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY mins)::numeric, 1) AS p75,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY mins)::numeric, 1) AS p95,
    ROUND(MAX(mins)::numeric, 1)                      AS max_min
FROM d;

\echo ''
\echo '=== 12. DISTANCE DISTRIBUTION (completed, km) ==='
WITH d AS (
    SELECT distance_km FROM rides WHERE status = 'completed' AND distance_km > 0
)
SELECT
    ROUND(MIN(distance_km), 2)                                      AS min_km,
    ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY distance_km)::numeric, 2) AS p25,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY distance_km)::numeric, 2) AS median,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY distance_km)::numeric, 2) AS p75,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY distance_km)::numeric, 2) AS p95,
    ROUND(MAX(distance_km), 2)                                      AS max_km
FROM d;

\echo ''
\echo '=== 13. RATING vs DISTANCE / FARE (avg rating by distance bucket) ==='
WITH b AS (
    SELECT
        CASE
            WHEN r.distance_km <  2 THEN '0-2 km'
            WHEN r.distance_km <  5 THEN '2-5 km'
            WHEN r.distance_km < 10 THEN '5-10 km'
            WHEN r.distance_km < 20 THEN '10-20 km'
            ELSE '20+ km'
        END AS bucket,
        ra.rating
    FROM ratings ra
    JOIN rides r ON r.ride_id = ra.ride_id
)
SELECT bucket,
       COUNT(*)              AS ratings,
       ROUND(AVG(rating), 2) AS avg_rating
FROM b
GROUP BY bucket
ORDER BY MIN(CASE bucket
    WHEN '0-2 km' THEN 1 WHEN '2-5 km' THEN 2 WHEN '5-10 km' THEN 3
    WHEN '10-20 km' THEN 4 ELSE 5 END);

\echo ''
\echo '=== 14. ACTIVE FLEET BY MAKE / MODEL (top 15) ==='
SELECT v.make, v.model,
       COUNT(*)                                          AS vehicles,
       ROUND(AVG(v.year), 0)                             AS avg_year
FROM vehicles v
WHERE v.is_active = TRUE
GROUP BY v.make, v.model
ORDER BY vehicles DESC
LIMIT 15;

\echo ''
\echo '=== 15. RIDER ACTIVITY — TOP 15 RIDERS BY RIDE COUNT ==='
SELECT r.rider_id,
       u.first_name || ' ' || u.last_name AS rider_name,
       u.city,
       COUNT(*)                           AS rides,
       ROUND(AVG(r.fare), 2)              AS avg_fare,
       ROUND(SUM(r.fare), 2)              AS total_fare
FROM rides r
JOIN users u ON u.user_id = r.rider_id
WHERE r.status = 'completed'
GROUP BY r.rider_id, u.first_name, u.last_name, u.city
ORDER BY rides DESC
LIMIT 15;

\echo ''
\echo '=== 16. MONTHLY RIDES & REVENUE (completed) ==='
SELECT TO_CHAR(DATE_TRUNC('month', r.requested_at), 'YYYY-MM') AS month,
       COUNT(*)                                              AS rides,
       ROUND(SUM(p.amount), 2)                               AS revenue
FROM rides r
LEFT JOIN payments p ON p.ride_id = r.ride_id AND p.payment_status = 'completed'
WHERE r.status = 'completed'
GROUP BY month
ORDER BY month;

\echo ''
\echo '=== Done. ==='