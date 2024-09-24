import os

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash


PORT_DATABASE = os.environ.get('PORT_DATABASE')
DATABASE_CONTAINER_NAME, DATABASE_NAME = os.environ.get('DATABASE_CONTAINER_NAME'), os.environ.get('DATABASE_NAME')
POSTGRES_USER, POSTGRES_PASSWORD = os.environ.get('POSTGRES_USER'), os.environ.get('POSTGRES_PASSWORD')

# Initialize SQLAlchemy and Migrate
db = SQLAlchemy()
migrate = Migrate()


users = {
    'test@gmail.com': {
        'id': 1,
        'name': ('Test', 'Name'),
        'password': generate_password_hash('pass'),
        'is_professional': True,
        'confirmed': True,
        'saved': {2054668176, 125785286, 2054529325},
    },
    'unverified@gmail.com': {
        'id': 2,
        'name': ('Unverified', 'Name'),
        'password': generate_password_hash('pass'),
        'is_professional': False,
        'confirmed': False,
        'saved': {},
    }
}

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)  # Store hashed passwords
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    is_professional = db.Column(db.Boolean, default=False)
    confirmed = db.Column(db.Boolean, default=False)
    saved = db.Column(db.PickleType, default=set)  # Can store set of IDs


def init_migration(app, is_prod):
    """Initialize the database and migration objects for the given app."""

    prod_db_uri = f'postgresql://<PROD_DB_USER>:<PROD_DB_PASSWORD>@<PROD_DB_HOST>:<PROD_DB_PORT>/<PROD_DB_NAME>'
    dev_db_uri = f'postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{DATABASE_CONTAINER_NAME}:{PORT_DATABASE}/{DATABASE_NAME}'
    app.config['SQLALCHEMY_DATABASE_URI'] = prod_db_uri if is_prod else dev_db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    migrate.init_app(app, db)


# Function to transfer in-memory users to the database.
def transfer_users_to_db():
    for email, user_data in users.items():
        # Check if user already exists in the database
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            print(f"User {email} already exists in the database. Skipping.")
            continue

        # Create a new User object
        new_user = User(
            email=email,
            first_name=user_data['name'][0],
            last_name=user_data['name'][1],
            password=user_data['password'],
            is_professional=user_data['is_professional'],
            confirmed=user_data['confirmed'],
            saved=user_data['saved']
        )

        db.session.add(new_user)

    db.session.commit()
    print("All users have been transferred to the database.")
