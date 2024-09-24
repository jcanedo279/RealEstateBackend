import os
from app import app
from app_database_util import transfer_users_to_db

# Initialize the app and database in a standalone context
def seed_users():
    with app.app_context():
        transfer_users_to_db()

if __name__ == "__main__":
    print("Seeding users into the database...")
    seed_users()
    print("User seeding complete.")
