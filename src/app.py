import os
import logging
import json
import jwt
from datetime import datetime, timedelta, timezone

from app_util import get_properties_response_from_attributes, get_properties_from_attributes, compare_properties_response_from_attributes, create_rename_dict, env, Env, BACKEND_PROPERTIES_DF
from visual_analysis import prepare_distribution_graph_data, prepare_clustering_graph_data

from app_database_util import db, init_migration, User

from email_service_util import email_app

from flask_cors import CORS
from flask import Flask, render_template, request, Response, jsonify, render_template, url_for
from flask_login import LoginManager, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask_jwt_extended import JWTManager, create_access_token, create_refresh_token, jwt_required, get_jwt_identity, set_access_cookies, set_refresh_cookies, unset_jwt_cookies
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

from smtplib import SMTP

from celery import Celery


DEV_DB_FOLDER = 'database'


app = Flask(__name__,
            template_folder='../templates',
            instance_path=os.path.join(os.path.abspath(os.curdir), DEV_DB_FOLDER))
# app.config['CORS_HEADERS'] = 'Content-Type'
CORS(app, supports_credentials=True, resources={r'/api/*': {'origins': ['http://localhost']}})


FRONTEND_URL = os.environ.get('REACT_APP_FRONTEND_URL')
NGINX_URL = os.environ.get('REACT_APP_NGINX_URL')


logging_level = logging.DEBUG if env == Env.DEV else logging.INFO
app.logger.setLevel(logging_level)
app.secret_key = os.environ.get('APP_SECRET_KEY')

login_manager = LoginManager()
login_manager.init_app(app)


# Set up JWT manager for authenticating sessions.
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY')
app.config['JWT_TOKEN_LOCATION'] = ['cookies', 'headers']
app.config['JWT_COOKIE_SECURE'] = (env == Env.PROD)  # Only send cookies over https
app.config['JWT_ACCESS_COOKIE_PATH'] = '/'  # Path where cookies are valid
app.config['JWT_REFRESH_COOKIE_PATH'] = '/'  # Path where cookies are valid
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(hours=2)
app.config['JWT_COOKIE_CSRF_PROTECT'] = True  # Enable CSRF protection
app.config['JWT_COOKIE_SAMESITE'] = 'Lax'

celery_user, celery_password, celery_port = os.getenv('RABBITMQ_DEFAULT_USER'), os.getenv('RABBITMQ_DEFAULT_PASS'), os.getenv('RABBITMQ_SERVER_PORT')
app.config['CELERY_BROKER_URL'] = f'pyamqp://{celery_user}:{celery_password}@rabbitmq:{celery_port}//'
app.config['CELERY_RESULT_BACKEND'] = f'rpc://{celery_user}:{celery_password}@rabbitmq:{celery_port}//'

# Configure the database.
init_migration(app, env == Env.PROD)

# Set up Celery asynchronous task manager.
def celery_app(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery


jwtManager = JWTManager(app)

celery = celery_app(app)


#############
## UTILITY ##
#############

def fancy_flash(message, status='info', flash_id='default', animation=None):
    '''
        A message based flash message with the following funcitonality:
        - Regular flash functionality, i.e. message and message category.
        - Multiple flash messages per html via area.
        - Custom animation types.
    '''
    return {
        'fancy_flash': [{
            'message': message,
            'status': status,
            'flash_id': flash_id,
            'animation': animation
        }]
    }


#####################
## USER MANAGEMENT ##
#####################

@login_manager.user_loader
def load_user(user_email):
    return User.query.filter_by(email=user_email).first()

def maybe_load_user(user_email):
    user_obj = None
    if user_email == 'anonymous':
        app.logger.info('Anonymous user detected')
    elif user_email:
        app.logger.info('User is authenticated, skipping CSRF header validation.')
        user_obj = load_user(user_email)
    return user_obj


#########################
## APP MAILING UTILITY ##
#########################

def get_external_url(endpoint, **values):
    return NGINX_URL + url_for(endpoint, **values)

def generate_token(data, salt='generic-salt', expiration=3600):
    ''' Generate a secure token for a given data with a salt and expiration time. '''
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    return serializer.dumps(data, salt=salt)

def verify_token(token, salt='generic-salt', expiration=3600):
    ''' Verify a token and return the data if valid; otherwise, return None. '''
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    try:
        data = serializer.loads(token, salt=salt, max_age=expiration)
        return data
    except (SignatureExpired, BadSignature):
        return None

@celery.task(bind=True, retry_backoff=True, max_retries=3)
def send_async_email(self, email_data):
    ''' Background task to send an email using the provided email service. '''
    try:
        # Ensure a fresh connection for each email
        with SMTP(email_app.smtp_server, email_app.smtp_port) as server:
            if email_app.use_tls:
                server.starttls()
            server.login(email_app.sender_email, email_app.password)
            # Use the server object for sending the email
            if email_app.send_email(server, email_data['recipient'], email_data['subject'], email_data['body'], email_data['html']):
                app.logger.info('Email sent successfully.')
            else:
                raise Exception('Failed to send email')
    except Exception as e:
        app.logger.error(f'Failed to send email: {str(e)}')
        self.retry(exc=e)

def send_email_with_message(user_email, redirect_url, email_subject, email_template, email_body):
    service_name = os.getenv('SERVICE_NAME')
    body = render_template(email_body, redirect_url=redirect_url, user_email=user_email, service_name=service_name)
    html = render_template(email_template, redirect_url=redirect_url, user_email=user_email, service_name=service_name)
    
    # Generate the email, and send it.
    email = email_app.make_email(user_email, email_subject, body, html)
    send_async_email.delay(email)
    app.logger.info(f'Email task queued for: {user_email}')

def send_email_verification_email(user_email):
    token = generate_token(user_email, salt='email-verification-salt', expiration=3600)
    # redirect_url = get_external_url('email_verification', token=token)
    redirect_url = f'{FRONTEND_URL}/email/verify/{token}'
    send_email_with_message(user_email, redirect_url,
                            'Confirm Your Email',
                            'email_verification/verify-email.html', 'email_verification/verify-email.txt')

def send_password_reset_email(user_email):
    token = generate_token(user_email, salt='password-reset-salt', expiration=1800)
    redirect_url = f'{FRONTEND_URL}/password/set-new/{token}'
    send_email_with_message(user_email, redirect_url,
                            'Set New Password',
                            'reset_password/reset-password.html', 'reset_password/reset-password.txt')


####################
## LISTING ROUTES ##
####################

@app.route('/api/test', methods=['GET'])
def test_route():
    return fancy_flash('Hello from the backend!', 'success', 'test', 'fadeIn'), 200

@app.route('/api/explore', methods=['POST'])
@jwt_required()
def explore():
    # Retrieve the user identity if the session is authenticated.
    user_email = get_jwt_identity()
    user_obj = maybe_load_user(user_email)

    request_data = request.get_json()
    
    #Filter properties by requested user saved properties.
    is_saved = bool(request_data.get('is_saved', False))
    saved_ids = set(user_obj.saved) if user_obj else set()
    filter_by_ids = saved_ids if is_saved else set()

    response_data = get_properties_response_from_attributes(request_data, filter_by_ids=filter_by_ids, saved_ids=saved_ids)
    if user_obj:
        response_data['descriptions']['Save'] = 'Save/unsave this property to go back to it later.'
    else:
        response_data['descriptions']['Save'] = 'To save a property you must first login.'

    return Response(json.dumps(response_data), mimetype='application/json')

@app.route('/api/toggle-save', methods=['POST'])
@jwt_required()
def toggle_save():
    user_email = get_jwt_identity()
    user_obj = maybe_load_user(user_email)

    data = request.get_json()
    property_id = data.get('propertyId')
    if property_id in user_obj.saved:
        user_obj.saved.remove(property_id)
        saved = False
    else:
        user_obj.saved.add(property_id)
        saved = True
    return jsonify({'success': True, 'saved': saved})

@app.route('/api/compare', methods=['POST'])
@jwt_required()
def compare():
    # Retrieve the user identity if the session is authenticated.
    user_email = get_jwt_identity()
    user_obj = maybe_load_user(user_email)

    request_data = request.get_json()

    response_data = compare_properties_response_from_attributes(request_data)
    aggregates = response_data.groupby('list_id').agg({
        'purchase_price': 'sum',
        'monthly_costs': 'sum',
        'cash_invested': 'sum',
        'monthly_restimate': 'sum'
    }).reset_index()

    return Response(aggregates.to_json(), mimetype='application/json')


#####################
## GRAPHING ROUTES ##
#####################

@app.route('/api/distribution_graph_data', methods=['POST'])
@jwt_required()
def get_distribution_graph_data():
    user_email = get_jwt_identity()
    user_obj = maybe_load_user(user_email)

    request_data = request.get_json()

    is_saved = bool(request_data.get('is_saved', False))
    saved_ids = set(user_obj.saved) if user_obj else set()
    filter_by_ids = saved_ids if is_saved else set()

    use_filtered_data = request_data.get('useFilteredData', False)

    if use_filtered_data:
        properties_df, _ = get_properties_from_attributes(
            request_data,
            calculate_series_metrics=False,
            filter_by_ids=filter_by_ids
        )
        properties_df.rename(columns=create_rename_dict(), inplace=True)
    else:
        properties_df = BACKEND_PROPERTIES_DF.copy()
        properties_df.rename(columns=create_rename_dict(), inplace=True)

    aggregates = request_data.get('aggregates', [])
    visualize_options = request_data.get('visualizeOptions', ['Price'])
    bins = int(request_data.get('bins', 30))
    property_data = request_data.get('propertyData', {})

    if not visualize_options:
        return jsonify({"error": "You need to specify something to visualize by..."}), 400

    data = prepare_distribution_graph_data(properties_df, aggregates, visualize_options, bins, property_data)
    return jsonify(data)

@app.route('/api/clustering_graph_data', methods=['POST'])
@jwt_required()
def get_clustering_graph_data():
    user_email = get_jwt_identity()
    user_obj = maybe_load_user(user_email)

    request_data = request.get_json()

    is_saved = bool(request_data.get('is_saved', False))
    saved_ids = set(user_obj.saved) if user_obj else set()
    filter_by_ids = saved_ids if is_saved else set()

    use_filtered_data = request_data.get('useFilteredData', False)
    property_data = request_data.get('propertyData', {})

    if use_filtered_data:
        properties_df, _ = get_properties_from_attributes(
            request_data,
            calculate_series_metrics=False,
            filter_by_ids=filter_by_ids
        )
        properties_df.rename(columns=create_rename_dict(), inplace=True)
    else:
        properties_df = BACKEND_PROPERTIES_DF.copy()
        properties_df.rename(columns=create_rename_dict(), inplace=True)

    app.logger.info("properties df: ", properties_df, properties_df.shape)
    app.logger.info("proeprties df columns: ", list(properties_df.columns))

    # Prepare data to send to the frontend
    result = prepare_clustering_graph_data(properties_df)

    app.logger.info("result: ", result)

    return jsonify(result)


###########################
## AUTHENTICATION ROUTES ##
###########################

def session_data(csrf_access_token, csrf_refresh_token=None):
    session_data_key = 'session_data'
    session_data = {
        session_data_key: {
            'session_info': session_info(isAnonymous=not bool(csrf_refresh_token)),
            'csrf_access_token': csrf_access_token
        }
    }
    if csrf_refresh_token:
        session_data[session_data_key]['csrf_refresh_token'] = csrf_refresh_token
    return session_data

def session_info(isAnonymous=True):
    access_exp = datetime.now(timezone.utc) + app.config['JWT_ACCESS_TOKEN_EXPIRES']

    session_info = {
        'status': 'anonymous' if isAnonymous else 'authenticated',
        'access_expires': access_exp.isoformat()
    }
    if not isAnonymous:
        refresh_exp = datetime.now(timezone.utc) + app.config['JWT_REFRESH_TOKEN_EXPIRES']
        session_info['refresh_expires'] = refresh_exp.isoformat()
    return session_info

def clear_jwts(response):
    '''
        Utility function to clear JWT cookies (access and refresh).
        Takes a Flask response object and unsets the JWT cookies.
    '''
    unset_jwt_cookies(response)
    return response

def get_csrf_token_from_jwt(jwt_token):
    '''
        Manually extract the csrf token from the jwt access token to re-use it.
    '''
    decoded_token = jwt.decode(jwt_token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
    return decoded_token['csrf']

# Generate anonymous CSRF token
@app.route('/api/start-anon-session', methods=['GET'])
def start_anonymous_session():
    # Create a JWT with anonymous user claims or identity
    access_token = create_access_token(identity='anonymous', additional_claims={'role': 'anonymous'})
    csrf_access_token = get_csrf_token_from_jwt(access_token)

    response = jsonify({
        **session_data(csrf_access_token)
    })
    # Clear authenticated cookie JWTs.
    clear_jwts(response)
    # Set and override JWT/Csrfs.
    set_access_cookies(response, access_token)
    response.set_cookie('csrf_access_token', csrf_access_token, httponly=True)

    return response

@app.route('/api/start-auth-session', methods=['POST'])
def start_authenticated_session():
    '''
        Endpoint to start an authenticated session (login), given a set of credentials:
        - user_email: Email associated with an account.
        - user_password: Password associated with the given user_email.
    '''
    app.logger.info('New request just came in.')
    data = request.get_json()
    user_email, user_password = data.get('user_email'), data.get('user_password')

    # Check if input credentials are incorrect or unverified.
    app.logger.info(f"Trying to fetch: {user_email} from the backend...")
    user = User.query.filter_by(email=user_email).first()
    app.logger.info(f"User requested is: {user}")
    if not user or not check_password_hash(user.password, user_password):
        return fancy_flash('Invalid username or password.', 'error', 'login', 'shake'), 200
    if not user.confirmed:
        return fancy_flash('Please verify your email.', 'error', 'login', 'shake'), 200

    app.logger.info(f"{user}: is a valid user!")
    access_token, refresh_token = create_access_token(identity=user_email), create_refresh_token(identity=user_email)
    csrf_access_token, csrf_refresh_token = get_csrf_token_from_jwt(access_token), get_csrf_token_from_jwt(refresh_token)

    response = jsonify({
        **session_data(csrf_access_token, csrf_refresh_token=csrf_refresh_token),
        **fancy_flash('Logging in!', 'success', 'login', 'fadeIn')
    })
    # Clear anonymous cookie JWTs.
    clear_jwts(response)
    # Set and override JWT/Csrfs.
    set_access_cookies(response, access_token)
    response.set_cookie('csrf_access_token', csrf_access_token, httponly=True)
    set_refresh_cookies(response, refresh_token)
    response.set_cookie('csrf_refresh_token', csrf_refresh_token, httponly=True)
    app.logger.info(f'Auth response is: {response}')
    return response, 200

@app.route('/api/refresh-auth-session', methods=['POST'])
@jwt_required(refresh=True)
def refresh_authenticated_session():
    try:
        current_user = get_jwt_identity()
        access_token = create_access_token(identity=current_user)
        csrf_access_token = get_csrf_token_from_jwt(access_token)
        response = jsonify({
            **session_data(csrf_access_token)
        })
        # Set and override JWT/Csrfs.
        set_access_cookies(response, access_token)
        response.set_cookie('csrf_access_token', csrf_access_token, httponly=True)
        return response, 200
    except Exception as e:
        response = jsonify({'msg': 'Failed to refresh token'})
        return clear_jwts(response), 401

@app.route('/api/clean-session', methods=['POST'])
def clean_session():
    response = jsonify({'msg': 'Logout successful'})
    return clear_jwts(response)


#################
## USER ROUTES ##
#################

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def profile():
    user_email = get_jwt_identity()
    app.logger.info(f'User email is: {user_email}')
    user = User.query.filter_by(email=user_email).first()
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    app.logger.info(f'User info isss: {user}.')
    user_info = {
        'email': user_email,
        'first_name': user.first_name,  # Directly access the first_name
        'last_name': user.last_name,    # Directly access the last_name
        'saved': list(user.saved) if user.saved else []  # Make sure to handle bytea or None correctly
    }
    return jsonify(user_info)

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    user_email = data.get('userEmail')

    app.logger.info(f"Registering user email: {user_email}")
    # Check if email already exists.
    if User.query.filter_by(email=user_email).first():
        return jsonify(fancy_flash('Email already registered.', 'error', 'register', 'shake')), 200

    # Add new user to the database.
    new_user = User(
        email=user_email,
        first_name=data.get('firstName'),
        last_name=data.get('lastName'),
        password=generate_password_hash(data.get('userPassword')),
        is_professional=data.get('isProfessional'),
        confirmed=False,
        saved=set()
    )
    app.logger.info(f"Adding user to db: {new_user}")
    db.session.add(new_user)
    db.session.commit()

    # Send confirmation email
    send_email_verification_email(user_email)
    return jsonify(fancy_flash('Please confirm your email address.', 'success', 'register', 'fadeIn')), 200

@app.route('/api/delete-account', methods=['DELETE'])
@jwt_required()
def delete_account():
    user_email = get_jwt_identity()
    user_obj = maybe_load_user(user_email)

    if not user_obj:
        return jsonify(fancy_flash('User not found.', 'error', 'delete-account', 'shake')), 404

    # Remove user from the database instead of in-memory dictionary
    db.session.delete(user_obj)
    db.session.commit()
    
    response = jsonify(fancy_flash('Your account has been successfully deleted.', 'success', 'delete-account', 'fadeIn'))
    return clear_jwts(response), 200

@app.route('/api/email/verify/<token>', methods=['POST'])
def email_verification(token):
    user_email = verify_token(token, salt='email-verification-salt', expiration=3600)
    if user_email:
        app.logger.info(f'We have decoded the email: {user_email}, its type is: {type(token)}')
        user_obj = maybe_load_user(user_email)
        if user_obj:
            user_obj.confirmed = True  # Update confirmed status
            db.session.commit()  # Commit changes to the database
            return jsonify(fancy_flash('Email confirmed.', 'success', 'email-verify', 'fadeIn')), 200
    return jsonify(fancy_flash('Unable to locate user associated with the given email address.', 'error', 'email-verify', 'shake')), 200

@app.route('/api/password/request-new', methods=['POST'])
def reset_password():
    data = request.get_json()
    user_email = data.get('userEmail')
    user_obj = maybe_load_user(user_email)\

    if user_obj:
        app.logger.info(f'Reset password email is: {user_email}.')
        send_password_reset_email(user_email)
        return jsonify(fancy_flash('A password reset link has been sent to your email.', 'success', 'password-request-new', 'fadeIn')), 200
    else:
        return jsonify(fancy_flash('No account found with that email address.', 'error', 'password-request-new', 'shake')), 200

@app.route('/api/password/set-new/<token>', methods=['POST'])
def set_new_password(token):
    try:
        app.logger.info(f'Tokenizing: {token}, with type: {type(token)}')
        user_email = verify_token(token, salt='password-reset-salt', expiration=1800)
        app.logger.info(f'Password set new tokenized user: {user_email}')
        if not user_email:
            return jsonify(fancy_flash('No user email from the autodirected token.', 'error', 'password-set-new', 'shake')), 200

        user_obj = maybe_load_user(user_email)
        if not user_obj:
            return jsonify(fancy_flash('No user associated with the given email.', 'error', 'password-set-new', 'shake')), 200

        new_password = request.get_json()['new_password']
        user_obj.password = generate_password_hash(new_password)
        db.session.commit()
        return jsonify(fancy_flash('Your password has been updated.', 'success', 'password-set-new', 'fadeIn')), 200
    except (SignatureExpired, BadSignature):
        return jsonify(fancy_flash('The reset link is invalid or has expired.', 'error', 'password-set-new', 'shake')), 200
    except KeyError:
        return jsonify(fancy_flash('Invalid data received.', 'error', 'password-set-new', 'shake')), 200

@app.route('/api/report/app-issue', methods=['POST'])
def report():
    request_data = request.get_json()
    user_email = request_data.get('user_email', '')
    issue_description = request_data.get('issue_description', '')

    return jsonify(fancy_flash(f"You have reported the issue: '{issue_description[:10]}...'.", 'success', 'report', 'fadeIn')), 200



if __name__ == '__main__':
    app.run(debug=True)
