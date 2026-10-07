import csv
import json
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from time import perf_counter


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
    point_batch_size: int = 100000,
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

# How many taxis, trips, and total GPS points are there?
def part2Question1():
    
    return None

if __name__ == "__main__":
    part1EDA()
    #part1Populate()
    part2Question1()
