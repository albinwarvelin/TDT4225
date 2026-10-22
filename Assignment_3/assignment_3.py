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


if __name__ == "__main__":
    total_start = perf_counter()
    part1EDA()
    part1Populate()  # Full import; enable when ready to populate MongoDB.
    print("CSV overviews count stored IDs; analyzeMetadata validates metadata IDs separately.")
