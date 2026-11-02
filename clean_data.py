"""Clean the 2025 NYC yellow taxi trip records and build the hourly zone demand panel.

Input:  combined_data_final.csv (raw TLC trips, Jan-Dec 2025)
Output: data/trips_clean.parquet          one row per valid trip, all original columns
        data/hourly_zone_demand.parquet   one row per (pickup zone, hour), zeros filled in,
                                          restricted to rows suitable for linear regression
                                          (see the panel section of main())

Rows kept despite looking odd (explained by the TLC data dictionary, Mar 2025):
  - passenger_count / RatecodeID null, payment_type = 0: Flex Fare trips (upfront
    app pricing), ~24% of rows. Real trips; the meter fields are just not populated.
  - Flex Fare trips with negative fare_amount but non-negative total_amount: the fare
    breakdown is backed out of the upfront price, so fare_amount can go negative.
  - trip_distance = 0 on Flex Fare trips (no metered distance) or on negotiated /
    flat-rate fares (RatecodeID 2-5, entered without running the meter).
  - pickup == dropoff timestamp with normal distance and fare: dropoff time not
    recorded, but the trip happened and its pickup time is valid.

Rows removed (each row gets the first reason that applies), must total < 5%:
  - pickup_outside_2025:    bad pickup timestamps (2007-2009, Dec 2024)
  - unknown_zone:           PULocationID 264/265 (Unknown / outside NYC)
  - dropoff_before_pickup:  negative trip duration
  - duration_over_24h:      meter left running
  - refund_reversal:        negative fare on a card/cash/no-charge/dispute trip; it
                            mirrors an original positive record, so keeping it
                            double-counts the trip
  - flex_negative_total:    Flex Fare trip with negative total charged; no
                            documented explanation
  - meter_false_start:      zero distance, under 60 seconds, metered rate; the meter
                            was started and stopped without a trip
  - impossible_distance:    trip_distance > 100 miles (odometer errors up to 250k mi)
  - exact_duplicate:        identical copies of another row
"""

import argparse
from pathlib import Path

import duckdb

MAX_REMOVED_SHARE = 0.05

COLUMNS = {
    "VendorID": "BIGINT",
    "tpep_pickup_datetime": "TIMESTAMP",
    "tpep_dropoff_datetime": "TIMESTAMP",
    "passenger_count": "DOUBLE",
    "trip_distance": "DOUBLE",
    "RatecodeID": "DOUBLE",
    "store_and_fwd_flag": "VARCHAR",
    "PULocationID": "BIGINT",
    "DOLocationID": "BIGINT",
    "payment_type": "BIGINT",
    "fare_amount": "DOUBLE",
    "extra": "DOUBLE",
    "mta_tax": "DOUBLE",
    "tip_amount": "DOUBLE",
    "tolls_amount": "DOUBLE",
    "improvement_surcharge": "DOUBLE",
    "total_amount": "DOUBLE",
    "congestion_surcharge": "DOUBLE",
    "Airport_fee": "DOUBLE",
    "cbd_congestion_fee": "DOUBLE",
}

REMOVAL_REASON = """
CASE
    WHEN tpep_pickup_datetime < TIMESTAMP '2025-01-01'
      OR tpep_pickup_datetime >= TIMESTAMP '2026-01-01'               THEN 'pickup_outside_2025'
    WHEN PULocationID IN (264, 265)                                    THEN 'unknown_zone'
    WHEN tpep_dropoff_datetime < tpep_pickup_datetime                  THEN 'dropoff_before_pickup'
    WHEN date_diff('second', tpep_pickup_datetime,
                   tpep_dropoff_datetime) > 86400                      THEN 'duration_over_24h'
    WHEN fare_amount < 0 AND payment_type <> 0                         THEN 'refund_reversal'
    WHEN payment_type = 0 AND total_amount < 0                         THEN 'flex_negative_total'
    WHEN trip_distance = 0
     AND date_diff('second', tpep_pickup_datetime,
                   tpep_dropoff_datetime) < 60
     AND payment_type <> 0
     AND RatecodeID NOT IN (2, 3, 4, 5)                                THEN 'meter_false_start'
    WHEN trip_distance > 100                                           THEN 'impossible_distance'
END
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--input", type=Path, default=Path("combined_data_final.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("data"))
    parser.add_argument("--min-mean-pickups", type=float, default=1.0,
                        help="drop zones averaging fewer pickups per hour than this")
    args = parser.parse_args()

    args.out_dir.mkdir(exist_ok=True)
    trips_path = args.out_dir / "trips_clean.parquet"
    panel_path = args.out_dir / "hourly_zone_demand.parquet"

    con = duckdb.connect()
    con.execute(f"SET temp_directory = '{args.out_dir / '.duckdb_tmp'}'")

    print(f"Reading {args.input} ...")
    con.execute(
        f"""
        CREATE TABLE raw AS
        SELECT *, {REMOVAL_REASON} AS removal_reason
        FROM read_csv(?, header = true, columns = {COLUMNS},
                      timestampformat = '%Y-%m-%d %H:%M:%S')
        """,
        [str(args.input)],
    )
    n_raw = con.execute("SELECT count(*) FROM raw").fetchone()[0]

    con.execute(
        """
        CREATE TABLE clean AS
        SELECT DISTINCT * EXCLUDE (removal_reason) FROM raw WHERE removal_reason IS NULL
        """
    )
    reasons = con.execute(
        "SELECT removal_reason, count(*) FROM raw WHERE removal_reason IS NOT NULL "
        "GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    n_flagged = sum(n for _, n in reasons)
    con.execute("DROP TABLE raw")
    n_clean = con.execute("SELECT count(*) FROM clean").fetchone()[0]
    reasons.append(("exact_duplicate", n_raw - n_flagged - n_clean))

    print(f"\n{'reason':<24}{'rows':>12}{'share':>9}")
    for reason, n in reasons:
        print(f"{reason:<24}{n:>12,}{n / n_raw:>9.3%}")
    n_removed = n_raw - n_clean
    print(f"{'TOTAL REMOVED':<24}{n_removed:>12,}{n_removed / n_raw:>9.3%}")
    print(f"{'kept':<24}{n_clean:>12,}{n_clean / n_raw:>9.3%}\n")
    if n_removed / n_raw >= MAX_REMOVED_SHARE:
        raise SystemExit(f"Removed {n_removed / n_raw:.2%} of rows, over the 5% limit; not writing output.")

    con.execute(
        f"COPY (SELECT * FROM clean ORDER BY tpep_pickup_datetime) TO '{trips_path}' (FORMAT parquet)"
    )
    print(f"Wrote {trips_path}")

    # Full zone x hour grid so hours with no pickups appear as 0. Timestamps are local
    # (America/New_York) wall-clock time: 2025-03-09 02:00 does not exist (spring
    # forward) and 2025-11-02 01:00 occurs twice (fall back), holding ~2x trips.
    con.execute(
        """
        CREATE TABLE panel AS
        WITH zones AS (SELECT DISTINCT PULocationID FROM clean),
        hours AS (
            SELECT generate_series AS pickup_hour
            FROM generate_series(TIMESTAMP '2025-01-01 00:00', TIMESTAMP '2025-12-31 23:00',
                                 INTERVAL 1 HOUR)
            WHERE generate_series <> TIMESTAMP '2025-03-09 02:00'
        ),
        counts AS (
            SELECT PULocationID, date_trunc('hour', tpep_pickup_datetime) AS pickup_hour,
                   count(*) AS pickups
            FROM clean GROUP BY 1, 2
        )
        SELECT z.PULocationID, h.pickup_hour, coalesce(c.pickups, 0) AS pickups
        FROM zones z CROSS JOIN hours h
        LEFT JOIN counts c USING (PULocationID, pickup_hour)
        """
    )
    n_panel, = con.execute("SELECT count(*) FROM panel").fetchone()

    # Rows unsuitable for linear regression:
    #  - low-demand zones: counts pinned near zero (mostly 0s) cannot be fit by a linear
    #    model; they give negative predictions and heteroskedastic residuals
    #  - the repeated fall-back hour: an artificial ~2x outlier
    # Zero-pickup hours inside the kept zones stay; dropping them would bias demand up.
    con.execute(
        """
        CREATE TABLE panel_lr AS
        SELECT PULocationID, pickup_hour, pickups, ln(1 + pickups) AS log_pickups
        FROM panel
        WHERE PULocationID IN (SELECT PULocationID FROM panel GROUP BY 1 HAVING avg(pickups) >= ?)
          AND pickup_hour <> TIMESTAMP '2025-11-02 01:00'
        """,
        [args.min_mean_pickups],
    )
    zones, hours, rows, total, zero_share = con.execute(
        """SELECT count(DISTINCT PULocationID), count(DISTINCT pickup_hour), count(*), sum(pickups),
                  avg((pickups = 0)::int) FROM panel_lr"""
    ).fetchone()
    print(f"\nHourly panel: {n_panel:,} zone-hours, kept {rows:,} ({rows / n_panel:.1%}) for LR")
    print(f"  zones averaging >= {args.min_mean_pickups} pickups/hour: {zones}, "
          f"covering {total / n_clean:.1%} of clean trips")
    print(f"  hours: {hours} (dropped the repeated 2025-11-02 01:00)")
    print(f"  zero-pickup cells: {zero_share:.1%}")

    con.execute(
        f"COPY (SELECT * FROM panel_lr ORDER BY PULocationID, pickup_hour) TO '{panel_path}' (FORMAT parquet)"
    )
    print(f"Wrote {panel_path}")


if __name__ == "__main__":
    main()
