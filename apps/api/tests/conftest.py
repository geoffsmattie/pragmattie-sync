import os

# Tests run against SQLite so they need no MySQL server.
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
