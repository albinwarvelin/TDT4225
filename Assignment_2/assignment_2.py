import csv
import json
from datetime import datetime, timedelta, timezone
from itertools import islice
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from DbConnector import DbConnector

GPS_BATCH_SIZE = 10_000_000

def line():
    print("\n" + "-" * 80 + "\n")

def preview_csv(file_path: Path, number_of_rows: int = 1) -> None:
    """Print the header and first data rows, including complete polylines."""
    with file_path.open(encoding="utf-8") as csv_file:
        # Each Porto trip occupies one line. Print the original CSV text.
        for row in islice(csv_file, number_of_rows + 1):
            print(row, end="")

# Counts data and returns some statistics.
def count_data(
    file_path: Path,
) -> tuple[
    int,
    int,
    int,
    list[dict[str, str]],
    list[int],
    dict[str, int],
    datetime | None,
    datetime | None,
    list[str],
    list[dict[str, str]],
]:
    """Return trip statistics, missing-data rows, and the UTC start-date range."""
    number_of_trips = 0
    unique_taxis: set[str] = set()
    number_of_missing_data = 0
    # Rows are dictionaries, so use a list to retain each full trip record.
    missing_data_rows: list[dict[str, str]] = []
    number_call_types = [0,0,0]
    day_type_counts = {"A": 0, "B": 0, "C": 0}
    earliest_timestamp: int | None = None
    latest_timestamp: int | None = None
    seen_trip_ids: set[str] = set()
    repeated_trip_ids: list[str] = []
    repeated_trip_id_set: set[str] = set()
    empty_trajectory_rows: list[dict[str, str]] = []

    with file_path.open(encoding="utf-8", newline="") as csv_file:
        # DictReader handles the header and quoted commas inside POLYLINE.
        reader = csv.DictReader(csv_file)
        for row in reader:
            number_of_trips += 1
            trip_id = row["TRIP_ID"]
            if trip_id in seen_trip_ids and trip_id not in repeated_trip_id_set:
                # Report an ID once, even when it occurs more than twice.
                repeated_trip_ids.append(trip_id)
                repeated_trip_id_set.add(trip_id)
            seen_trip_ids.add(trip_id)

            #if not json.loads(row["POLYLINE"]):
            #    # Keep the original row unchanged; list membership identifies it as empty.
            #    empty_trajectory_rows.append(row)

            taxi_id = row["TAXI_ID"]
            if taxi_id:
                # A set stores each taxi ID only once, without a list search.
                unique_taxis.add(taxi_id)
            has_missing_data = row["MISSING_DATA"] == "True"
            if has_missing_data:
                number_of_missing_data += 1
                missing_data_rows.append(row)

            call_type = row["CALL_TYPE"]
            if call_type == "A":
                number_call_types[0] += 1
            elif call_type == "B":
                number_call_types[1] += 1
            elif call_type == "C":
                number_call_types[2] += 1

            day_type_counts[row["DAY_TYPE"]] += 1

            # Compare Unix timestamps numerically; convert only the two extremes.
            timestamp = int(row["TIMESTAMP"])
            if earliest_timestamp is None or timestamp < earliest_timestamp:
                earliest_timestamp = timestamp
            if latest_timestamp is None or timestamp > latest_timestamp:
                latest_timestamp = timestamp

    earliest_start = (datetime.fromtimestamp(earliest_timestamp, tz=timezone.utc))
    latest_start = (datetime.fromtimestamp(latest_timestamp, tz=timezone.utc))

    return (
        number_of_trips,
        len(unique_taxis),
        number_of_missing_data,
        missing_data_rows,
        number_call_types,
        day_type_counts,
        earliest_start,
        latest_start,
        repeated_trip_ids,
        #empty_trajectory_rows,
    )

# Perform exploratory data analysis (EDA) on the Porto taxi dataset. Calls count_data() and prints the results.
def part1EDA() -> None:
    start_time = perf_counter()

    file_path = Path(__file__).resolve().parent / "porto" / "porto" / "porto.csv"
    preview_csv(file_path)
    print()

    (
        number_of_trips,
        number_of_taxis,
        number_of_missing_data,
        missing_data_rows,
        number_call_types,
        day_type_counts,
        earliest_start,
        latest_start,
        repeated_trip_ids,
        # empty_trajectory_rows,
    ) = count_data(file_path)
    print("Number of trips:", number_of_trips)
    print("Number of unique taxis:", number_of_taxis)
    print("Number of trips with missing data:", number_of_missing_data)
    print("Number of trips by call type: A(Central):", number_call_types[0], "B(Taxi Stand):", number_call_types[1], "C(Street):", number_call_types[2])
    print("Number of trips by day type:", "A(Normal):", day_type_counts["A"], "B(Holiday):", day_type_counts["B"], "C(Day before holiday):", day_type_counts["C"])
    print("Earliest trip start (UTC):", earliest_start)
    print("Latest trip start (UTC):", latest_start)
    print("Number of repeated trip IDs:", len(repeated_trip_ids))
    print("\n")
    print("Repeated trip IDs:", repeated_trip_ids)
    # print("Number of empty trajectories:", len(empty_trajectory_rows))

    elapsed_seconds = perf_counter() - start_time
    print(f"Processing took {elapsed_seconds:.2f} seconds.")

    #print("\nTrips with missing data:")
    #for trip in missing_data_rows:
    #   print(trip)

# Populate the Trip and GPSPoint tables with CSV data, using batches for speed.
def part1Populate(
    file_path: Path | None = None,
    batch_size: int = 20000,
    point_batch_size: int = GPS_BATCH_SIZE,
    max_trips: int | None = None,
) -> None:
    """Create Trip/GPSPoint tables and import CSV records into empty tables.

    Use max_trips for a small trial import. Successful batches stay committed
    if a later batch fails; rerunning requires empty target tables.
    """
    from DbConnector import DbConnector

    if batch_size <= 0 or point_batch_size <= 0:
        raise ValueError("Batch sizes must be positive.")
    if max_trips is not None and max_trips <= 0:
        raise ValueError("max_trips must be positive or None.")
    if file_path is None:
        file_path = Path(__file__).resolve().parent / "porto" / "porto" / "porto.csv"

    start_time = perf_counter()
    # Reserve every original ID so replacements cannot clash with later CSV rows.
    with file_path.open(encoding="utf-8", newline="") as csv_file:
        original_trip_ids = {int(row["TRIP_ID"]) for row in csv.DictReader(csv_file)}

    connector = DbConnector()
    connection = connector.db_connection
    cursor = connector.cursor
    connection.autocommit = False

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Trip (
                trip_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
                call_type CHAR(1) NULL,
                origin_call BIGINT UNSIGNED NULL,
                origin_stand INT UNSIGNED NULL,
                taxi_id INT UNSIGNED NULL,
                start_time DATETIME NULL COMMENT 'Trip start in UTC',
                day_type CHAR(1) NULL,
                missing_data BOOLEAN NULL,
                INDEX idx_trip_taxi_start (taxi_id, start_time)
            ) ENGINE=InnoDB
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS GPSPoint (
                trip_id BIGINT UNSIGNED NOT NULL,
                point_index INT UNSIGNED NOT NULL,
                longitude DOUBLE NOT NULL,
                latitude DOUBLE NOT NULL,
                PRIMARY KEY (trip_id, point_index),
                CONSTRAINT fk_gpspoint_trip
                    FOREIGN KEY (trip_id) REFERENCES Trip (trip_id)
            ) ENGINE=InnoDB
        """)

        # Ensure that the Trip and GPSPoint tables are empty before importing.
        for table_name in ("Trip", "GPSPoint"):
            cursor.execute(f"SELECT 1 FROM {table_name} LIMIT 1")
            if cursor.fetchone() is not None:
                raise ValueError("Trip and GPSPoint must be empty before importing.")

        insert_trip = """
            INSERT INTO Trip
                (trip_id, call_type, origin_call, origin_stand, taxi_id,
                 start_time, day_type, missing_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        insert_point = """
            INSERT INTO GPSPoint (trip_id, point_index, longitude, latitude)
            VALUES (%s, %s, %s, %s)
        """
        used_trip_ids: set[int] = set()
        next_replacement_id = 1
        reassigned_ids: list[tuple[int, int]] = []
        trip_batch = []
        point_batch = []
        imported_trips = 0
        imported_points = 0

        def insert_batch() -> None:
            nonlocal imported_trips, imported_points
            if not trip_batch:
                return

            # Parent trips and all their points are committed together.
            cursor.executemany(insert_trip, trip_batch)
            for offset in range(0, len(point_batch), point_batch_size):
                cursor.executemany(
                    insert_point, point_batch[offset:offset + point_batch_size]
                )
            connection.commit()
            imported_trips += len(trip_batch)
            imported_points += len(point_batch)
            trip_batch.clear()
            point_batch.clear()
            print(
                f"Imported {imported_trips:,} trips and {imported_points:,} GPS points "
                f"in {perf_counter() - start_time:.1f} seconds.",
                flush=True,
            )

        with file_path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in islice(reader, max_trips):
                trip_id = int(row["TRIP_ID"])
                if trip_id in used_trip_ids:
                    while (next_replacement_id in original_trip_ids or
                           next_replacement_id in used_trip_ids):
                        next_replacement_id += 1
                    reassigned_ids.append((trip_id, next_replacement_id))
                    trip_id = next_replacement_id
                    next_replacement_id += 1
                used_trip_ids.add(trip_id)

                # Build insertion values separately; the CSV row stays unchanged.
                timestamp = row["TIMESTAMP"]
                start_date = (
                    datetime.fromtimestamp(int(timestamp), tz=timezone.utc).replace(tzinfo=None)
                    if timestamp else None
                )
                trip_batch.append((
                    trip_id,
                    row["CALL_TYPE"] or None,
                    int(row["ORIGIN_CALL"]) if row["ORIGIN_CALL"] else None,
                    int(row["ORIGIN_STAND"]) if row["ORIGIN_STAND"] else None,
                    int(row["TAXI_ID"]) if row["TAXI_ID"] else None,
                    start_date,
                    row["DAY_TYPE"] or None,
                    {"True": True, "False": False, "": None}[row["MISSING_DATA"]],
                ))

                # Retain every supplied point, including those in incomplete trips.
                points = json.loads(row["POLYLINE"]) if row["POLYLINE"] else []
                for point_index, (longitude, latitude) in enumerate(points):
                    point_batch.append((trip_id, point_index, longitude, latitude))

                if len(trip_batch) >= batch_size:
                    insert_batch()
            insert_batch()

        print(f"Finished: {imported_trips:,} trips, {imported_points:,} GPS points.")
        print("Reassigned trip IDs (original, replacement):", reassigned_ids)
    except BaseException:
        # Roll back the current batch, including its trips and GPS points.
        connection.rollback()
        raise
    finally:
        connector.close_connection()


def part2() -> "DbConnector":
    """Open and return the shared database connector for Part 2."""
    from DbConnector import DbConnector

    return DbConnector()


# How many taxis, trips, and total GPS points are there?
def part2Question1(connector: "DbConnector") -> None:
    """Print the number of taxis, trips, and GPS points in the database."""
    start_time = perf_counter()

    cursor = connector.cursor

    cursor.execute("SELECT COUNT(DISTINCT taxi_id) FROM Trip")
    number_of_taxis = cursor.fetchone()[0]
    print("Number of taxis:", number_of_taxis)

    cursor.execute("SELECT COUNT(*) FROM Trip")
    number_of_trips = cursor.fetchone()[0]
    print("Number of trips:", number_of_trips)

    cursor.execute("SELECT COUNT(*) FROM GPSPoint")
    number_of_gps_points = cursor.fetchone()[0]
    print("Number of GPS points:", number_of_gps_points)

    elapsed_seconds = perf_counter() - start_time
    print(f"Queries took {elapsed_seconds:.2f} seconds.")

    return number_of_taxis, number_of_trips

def part2Question2(connector: "DbConnector", number_of_taxis, number_of_trips) -> None:
    start_time = perf_counter()

    average_trips_per_taxi = number_of_trips / number_of_taxis
    print("Average number of trips per taxi:", average_trips_per_taxi)

    elapsed_seconds = perf_counter() - start_time
    print(f"Queries took {elapsed_seconds:.2f} seconds.")
    
def part2Question3(connector: "DbConnector") -> None:
    """Print the top 20 taxis ranked by their number of trips."""
    start_time = perf_counter()
    cursor = connector.cursor
    cursor.execute("""
        SELECT taxi_id, COUNT(*) AS number_of_trips
        FROM Trip
        GROUP BY taxi_id
        ORDER BY number_of_trips DESC, taxi_id ASC
        LIMIT 20
    """)

    print(f"{'Taxi ID':<12} {'Number of trips':>15}")
    for taxi_id, number_of_trips in cursor.fetchall():
        print(f"{taxi_id:<12} {number_of_trips:>15}")

    elapsed_seconds = perf_counter() - start_time
    print(f"Query took {elapsed_seconds:.2f} seconds.")

def part2Question4(
    connector: "DbConnector", batch_size: int = GPS_BATCH_SIZE
) -> tuple[dict[int | None, dict[str, float]], dict[int, int], list[int]]:
    """Print call statistics; return taxi totals, trip durations and circular trip IDs."""
    import numpy as np
    from haversine import haversine, haversine_vector, Unit

    start_time = perf_counter()
    cursor = connector.cursor

    # ROW_NUMBER selects one winner per taxi. MySQL decides between tied counts.
    cursor.execute("""
        WITH call_counts AS (
            SELECT taxi_id, call_type, COUNT(*) AS number_of_trips
            FROM Trip
            GROUP BY taxi_id, call_type
        ), ranked_calls AS (
            SELECT taxi_id, call_type, number_of_trips,
                   ROW_NUMBER() OVER (
                       PARTITION BY taxi_id ORDER BY number_of_trips DESC
                   ) AS position
            FROM call_counts
        )
        SELECT taxi_id, call_type, number_of_trips
        FROM ranked_calls
        WHERE position = 1
        ORDER BY taxi_id
    """)

    print("4a: Most used call type per taxi")
    print(f"{'Taxi ID':<12} {'Call type':<10} {'Number of trips':>15}")
    most_used_call_types = cursor.fetchall()
    # Initialize every taxi, including those whose trajectories are all empty.
    taxi_statistics = {
        taxi_id: {"duration_seconds": 0, "distance_km": 0.0}
        for taxi_id, _, _ in most_used_call_types
    }
    for taxi_id, call_type, number_of_trips in most_used_call_types:
        print(f"{str(taxi_id):<12} {str(call_type):<10} {number_of_trips:>15}")

    # Count all trips, including empty/incomplete trajectories. Use stored UTC hours.
    cursor.execute("""
        SELECT call_type, COUNT(*) AS number_of_trips,
               SUM(CASE WHEN HOUR(start_time) BETWEEN 0 AND 5 THEN 1 ELSE 0 END),
               SUM(CASE WHEN HOUR(start_time) BETWEEN 6 AND 11 THEN 1 ELSE 0 END),
               SUM(CASE WHEN HOUR(start_time) BETWEEN 12 AND 17 THEN 1 ELSE 0 END),
               SUM(CASE WHEN HOUR(start_time) BETWEEN 18 AND 23 THEN 1 ELSE 0 END)
        FROM Trip
        GROUP BY call_type
        ORDER BY call_type
    """)
    call_statistics = {}
    for call_type, number_of_trips, *period_counts in cursor.fetchall():
        call_statistics[call_type] = {
            "number_of_trips": number_of_trips,
            "period_counts": period_counts,
            "duration_seconds": 0,
            "distance_km": 0.0,
        }

    call_types = list(call_statistics)
    taxi_ids = list(taxi_statistics)
    call_indices = {call_type: index for index, call_type in enumerate(call_types)}
    taxi_indices = {taxi_id: index for index, taxi_id in enumerate(taxi_ids)}
    trip_durations: dict[int, int] = {}
    circular_trip_ids: list[int] = []
    first_trip_row = None
    last_trip_row = None

    def finish_circular_trip() -> None:
        # At least three points give two 15-second intervals (a valid trip).
        if first_trip_row is None or trip_durations[first_trip_row[0]] < 30:
            return
        first_point = (first_trip_row[3], first_trip_row[4])
        last_point = (last_trip_row[3], last_trip_row[4])
        if haversine(first_point, last_point, unit=Unit.METERS) <= 50:
            circular_trip_ids.append(first_trip_row[0])

    def add_batch_statistics(point_batch, previous_row) -> None:
        nonlocal first_trip_row, last_trip_row
        # Carry one point across batches so a trip's boundary segment is retained.
        rows = [previous_row] + point_batch if previous_row is not None else point_batch
        if len(rows) < 2:
            trip_durations.setdefault(rows[0][0], 0)
            first_trip_row = last_trip_row = rows[0]
            return

        # Keep trip IDs as integers; floating-point conversion could merge large IDs.
        trip_ids = np.fromiter((row[0] for row in rows), dtype=np.uint64, count=len(rows))
        same_trip = trip_ids[1:] == trip_ids[:-1]

        # Count each trip's intervals in this batch. The carried point preserves
        # the interval across batches without counting earlier intervals twice.
        run_starts = np.concatenate(([0], np.flatnonzero(~same_trip) + 1))
        run_lengths = np.diff(np.append(run_starts, len(rows)))
        for run_start, point_count in zip(run_starts, run_lengths):
            first_row = rows[int(run_start)]
            last_row = rows[int(run_start + point_count - 1)]
            trip_id = first_row[0]
            # Sorted runs let us retain only the current trip's endpoints.
            # A trip crossing a batch boundary keeps its original first point.
            if first_trip_row is None or first_trip_row[0] != trip_id:
                finish_circular_trip()
                first_trip_row = first_row
            last_trip_row = last_row
            trip_durations[trip_id] = (
                trip_durations.get(trip_id, 0) + (int(point_count) - 1) * 15
            )

        if not same_trip.any():
            return

        # Calculate only consecutive points within the same trip, in (lat, lon) order.
        # Fill the array directly instead of creating a temporary tuple per point.
        points = np.empty((len(rows), 2), dtype=np.float64)
        points[:, 0] = np.fromiter(
            (row[3] for row in rows), dtype=np.float64, count=len(rows)
        )
        points[:, 1] = np.fromiter(
            (row[4] for row in rows), dtype=np.float64, count=len(rows)
        )
        distances = haversine_vector(points[:-1][same_trip], points[1:][same_trip])
        call_groups = np.fromiter(
            (call_indices[row[1]] for row in islice(rows, 1, None)),
            dtype=np.intp, count=len(rows) - 1
        )[same_trip]
        taxi_groups = np.fromiter(
            (taxi_indices[row[2]] for row in islice(rows, 1, None)),
            dtype=np.intp, count=len(rows) - 1
        )[same_trip]

        # Sum entire arrays rather than updating dictionaries for every GPS pair.
        call_segments = np.bincount(call_groups, minlength=len(call_types))
        call_distances = np.bincount(call_groups, weights=distances, minlength=len(call_types))
        taxi_segments = np.bincount(taxi_groups, minlength=len(taxi_ids))
        taxi_distances = np.bincount(taxi_groups, weights=distances, minlength=len(taxi_ids))
        for index, call_type in enumerate(call_types):
            call_statistics[call_type]["duration_seconds"] += int(call_segments[index]) * 15
            call_statistics[call_type]["distance_km"] += float(call_distances[index])
        for index, taxi_id in enumerate(taxi_ids):
            taxi_statistics[taxi_id]["duration_seconds"] += int(taxi_segments[index]) * 15
            taxi_statistics[taxi_id]["distance_km"] += float(taxi_distances[index])

    # Scan GPSPoint in primary-key order, then look up its trip's call type and taxi.
    # STRAIGHT_JOIN keeps GPSPoint first so the large result can use that order.
    fetch_start = perf_counter()
    cursor.execute("""
        SELECT p.trip_id, t.call_type, t.taxi_id, p.latitude, p.longitude
        FROM GPSPoint AS p
        STRAIGHT_JOIN Trip AS t ON t.trip_id = p.trip_id
        ORDER BY p.trip_id, p.point_index
    """)
    fetch_seconds = perf_counter() - fetch_start
    calculation_seconds = 0.0
    previous_row = None
    processed_points = 0
    batch_number = 0
    while True:
        batch_start = perf_counter()
        fetch_start = perf_counter()
        point_batch = cursor.fetchmany(batch_size)
        batch_fetch_seconds = perf_counter() - fetch_start
        fetch_seconds += batch_fetch_seconds
        if not point_batch:
            break

        calculation_start = perf_counter()
        add_batch_statistics(point_batch, previous_row)
        previous_row = point_batch[-1]
        batch_calculation_seconds = perf_counter() - calculation_start
        calculation_seconds += batch_calculation_seconds

        batch_number += 1
        processed_points += len(point_batch)
        # Release this batch before fetching another large batch.
        del point_batch
        print(
            f"Processed batch {batch_number:,}: {processed_points:,} GPS points total | "
            f"batch: {perf_counter() - batch_start:.1f}s "
            f"(fetch: {batch_fetch_seconds:.1f}s, calculations: {batch_calculation_seconds:.1f}s) | "
            f"elapsed: {perf_counter() - start_time:.1f}s",
            flush=True,
        )

    # The final trip has no following trip to trigger its endpoint check.
    finish_circular_trip()

    print("\n4b: Trip statistics per call type (start times in UTC)")
    print(
        f"{'Call type':<10} {'Trips':>10} {'Avg min':>10} {'Avg km':>10} "
        f"{'00-06 %':>9} {'06-12 %':>9} {'12-18 %':>9} {'18-24 %':>9}"
    )
    for call_type, statistics in call_statistics.items():
        number_of_trips = statistics["number_of_trips"]
        average_minutes = statistics["duration_seconds"] / number_of_trips / 60
        average_km = statistics["distance_km"] / number_of_trips
        percentages = [
            count / number_of_trips * 100 for count in statistics["period_counts"]
        ]
        print(
            f"{str(call_type):<10} {number_of_trips:>10} "
            f"{average_minutes:>10.2f} {average_km:>10.2f} "
            + " ".join(f"{percentage:>9.2f}" for percentage in percentages)
        )

    elapsed_seconds = perf_counter() - start_time
    print(
        f"Question 4 took {elapsed_seconds:.2f} seconds "
        f"(total GPS fetch: {fetch_seconds:.2f}s, calculations: {calculation_seconds:.2f}s)."
    )
    return taxi_statistics, trip_durations, circular_trip_ids


def part2Question5(taxi_statistics: dict[int | None, dict[str, float]]) -> None:
    """Print total driving hours and kilometres per taxi, ordered by hours."""
    start_time = perf_counter()

    # Reuse Question 4's totals; no database query or GPS calculation is needed.
    ranked_taxis = sorted(
        taxi_statistics.items(),
        key=lambda item: item[1]["duration_seconds"],
        reverse=True,
    )
    print("5: Total driving hours and distance per taxi")
    print(f"{'Taxi ID':<12} {'Total hours':>15} {'Total km':>15}")
    for taxi_id, statistics in ranked_taxis:
        total_hours = statistics["duration_seconds"] / 3600
        print(f"{str(taxi_id):<12} {total_hours:>15.2f} {statistics['distance_km']:>15.2f}")

    print(f"Question 5 took {perf_counter() - start_time:.2f} seconds.")


def part2Question6(
    connector: "DbConnector", radius_meters: float = 100.0, batch_size: int = GPS_BATCH_SIZE
) -> list[int]:
    """Return unique trip IDs with a recorded GPS point within City Hall's radius."""
    from haversine import haversine, Unit

    if radius_meters < 0:
        raise ValueError("radius_meters must not be negative.")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive.")

    start_time = perf_counter()
    cursor = connector.cursor
    city_hall = (41.15794, -8.62911)  # haversine expects (latitude, longitude).
    cursor.execute("""
        SELECT trip_id, latitude, longitude
        FROM GPSPoint
        ORDER BY trip_id, point_index
    """)

    matching_trip_ids: list[int] = []
    matched_trip_id = None
    processed_points = 0
    batch_number = 0
    while True:
        batch_start = perf_counter()
        point_batch = cursor.fetchmany(batch_size)
        if not point_batch:
            break

        for trip_id, latitude, longitude in point_batch:
            # Sorted rows keep each trip together, including across batch boundaries.
            # Once a trip matches, skip its remaining distance calculations.
            if trip_id == matched_trip_id:
                continue
            distance_meters = haversine(city_hall, (latitude, longitude), unit=Unit.METERS)
            if distance_meters <= radius_meters:
                matching_trip_ids.append(trip_id)
                matched_trip_id = trip_id

        batch_number += 1
        processed_points += len(point_batch)
        del point_batch
        print(
            f"Question 6 batch {batch_number:,}: {processed_points:,} GPS points read | "
            f"{len(matching_trip_ids):,} matching trips | "
            f"batch: {perf_counter() - batch_start:.1f}s | "
            f"elapsed: {perf_counter() - start_time:.1f}s",
            flush=True,
        )

    print(f"Trips within {radius_meters:g} m of Porto City Hall: {len(matching_trip_ids):,}")
    print(f"Question 6 took {perf_counter() - start_time:.2f} seconds.")
    return matching_trip_ids


def part2Question7(number_of_trips: int, trip_durations: dict[int, int]) -> int:
    """Count trips with fewer than three points using Question 4's interval totals."""
    start_time = perf_counter()

    # Question 4 assigns 15 seconds per recorded interval: three points mean
    # two intervals (30 seconds). Subtracting valid trips also counts empty trips.
    number_of_valid_trips = sum(seconds >= 30 for seconds in trip_durations.values())
    number_of_invalid_trips = number_of_trips - number_of_valid_trips
    print("Number of invalid trips (fewer than 3 GPS points):", number_of_invalid_trips)
    print(f"Question 7 took {perf_counter() - start_time:.2f} seconds.")
    return number_of_invalid_trips


def part2Question8(
    connector: "DbConnector", trip_durations: dict[int, int], batch_size: int = 100000
) -> list[int]:
    """Return trips crossing midnight, using the durations calculated in Question 4."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive.")

    start_time = perf_counter()
    cursor = connector.cursor
    cursor.execute("""
        SELECT trip_id, start_time
        FROM Trip
        WHERE start_time IS NOT NULL
        ORDER BY trip_id
    """)
    midnight_trip_ids: list[int] = []
    processed_trips = 0
    batch_number = 0
    while True:
        batch_start = perf_counter()
        trip_batch = cursor.fetchmany(batch_size)
        if not trip_batch:
            break

        for trip_id, trip_start in trip_batch:
            # Trips without GPS points have no duration entry and use zero seconds.
            trip_end = trip_start + timedelta(seconds=trip_durations.get(trip_id, 0))
            if trip_end.date() > trip_start.date():
                midnight_trip_ids.append(trip_id)

        batch_number += 1
        processed_trips += len(trip_batch)
        del trip_batch
        print(
            f"Question 8 batch {batch_number:,}: {processed_trips:,} trips checked | "
            f"{len(midnight_trip_ids):,} midnight crossers | "
            f"batch: {perf_counter() - batch_start:.1f}s | "
            f"elapsed: {perf_counter() - start_time:.1f}s",
            flush=True,
        )

    print("Number of trips crossing midnight (UTC):", len(midnight_trip_ids))
    print(f"Question 8 took {perf_counter() - start_time:.2f} seconds.")
    return midnight_trip_ids


def part2Question9(circular_trip_ids: list[int]) -> list[int]:
    """Report valid trips whose first and last points are within 50 metres."""
    print("Number of circular trips (at least 3 GPS points, endpoints within 50 m):",
          len(circular_trip_ids))
    print("Question 9 reuses the endpoint checks performed during Question 4.")
    return circular_trip_ids


def part2Question10(
    connector: "DbConnector", trip_durations: dict[int, int], batch_size: int = 100000
) -> dict[int, dict[str, float | int | None]]:
    """Compare all idle gaps with gaps of at most 12 hours, using stored UTC times."""
    from statistics import median

    if batch_size <= 0:
        raise ValueError("batch_size must be positive.")

    start_time = perf_counter()
    cursor = connector.cursor
    cursor.execute("""
        SELECT trip_id, taxi_id, start_time
        FROM Trip
        WHERE taxi_id IS NOT NULL AND start_time IS NOT NULL
        ORDER BY taxi_id, start_time, trip_id
    """)

    # Keep gaps per taxi because an exact median requires their individual values.
    idle_gaps: dict[int, list[float]] = {}
    previous_taxi_id = None
    previous_trip_end = None
    overlapping_pairs = 0
    processed_trips = 0
    batch_number = 0
    while True:
        batch_start = perf_counter()
        trip_batch = cursor.fetchmany(batch_size)
        if not trip_batch:
            break

        for trip_id, taxi_id, trip_start in trip_batch:
            if taxi_id == previous_taxi_id:
                gap_seconds = (trip_start - previous_trip_end).total_seconds()
                if gap_seconds < 0:
                    overlapping_pairs += 1
                # Overlapping trips contribute zero idle time.
                idle_gaps.setdefault(taxi_id, []).append(max(0.0, gap_seconds))
            previous_taxi_id = taxi_id
            previous_trip_end = trip_start + timedelta(
                seconds=trip_durations.get(trip_id, 0)
            )

        batch_number += 1
        processed_trips += len(trip_batch)
        del trip_batch
        print(
            f"Question 10 batch {batch_number:,}: {processed_trips:,} trips checked | "
            f"batch: {perf_counter() - batch_start:.1f}s | "
            f"elapsed: {perf_counter() - start_time:.1f}s",
            flush=True,
        )

    idle_statistics = {}
    excluded_breaks = 0
    for taxi_id, gaps in idle_gaps.items():
        # Exclude only gaps greater than 12 hours; exactly 12 hours still counts.
        filtered_gaps = [gap for gap in gaps if gap <= 12 * 3600]
        long_breaks = len(gaps) - len(filtered_gaps)
        excluded_breaks += long_breaks
        idle_statistics[taxi_id] = {
            "number_of_gaps": len(gaps),
            "average_seconds": sum(gaps) / len(gaps),
            "median_seconds": median(gaps),
            "filtered_number_of_gaps": len(filtered_gaps),
            "filtered_average_seconds": (
                sum(filtered_gaps) / len(filtered_gaps) if filtered_gaps else None
            ),
            "filtered_median_seconds": median(filtered_gaps) if filtered_gaps else None,
            "breaks_over_12h": long_breaks,
        }

    ranked_taxis = sorted(
        idle_statistics.items(),
        key=lambda item: (-item[1]["average_seconds"], item[0]),
    )[:20]
    print("10: Top 20 taxis by average idle time across all consecutive trips")
    print("All time values are in hours. Filtered values exclude breaks over 12 hours.")
    print(
        f"{'Taxi ID':<12} {'Avg all':>10} {'Median all':>12} "
        f"{'Avg <=12h':>12} {'Median <=12h':>14} {'Gaps':>9} {'Breaks >12h':>12}"
    )
    for taxi_id, statistics in ranked_taxis:
        filtered_average = statistics["filtered_average_seconds"]
        filtered_median = statistics["filtered_median_seconds"]
        average_text = f"{filtered_average / 3600:.2f}" if filtered_average is not None else "N/A"
        median_text = f"{filtered_median / 3600:.2f}" if filtered_median is not None else "N/A"
        print(
            f"{taxi_id:<12} {statistics['average_seconds'] / 3600:>10.2f} "
            f"{statistics['median_seconds'] / 3600:>12.2f} "
            f"{average_text:>12} {median_text:>14} "
            f"{statistics['number_of_gaps']:>9} {statistics['breaks_over_12h']:>12}"
        )

    print("Overlapping trip pairs counted as zero idle time:", overlapping_pairs)
    print("Gaps over 12 hours excluded from the filtered statistics:", excluded_breaks)
    print(f"Question 10 took {perf_counter() - start_time:.2f} seconds.")
    return idle_statistics


def main() -> None:
    part1EDA()
    line()

    #part1Populate()
    connector = part2()
    try:
        number_of_taxis, number_of_trips = part2Question1(connector)
        line()
        part2Question2(connector, number_of_taxis, number_of_trips)
        line()
        part2Question3(connector)
        line()
        # Reuse the GPS scan's totals, durations and endpoint checks below.
        taxi_statistics, trip_durations, circular_trip_ids = part2Question4(connector)
        line()
        part2Question5(taxi_statistics)
        line()
        city_hall_trip_ids = part2Question6(connector)
        line()
        number_of_invalid_trips = part2Question7(number_of_trips, trip_durations)
        line()
        midnight_trip_ids = part2Question8(connector, trip_durations)
        line()
        circular_trip_ids = part2Question9(circular_trip_ids)
        line()
        idle_statistics = part2Question10(connector, trip_durations)
    finally:
        connector.close_connection()


if __name__ == "__main__":
    main()
