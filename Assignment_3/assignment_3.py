# For each file, print row count and column count
import ast
import csv
from collections import Counter
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from pprint import pprint
from statistics import mean, median
from time import perf_counter


def describe_structure(value) -> str:
    """Show field names and types, without printing the actual data values."""
    if isinstance(value, dict): 
        fields = []
        for key, item in value.items():
            fields.append(f"{key}: {describe_structure(item)}")
        return "{" + ", ".join(fields) + "}"
    if isinstance(value, list):
        # Use the first list element as an example of its structure.
        if value:
            return "[" + describe_structure(value[0]) + "]"
        return "[]"
    return type(value).__name__

def parseNested(text: str):
    """Parse a stored list or dictionary; return None if the syntax is invalid."""
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None

def loadCSV(filename: str) -> dict:
    """Load a CSV once so its rows can be reused by later EDA steps."""
    file_path = Path(__file__).resolve().parent / "data" / filename

    csv.field_size_limit(10_000_000)
    print(f"Loading {file_path.name}...", flush=True)

    with file_path.open(encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = reader.fieldnames or []
        rows = list(reader)

    return {"filename": filename, "columns": columns, "rows": rows}

def analyzeCSV(data: dict) -> None:
    """Print the overview of an CSV."""
    print(f"Analyzing {data['filename']}...", flush=True)
    columns = data["columns"]
    rows = data["rows"]
    first_row = rows[0] if rows else {}
    movie_id_column = "movieId" if "movieId" in columns else "id"
    id_system = "MovieLens" if movie_id_column == "movieId" else "TMDB"
    has_users = "userId" in columns
    movie_ids = set()
    user_ids = set()

    # Work with the loaded rows without changing their original values.
    for row in rows:
        movie_id = (row.get(movie_id_column) or "").strip()
        if movie_id:
            movie_ids.add(movie_id)
        if has_users:
            user_id = (row.get("userId") or "").strip()
            if user_id:
                user_ids.add(user_id)

    print(f"Rows: {len(rows):,} | Columns: {len(columns)}")
    user_count = f"{len(user_ids):,}" if has_users else "-"
    print(f"Unique movie IDs: {len(movie_ids):,} | Unique users: {user_count}")
    print(f"Movie ID field: {movie_id_column} ({id_system})")
    print("Columns:", ", ".join(columns))

    print("Substructure (first row; first element of each list):")
    nested_fields = 0
    for column in columns:
        text = (first_row.get(column) or "").strip()
        if not text.startswith(("[", "{")):
            continue
        value = parseNested(text)
        if value is None:
            print(f"  {column}: could not parse first-row value")
            nested_fields += 1
            continue
        if isinstance(value, (list, dict)):
            print(f"  {column}: {describe_structure(value)}")
            nested_fields += 1
    if nested_fields == 0:
        print("  None found in the first row.")

def analyzeMetadata(data: dict) -> None:
    """Find metadata quality issues"""
    rows = data["rows"]
    total_rows = len(rows)

    def count_and_percent(count: int) -> str:
        percent = count / total_rows * 100 if total_rows else 0
        return f"{count:,} ({percent:.2f}%)"

    print("Metadata statistics")
    print(f"Rows examined: {total_rows:,}")

    # Check movie IDs and compare rows that share the same ID.
    id_counts = Counter()
    first_rows = {}
    invalid_ids = []
    conflicting_ids = set()
    for row_number, row in enumerate(rows, start=1):
        text = (row.get("id") or "").strip()
        # TMDB movie IDs must be positive ASCII integers.
        if not text.isascii() or not text.isdigit() or int(text) == 0:
            invalid_ids.append((row_number, text))
            continue
        movie_id = int(text)

        id_counts[movie_id] += 1
        if movie_id in first_rows:
            if row != first_rows[movie_id]:
                conflicting_ids.add(movie_id)
        else:
            first_rows[movie_id] = row

    repeated_ids = []
    extra_rows = 0
    for movie_id, count in id_counts.items():
        if count > 1:
            repeated_ids.append(movie_id)
            extra_rows += count - 1

    print("\nMovie IDs")
    print("Missing/invalid IDs:", count_and_percent(len(invalid_ids)))
    print("Distinct valid IDs:", f"{len(id_counts):,}")
    print("IDs appearing more than once:", len(repeated_ids))
    print("Extra rows with repeated IDs:", extra_rows)
    print("Repeated IDs with conflicting values:", len(conflicting_ids))
    print("Repeated IDs:", repeated_ids)
    for row_number, text in invalid_ids[:5]:
        print(f"  Invalid ID in data record {row_number}: {text!r}")

    # print every row sharing a repeated movie ID, including the first.
    #for movie_id in repeated_ids:
    #    print(f"\nDuplicate movie ID {movie_id} ({id_counts[movie_id]} rows):")
    #    for row_number, row in enumerate(rows, start=1):
    #        text = (row.get("id") or "").strip()
    #        if text.isascii() and text.isdigit() and int(text) == movie_id:
    #            print(f"Data record {row_number}:")
    #            pprint(row, sort_dicts=False)

    # Count blank text fields. A missing tagline differs from a missing title
    print("\nMissing text values")
    for field in ["title", "overview", "tagline", "original_language"]:
        missing = 0
        for row in rows:
            if not (row.get(field) or "").strip():
                missing += 1
        print(f"{field}: {count_and_percent(missing)}")

    # Keep missing, invalid and zero numeric values in separate categories
    print("\nNumeric values: count (% of all rows)")
    print(f"{'Field':<14} {'Missing':>18} {'Invalid':>18} {'Zero':>18}")
    positive_values = {}
    for field in ["budget", "revenue", "runtime", "vote_average", "vote_count"]:
        missing = 0
        invalid = 0
        zero = 0
        values = []
        for row in rows:
            text = (row.get(field) or "").strip()
            if not text:
                missing += 1
                continue
            try:
                value = float(text)
            except ValueError:
                invalid += 1
                continue

            if not isfinite(value) or value < 0:
                invalid += 1
            elif field == "vote_average" and value > 10:
                invalid += 1
            elif field == "vote_count" and not value.is_integer():
                invalid += 1
            elif value == 0:
                zero += 1
            else:
                values.append(value)

        positive_values[field] = values
        print(f"{field:<14} {count_and_percent(missing):>18} "
              f"{count_and_percent(invalid):>18} {count_and_percent(zero):>18}")

    # Positive-only summaries show the distribution separately from the zeros.
    print("\nPositive numeric values only (missing, invalid and zeros excluded)")
    print(f"{'Field':<14} {'Count':>8} {'Min':>17} {'Mean':>17} {'Median':>17} {'Max':>17}")
    for field, values in positive_values.items():
        if values:
            print(f"{field:<14} {len(values):>8,} {min(values):>17,.2f} "
                  f"{mean(values):>17,.2f} {median(values):>17,.2f} {max(values):>17,.2f}")
        else:
            print(f"{field}: no positive valid values")

    # Parse release dates and count movies in each decade.
    missing_dates = 0
    invalid_dates = 0
    dates = []
    decades = Counter()
    for row in rows:
        text = (row.get("release_date") or "").strip()
        if not text:
            missing_dates += 1
            continue
        try:
            release_date = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            invalid_dates += 1
            continue
        dates.append(release_date)
        decade = release_date.year // 10 * 10
        decades[decade] += 1

    print("\nRelease dates")
    print("Missing:", count_and_percent(missing_dates))
    print("Invalid:", count_and_percent(invalid_dates))
    if dates:
        print(f"Date range: {min(dates)} to {max(dates)}")
    for decade, count in sorted(decades.items()):
        print(f"  {decade}s: {count:,} movies")

    # Parse genre lists. Count each genre at most once per movie row.
    missing_genres = 0
    empty_genres = 0
    invalid_genres = 0
    genre_counts = Counter()
    for row in rows:
        text = (row.get("genres") or "").strip()
        if not text:
            missing_genres += 1
            continue
        genres = parseNested(text)
        if not isinstance(genres, list):
            invalid_genres += 1
            continue
        if not genres:
            empty_genres += 1
            continue

        names = set()
        valid_genres = True
        for genre in genres:
            if not isinstance(genre, dict):
                valid_genres = False
                break
            name = genre.get("name")
            if not isinstance(name, str) or not name.strip():
                valid_genres = False
                break
            names.add(name.strip())
        if valid_genres:
            genre_counts.update(names)
        else:
            invalid_genres += 1

    print("\nGenres")
    print("Missing:", count_and_percent(missing_genres))
    print("Empty lists:", count_and_percent(empty_genres))
    print("Invalid lists or entries:", count_and_percent(invalid_genres))
    print("Most common genres:")
    for genre, count in genre_counts.most_common(10):
        print(f"  {genre}: {count:,} movie rows")

    # Show language coverage and check optional collection membership.
    languages = Counter()
    collection_ids = set()
    movies_in_collections = 0
    invalid_collections = 0
    for row in rows:
        language = (row.get("original_language") or "").strip()
        if language:
            languages[language] += 1

        text = (row.get("belongs_to_collection") or "").strip()
        if not text or text == "None":
            continue
        collection = parseNested(text)
        if not isinstance(collection, dict):
            invalid_collections += 1
            continue
        collection_id = collection.get("id")
        name = collection.get("name")
        valid_id = type(collection_id) is int and collection_id > 0
        valid_name = isinstance(name, str) and len(name.strip()) > 0
        if not valid_id or not valid_name:
            invalid_collections += 1
            continue
        movies_in_collections += 1
        collection_ids.add(collection_id)

    print("\nMost common original languages")
    for language, count in languages.most_common(10):
        print(f"  {language}: {count:,} movie rows")
    print("\nCollection membership")
    print("Movie rows in a collection:", count_and_percent(movies_in_collections))
    print("Distinct collections:", len(collection_ids))
    print("Invalid collection entries:", count_and_percent(invalid_collections))

def part1Populate() -> None:
    """Import the CSVs without changing them; keep all duplicate movie rows."""
    from DbConnector import DbConnector
    from pymongo import ReplaceOne

    start = perf_counter()
    data_path = Path(__file__).resolve().parent / "data"
    batch_size = 5_000
    for filename in ["movies_metadata.csv", "credits.csv", "keywords.csv",
                     "links.csv", "ratings.csv"]:
        if not (data_path / filename).is_file():
            raise FileNotFoundError(data_path / filename)

    # Convert the metadata checked in EDA. Keep zero; use None for blanks.
    movies = {}
    duplicates = []
    number_types = {"budget": int, "revenue": int, "vote_count": int,
                    "runtime": float, "vote_average": float, "popularity": float}
    for row_number, row in enumerate(loadCSV("movies_metadata.csv")["rows"], 1):
        movie = row.copy()
        for field, value in movie.items():
            if not value.strip():
                movie[field] = None
        movie["_id"] = int(movie.pop("id"))
        movie["source_record"] = row_number
        for field, convert in number_types.items():
            try:
                movie[field] = convert(movie[field]) if movie[field] is not None else None
            except ValueError:
                movie[field] = None
        if movie["release_date"]:
            try:
                movie["release_date"] = datetime.strptime(
                    movie["release_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                movie["release_date"] = None
        for field in ["adult", "video"]:
            movie[field] = {"True": True, "False": False}.get(movie[field])
        for field in ["genres", "production_companies", "production_countries",
                      "spoken_languages", "belongs_to_collection"]:
            movie[field] = parseNested(movie[field]) if movie[field] else None
        for field in ["cast", "crew", "keywords"]:
            movie[field] = None

        # Keep the first row under its TMDB ID; set every extra row aside.
        movie_id = movie["_id"]
        if movie_id in movies:
            movie["duplicate_of"] = movie_id
            duplicates.append(movie)
        else:
            movies[movie_id] = movie

    # Attach cast, crew and keywords to their original TMDB movie IDs.
    for filename, fields in [("credits.csv", ["cast", "crew"]),
                             ("keywords.csv", ["keywords"])]:
        print(f"Loading and attaching {filename}...", flush=True)
        unmatched = 0
        with (data_path / filename).open(encoding="utf-8-sig", newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                movie = movies.get(int(row["id"]))
                if movie is None:
                    unmatched += 1
                    continue
                for field in fields:
                    values = parseNested(row[field])
                    if not isinstance(values, list):
                        raise ValueError(f"Invalid {field} in {filename}, movie {row['id']}")
                    if movie[field] is None:
                        movie[field] = []
                    for value in values:
                        if value not in movie[field]:
                            movie[field].append(value)
        print(f"  Rows without matching metadata: {unmatched:,}")

    # Give extra rows unused IDs, keeping a reference to the original film.
    original_ids = set(movies)
    highest_id = max(original_ids, default=0)
    for movie in duplicates:
        original = movies[movie["duplicate_of"]]
        for field in ["cast", "crew", "keywords"]:
            movie[field] = original[field]
        highest_id += 1
        movie["_id"] = highest_id
        movies[highest_id] = movie
    print(f"Movies: {len(original_ids):,} originals + {len(duplicates):,} duplicate rows")

    # Keep MovieLens -> TMDB mappings for attaching ratings to movies.
    links = []
    movie_links = {}
    for row in loadCSV("links.csv")["rows"]:
        movie_id = int(row["movieId"])
        tmdb_id = int(row["tmdbId"]) if row["tmdbId"] else None
        imdb_id = "tt" + row["imdbId"].zfill(7) if row["imdbId"] else None
        links.append({"_id": movie_id, "tmdbId": tmdb_id, "imdbId": imdb_id})
        movie_links[movie_id] = tmdb_id

    connection = DbConnector()
    try:
        db = connection.db
        # 5. Write movies and links in batches. Upsert = insert or replace by ID.
        for name, documents in [("movies", movies.values()), ("links", links)]:
            print(f"Populating {name}...", flush=True)
            batch = []
            for count, document in enumerate(documents, 1):
                batch.append(ReplaceOne({"_id": document["_id"]}, document, upsert=True))
                if len(batch) == batch_size:
                    db[name].bulk_write(batch, ordered=False)
                    batch = []
                    print(f"  {name}: {count:,}", flush=True)
            if batch:
                db[name].bulk_write(batch, ordered=False)
        del movies, duplicates, links

        # Stream ratings: only one batch stays in memory, not the entire CSV.
        print("Streaming ratings.csv...", flush=True)
        batch = []
        unmatched = 0
        with (data_path / "ratings.csv").open(encoding="utf-8-sig", newline="") as csv_file:
            for row_number, row in enumerate(csv.DictReader(csv_file), 1):
                movie_id = int(row["movieId"])
                tmdb_id = movie_links.get(movie_id)
                if tmdb_id not in original_ids:
                    unmatched += 1
                document = {
                    "_id": row_number,  # Stable on reruns of the same unchanged CSV.
                    "userId": int(row["userId"]),
                    "movieId": movie_id,
                    "tmdbId": tmdb_id,
                    "rating": float(row["rating"]),
                    "timestamp": datetime.fromtimestamp(int(row["timestamp"]), timezone.utc),
                }
                if not 0.5 <= document["rating"] <= 5:
                    raise ValueError(f"Invalid rating in record {row_number}")
                batch.append(ReplaceOne({"_id": row_number}, document, upsert=True))
                if len(batch) == batch_size:
                    db.ratings.bulk_write(batch, ordered=False)
                    batch = []
                    if row_number % 100_000 == 0:
                        print(f"  Ratings: {row_number:,} | {perf_counter() - start:.1f}s",
                              flush=True)
        if batch:
            db.ratings.bulk_write(batch, ordered=False)
        print(f"  Ratings without matching metadata: {unmatched:,}")

        # Create indexes for Part 2, then report document counts and timing.
        print("Creating indexes...", flush=True)
        db.movies.create_index([("overview", "text"), ("tagline", "text")],
                               name="movie_text", default_language="none")
        db.movies.create_index("duplicate_of")
        db.ratings.create_index("userId")
        db.ratings.create_index("tmdbId")
        db.links.create_index("tmdbId")
        for name in ["movies", "links", "ratings"]:
            print(f"{name}: {db[name].count_documents({}):,} documents")
        print(f"Population time: {perf_counter() - start:.2f} seconds")
    finally:
        # 8. Close the connection, even if an import step fails.
        connection.close_connection()



def part2Question1() -> list:
    """Find the ten directors with the highest exact median movie revenue."""
    from DbConnector import DbConnector

    connection = DbConnector()
    try:
        pipeline = [
            # Count each original film, excluding preserved duplicate versions.
            {"$match": {"duplicate_of": {"$exists": False}}},
            # Make one temporary document per crew member; keep directors only.
            {"$unwind": "$crew"},
            {"$match": {"crew.job": "Director"}},
            # Count a director only once per film, even with repeated credits.
            {"$group": {
                "_id": {"director": "$crew.id", "movie": "$_id"},
                "name": {"$first": "$crew.name"},
                "revenue": {"$first": "$revenue"},
                "vote_average": {"$first": "$vote_average"},
            }},
            # Combine those films into one result per director.
            {"$group": {
                "_id": "$_id.director",
                "director": {"$first": "$name"},
                "movie_count": {"$sum": 1},
                "revenues": {"$push": "$revenue"},
                "mean_vote_average": {"$avg": "$vote_average"},
            }},
            {"$match": {"movie_count": {"$gte": 5}}},
        ]
        directors = list(connection.db.movies.aggregate(pipeline))
        
        print("Top 10 directors with at least 5 original films based on median revenue.")
        
        # Calculate exact medians before sorting and taking the top ten.
        for director in directors:
            revenues = director.pop("revenues")
            director["median_revenue"] = median(revenues)
        directors.sort(key=lambda director: (-director["median_revenue"], director["_id"]))
        results = directors[:10]
        pprint(results, sort_dicts=False)
        return results
    finally:
        connection.close_connection()

def part2Question2() -> list:
    """List the top ten actor pairs sharing at least three original films."""
    from DbConnector import DbConnector

    connection = DbConnector()
    try:
        pipeline = [
            # Keep original films and only the fields needed for this question.
            {"$match": {"duplicate_of": {"$exists": False}}},
            {"$project": {"cast.id": 1, "cast.name": 1, "vote_average": 1}},
            # Two copies let us compare each actor with their co-stars.
            {"$set": {"cast2": "$cast"}},
            {"$unwind": "$cast"},
            {"$unwind": "$cast2"},
            # Keep A-B once; exclude B-A and actors paired with themselves.
            {"$match": {"$expr": {"$lt": ["$cast.id", "$cast2.id"]}}},
            # An actor can have several roles: count each pair once per film.
            {"$group": {
                "_id": {"movie": "$_id", "actor1": "$cast.id", "actor2": "$cast2.id"},
                "actor1": {"$first": "$cast.name"},
                "actor2": {"$first": "$cast2.name"},
                "vote_average": {"$first": "$vote_average"},
            }},
            # Combine films for the same pair and calculate their statistics.
            {"$group": {
                "_id": {"actor1": "$_id.actor1", "actor2": "$_id.actor2"},
                "actor1": {"$first": "$actor1"},
                "actor2": {"$first": "$actor2"},
                "co_appearances": {"$sum": 1},
                "mean_vote_average": {"$avg": "$vote_average"},
            }},
            {"$match": {"co_appearances": {"$gte": 3}}},
            {"$sort": {"co_appearances": -1, "_id.actor1": 1, "_id.actor2": 1}},
            {"$limit": 10},
        ]
        # Pair grouping can be large; allow MongoDB to use temporary disk space.
        results = list(connection.db.movies.aggregate(pipeline, allowDiskUse=True))
        print("Top 10 actor pairs with at least 3 original films, sorted by co-appearances.")
        pprint(results, sort_dicts=False)
        return results
    finally:
        connection.close_connection()

def part2Question3() -> list:
    """Find the ten actors with the widest genre breadth and at least ten films."""
    from DbConnector import DbConnector

    connection = DbConnector()
    try:
        pipeline = [
            # Keep original films and expand their cast into separate records.
            {"$match": {"duplicate_of": {"$exists": False}}},
            {"$unwind": "$cast"},
            # Collect distinct films and their genre lists for each actor ID.
            {"$group": {
                "_id": "$cast.id",
                "actor": {"$first": "$cast.name"},
                "movie_ids": {"$addToSet": "$_id"},
                "genre_lists": {"$addToSet": "$genres.name"},
            }},
        ]

        results = []
        for actor in connection.db.movies.aggregate(pipeline, allowDiskUse=True):
            movie_count = len(actor["movie_ids"])
            if movie_count < 10:
                continue

            # A set counts each genre once, even across many different films.
            genres = set()
            for genre_list in actor["genre_lists"]:
                for genre in genre_list or []:
                    if genre:
                        genres.add(genre)
            results.append({
                "_id": actor["_id"],
                "actor": actor["actor"],
                "movie_count": movie_count,
                "genre_count": len(genres),
                "example_genres": sorted(genres)[:5],
            })

        # Rank by genre breadth; actor ID gives a consistent order for ties.
        results.sort(key=lambda actor: (-actor["genre_count"], actor["_id"]))
        results = results[:10]
        print("Top 10 actors with at least 10 original films, sorted by genre breadth.")
        pprint(results, sort_dicts=False)
        return results
    finally:
        connection.close_connection()

def part2Question4() -> list:
    """Find the ten film collections with the highest total revenue."""
    from DbConnector import DbConnector

    connection = DbConnector()
    try:
        pipeline = [
            # Keep original movies that belong to a named film collection.
            {"$match": {
                "duplicate_of": {"$exists": False},
                "belongs_to_collection.name": {"$ne": None},
            }},
            {"$group": {
                "_id": "$belongs_to_collection.id",
                "collection": {"$first": "$belongs_to_collection.name"},
                "movie_count": {"$sum": 1},
                "total_revenue": {"$sum": "$revenue"},
                "vote_averages": {"$push": "$vote_average"},
                "earliest_release": {"$min": "$release_date"},
                "latest_release": {"$max": "$release_date"},
            }},
            {"$match": {"movie_count": {"$gte": 3}}},
            {"$sort": {"total_revenue": -1, "_id": 1}},
            {"$limit": 10},
        ]
        results = list(connection.db.movies.aggregate(pipeline))

        for collection in results:
            votes = collection.pop("vote_averages")
            collection["median_vote_average"] = median(votes)
            for field in ["earliest_release", "latest_release"]:
                if collection[field] is not None:
                    collection[field] = collection[field].strftime("%Y-%m-%d")

        print("Top 10 collections with at least 3 original films, sorted by total revenue.")
        pprint(results, sort_dicts=False)
        return results
    finally:
        connection.close_connection()

def part2Question5() -> list:
    """Report median runtime and movie count by decade and primary genre."""
    from DbConnector import DbConnector

    connection = DbConnector()
    try:
        pipeline = [
            # A movie needs a date and at least one genre to assign its group.
            {"$match": {
                "duplicate_of": {"$exists": False},
                "release_date": {"$ne": None},
                "genres.0": {"$exists": True},
            }},
            {"$project": {
                "year": {"$year": "$release_date"},
                "primary_genre": {"$arrayElemAt": ["$genres.name", 0]},
                "runtime": 1,
            }},
            # Subtract the year's last digit: 1997 - 7 gives the 1990s.
            {"$group": {
                "_id": {
                    "decade": {"$subtract": ["$year", {"$mod": ["$year", 10]}]},
                    "genre": "$primary_genre",
                },
                "movie_count": {"$sum": 1},
                "runtimes": {"$push": "$runtime"},
            }},
        ]

        results = []
        for group in connection.db.movies.aggregate(pipeline):
            # Keep zero runtimes. Missing runtimes do not affect the movie count.
            runtimes = [runtime for runtime in group["runtimes"] if runtime is not None]
            results.append({
                "decade": group["_id"]["decade"],
                "primary_genre": group["_id"]["genre"],
                "movie_count": group["movie_count"],
                "median_runtime": median(runtimes) if runtimes else None,
            })

        # Decade ascending, median descending, with missing medians last.
        results.sort(key=lambda group: (
            group["decade"],
            group["median_runtime"] is None,
            -(group["median_runtime"] or 0),
            group["primary_genre"],
        ))
        print("Median runtime and movie count by decade and primary genre.")
        pprint(results, sort_dicts=False)
        return results
    finally:
        connection.close_connection()



def part2Question6() -> list:
    """Average each movie's top-five female cast proportion by decade."""
    from DbConnector import DbConnector

    connection = DbConnector()
    try:
        decades = {}
        movies = connection.db.movies.find(
            {"duplicate_of": {"$exists": False}, "release_date": {"$ne": None}},
            {"cast.order": 1, "cast.gender": 1, "release_date": 1})
        for movie in movies:
            # Select the five billing positions before ignoring unknown genders.
            top_cast = sorted(movie.get("cast") or [], key=lambda actor: actor["order"])[:5]
            known = [actor for actor in top_cast if actor["gender"] in [1, 2]]
            if not known:
                continue
            female_count = sum(1 for actor in known if actor["gender"] == 1)
            decade = movie["release_date"].year // 10 * 10
            if decade not in decades:
                decades[decade] = []
            decades[decade].append(female_count / len(known))

        results = []
        for decade, proportions in decades.items():
            results.append({"decade": decade, "movie_count": len(proportions),
                            "average_female_proportion": mean(proportions)})
        results.sort(key=lambda row: (-row["average_female_proportion"], row["decade"]))
        print("Average female proportion in the top-five cast, by decade.")
        pprint(results, sort_dicts=False)
        return results
    finally:
        connection.close_connection()


def part2Question7() -> list:
    """Find the highest-rated noir text matches with at least fifty votes."""
    from DbConnector import DbConnector

    connection = DbConnector()
    try:
        # The existing index searches both fields; noir also matches hyphenated neo-noir.
        movies = connection.db.movies.find({
            "duplicate_of": {"$exists": False},
            "$text": {"$search": "noir"},
            "vote_count": {"$gte": 50},
        }, {"title": 1, "release_date": 1, "vote_average": 1, "vote_count": 1})
        movies = movies.sort([("vote_average", -1), ("_id", 1)]).limit(20)
        results = []
        for movie in movies:
            date = movie.pop("release_date", None)
            movie["year"] = date.year if date else None
            results.append(movie)
        print("Top 20 noir or neo-noir text matches with at least 50 votes.")
        pprint(results, sort_dicts=False)
        return results
    finally:
        connection.close_connection()


def part2Question8() -> list:
    """Rank director-actor pairs with at least three well-voted collaborations."""
    from DbConnector import DbConnector

    connection = DbConnector()
    try:
        pipeline = [
            {"$match": {"duplicate_of": {"$exists": False}, "vote_count": {"$gte": 100}}},
            {"$project": {"crew.id": 1, "crew.name": 1, "crew.job": 1,
                          "cast.id": 1, "cast.name": 1, "vote_average": 1, "revenue": 1}},
            {"$unwind": "$crew"},
            {"$match": {"crew.job": "Director"}},
            {"$unwind": "$cast"},
            # Repeated roles or credits must not count the same film twice.
            {"$group": {
                "_id": {"movie": "$_id", "director": "$crew.id", "actor": "$cast.id"},
                "director": {"$first": "$crew.name"},
                "actor": {"$first": "$cast.name"},
                "vote_average": {"$first": "$vote_average"},
                "revenue": {"$first": "$revenue"},
            }},
            {"$group": {
                "_id": {"director": "$_id.director", "actor": "$_id.actor"},
                "director": {"$first": "$director"},
                "actor": {"$first": "$actor"},
                "movie_count": {"$sum": 1},
                "mean_vote_average": {"$avg": "$vote_average"},
                "mean_revenue": {"$avg": "$revenue"},
            }},
            {"$match": {"movie_count": {"$gte": 3}}},
            {"$sort": {"mean_vote_average": -1, "_id.director": 1, "_id.actor": 1}},
            {"$limit": 20},
        ]
        results = list(connection.db.movies.aggregate(pipeline, allowDiskUse=True))
        print("Top 20 director-actor pairs; each film has at least 100 votes.")
        pprint(results, sort_dicts=False)
        return results
    finally:
        connection.close_connection()


def part2Question9() -> list:
    """Count non-English movies with a US production country by language."""
    from DbConnector import DbConnector

    connection = DbConnector()
    try:
        # Company entries have no country field; use the recorded production country.
        pipeline = [
            {"$match": {
                "duplicate_of": {"$exists": False},
                "original_language": {"$nin": ["en", None, ""]},
                "production_countries.iso_3166_1": "US",
            }},
            {"$group": {"_id": "$original_language", "movie_count": {"$sum": 1},
                        "example_title": {"$first": "$title"}}},
            {"$sort": {"movie_count": -1, "_id": 1}},
            {"$limit": 10},
        ]
        results = list(connection.db.movies.aggregate(pipeline))
        print("Top 10 non-English languages with US production countries.")
        print("Company origins are unavailable in the supplied company entries.")
        pprint(results, sort_dicts=False)
        return results
    finally:
        connection.close_connection()


def part2Question10() -> dict:
    """Report user rating counts, population variance and distinct genre counts."""
    from DbConnector import DbConnector

    connection = DbConnector()
    try:
        # Load the small movie-to-genre lookup, rather than joining every rating.
        movie_genres = {}
        for movie in connection.db.movies.find(
                {"duplicate_of": {"$exists": False}}, {"genres": 1}):
            movie_genres[movie["_id"]] = [genre["name"] for genre in movie.get("genres") or []]

        pipeline = [{"$group": {
            "_id": "$userId",
            "rating_count": {"$sum": 1},
            "rating_stddev": {"$stdDevPop": "$rating"},
            "movie_ids": {"$addToSet": "$tmdbId"},
        }}]
        users = []
        for user in connection.db.ratings.aggregate(pipeline, allowDiskUse=True):
            genres = set()
            for movie_id in user["movie_ids"]:
                genres.update(movie_genres.get(movie_id, []))
            users.append({
                "userId": user["_id"],
                "rating_count": user["rating_count"],
                # Population variance is population standard deviation squared.
                "rating_variance": user["rating_stddev"] ** 2,
                "genre_count": len(genres),
            })

        diverse = sorted(users, key=lambda user: (-user["genre_count"], user["userId"]))[:10]
        eligible = [user for user in users if user["rating_count"] >= 20]
        variable = sorted(eligible, key=lambda user: (-user["rating_variance"], user["userId"]))[:10]
        print("Top 10 most genre-diverse users.")
        pprint(diverse, sort_dicts=False)
        print("Top 10 highest-variance users with at least 20 ratings.")
        pprint(variable, sort_dicts=False)
        return {"most_genre_diverse": diverse, "highest_variance": variable}
    finally:
        connection.close_connection()



def part1EDA() -> None:
    # Load each selected file once. Comment out both lines to skip a dataset.
    file_start = perf_counter()
    movies_metadata = loadCSV("movies_metadata.csv")
    credits = loadCSV("credits.csv")
    keywords = loadCSV("keywords.csv")
    links = loadCSV("links.csv")
    links_small = loadCSV("links_small.csv")
    # ratings = loadCSV("ratings.csv")  # Large: keep disabled for routine EDA.
    ratings_small = loadCSV("ratings_small.csv")	
    print()
	
    # Run the analysis on the data already in memory.
    analyzeCSV(movies_metadata)
    print()
    analyzeCSV(credits)
    print()
    analyzeCSV(keywords)
    print()
    analyzeCSV(links)
    print()
    analyzeCSV(links_small)
    print()
    # analyzeCSV(ratings)
    print()
    analyzeCSV(ratings_small)
    print()
    analyzeMetadata(movies_metadata)
    print()
    print(f"Analysis time: {perf_counter() - file_start:.2f} seconds")

def part2Questions():
    time_start = perf_counter()
    part2Question1()
    elapsed_seconds = perf_counter() - time_start
    print(f"Processing took {elapsed_seconds:.2f} seconds.")
    print()

    time_start = perf_counter()
    part2Question2()
    elapsed_seconds = perf_counter() - time_start
    print(f"Processing took {elapsed_seconds:.2f} seconds.")
    print()

    time_start = perf_counter()
    part2Question3()
    elapsed_seconds = perf_counter() - time_start
    print(f"Processing took {elapsed_seconds:.2f} seconds.")
    print()

    time_start = perf_counter()
    part2Question4()
    elapsed_seconds = perf_counter() - time_start
    print(f"Processing took {elapsed_seconds:.2f} seconds.")
    print()

    time_start = perf_counter()
    part2Question5()
    elapsed_seconds = perf_counter() - time_start
    print(f"Processing took {elapsed_seconds:.2f} seconds.")
    print()

    time_start = perf_counter()
    part2Question6()
    elapsed_seconds = perf_counter() - time_start
    print(f"Processing took {elapsed_seconds:.2f} seconds.")
    print()

    time_start = perf_counter()
    part2Question7()
    elapsed_seconds = perf_counter() - time_start
    print(f"Processing took {elapsed_seconds:.2f} seconds.")
    print()

    time_start = perf_counter()
    part2Question8()
    elapsed_seconds = perf_counter() - time_start
    print(f"Processing took {elapsed_seconds:.2f} seconds.")
    print()

    time_start = perf_counter()
    part2Question9()
    elapsed_seconds = perf_counter() - time_start
    print(f"Processing took {elapsed_seconds:.2f} seconds.")
    print()

    time_start = perf_counter()
    part2Question10()
    elapsed_seconds = perf_counter() - time_start
    print(f"Processing took {elapsed_seconds:.2f} seconds.")
    print()


if __name__ == "__main__":
    total_start = perf_counter()
    part1EDA()
    part1Populate()
    part2Questions()
