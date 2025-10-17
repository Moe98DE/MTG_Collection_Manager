# This script is responsible for creating the database and its tables.
# It should be run once before the main application or tests are run for the first time.
from core.models import Base, engine


def create_database_schema():
    """
    Connects to the database defined in models.py and creates all tables
    that inherit from the Base declarative base.
    """
    print("Attempting to create database tables...")
    try:
        # The 'create_all' method inspects all classes that inherit from Base
        # and issues CREATE TABLE statements for them.
        Base.metadata.create_all(bind=engine)
        print("Tables created successfully (if they didn't already exist).")
    except Exception as e:
        print(f"An error occurred during table creation: {e}")

if __name__ == '__main__':
    # This allows the script to be run directly from the command line
    # e.g., python -m your_package_name.database_setup
    create_database_schema()