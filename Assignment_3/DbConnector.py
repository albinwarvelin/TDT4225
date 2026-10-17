import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient


class DbConnector:
    """
    Connects to MongoDB using the repository's .env settings.
    Constructor arguments can override the settings when needed.
    """

    def __init__(self,
                 DATABASE=None,
                 HOST=None,
                 USER=None,
                 PASSWORD=None,
                 PORT=None):
        # Resolve .env from this file, regardless of the terminal's directory.
        env_path = Path(__file__).resolve().parent.parent / ".env"
        load_dotenv(env_path)

        DATABASE = DATABASE if DATABASE is not None else os.getenv("MONGO_DATABASE", "movies")
        HOST = HOST if HOST is not None else os.getenv("MONGO_HOST", "127.0.0.1")
        USER = USER if USER is not None else os.getenv("MONGO_USER", "movies_user")
        PASSWORD = PASSWORD if PASSWORD is not None else os.getenv("MONGO_PASSWORD")
        PORT = int(PORT if PORT is not None else os.getenv("MONGO_PORT", "27018"))

        if not PASSWORD:
            raise ValueError("Set MONGO_PASSWORD in the repository root .env file.")

        # Separate credentials avoid URI escaping problems with special characters.
        self.client = MongoClient(
            host=HOST,
            port=PORT,
            username=USER,
            password=PASSWORD,
            authSource=DATABASE,
            serverSelectionTimeoutMS=5000,
        )
        try:
            # MongoClient connects lazily; ping verifies the connection now.
            self.client.admin.command("ping")
            self.db = self.client[DATABASE]
        except Exception:
            self.client.close()
            raise

        print("You are connected to the database:", self.db.name)
        print("-----------------------------------------------\n")

    def close_connection(self):
        self.client.close()
        print("\n-----------------------------------------------")
        print("Connection to %s-db is closed" % self.db.name)
