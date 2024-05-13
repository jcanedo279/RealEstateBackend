import os
from enum import Enum

from app_util import env, Env

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib


EMAIL_SERVICE = os.getenv('MAIL_SERVICE')
class EmailService(Enum):
    GMAIL = 1
    OFFICE365 = 2

def get_mail_config(service: EmailService) -> dict:
    """
    Retrieves mail configuration based on the specified email service.

    Args:
        service: The EmailService enum value indicating the service to use.

    Returns:
        A dictionary containing the mail configuration details.
    """

    config = dict()
    config['MAIL_DEBUG'] = (env != Env.PROD)
    if service == EmailService.GMAIL:
        config['MAIL_SERVER'] = os.getenv('GMAIL_MAIL_SERVER')
        config['MAIL_USERNAME'] = os.getenv('GMAIL_MAIL_USERNAME')
        config['MAIL_PASSWORD'] = os.getenv('GMAIL_MAIL_APP_PASSWORD')  # Use app password
    elif service == EmailService.OFFICE365:
        config['MAIL_SERVER'] = os.getenv('OFFICE_MAIN_SERVER')
        config['MAIL_USERNAME'] = os.getenv('OFFICE_MAIL_USERNAME')
        config['MAIL_PASSWORD'] = os.getenv('OFFICE_MAIL_PASSWORD')
    else:
        raise ValueError(f"Unsupported email service: {service}")

    config['MAIL_PORT'] = 587
    config['MAIL_USE_TLS'] = True
    config['MAIL_USE_SSL'] = False

    return config

email_service = EmailService.GMAIL if EMAIL_SERVICE == "GMAIL" else EmailService.OFFICE365

class EmailApp:
    def __init__(self, config):
        self.mail_config = config
        self.sender_email = config['MAIL_USERNAME']
        self.smtp_server = config['MAIL_SERVER']
        self.smtp_port = config['MAIL_PORT']
        self.use_tls = config['MAIL_USE_TLS']
        self.use_ssl = config['MAIL_USE_SSL']
        self.password = config['MAIL_PASSWORD']

    def make_email(self, user_email, email_subject, body, html):
        return {
            'subject': email_subject,
            'sender': self.mail_config['MAIL_USERNAME'],
            'recipient': user_email,
            'body': body,
            'html': html
        }

    def send_email(self, server, recipient_email, subject, body, html):
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = self.sender_email
        message["To"] = recipient_email

        # Add body parts to the message
        part1 = MIMEText(body, "plain")
        part2 = MIMEText(html, "html")
        message.attach(part1)
        message.attach(part2)

        try:
            server.sendmail(self.sender_email, recipient_email, message.as_string())
            return True
        except smtplib.SMTPException as e:
            # Handle specific exception types here (e.g., connection errors, authentication errors)
            raise e

email_service = EmailService.GMAIL if os.getenv('MAIL_SERVICE') == "GMAIL" else EmailService.OFFICE365
email_config = get_mail_config(email_service)
email_app = EmailApp(email_config)
