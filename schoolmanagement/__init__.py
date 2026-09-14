from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
import os
from flask_login import LoginManager
from flask_migrate import Migrate
from dotenv import load_dotenv
load_dotenv()


# Define explicit naming convention layout keys for the database 
convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}
# Pass the custom metadata structure layout to SQLAlchemy
metadata = MetaData(naming_convention=convention)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET")
ENV_DB_URL = os.getenv('DATABASE_URL')
if ENV_DB_URL:
    if ENV_DB_URL.startswith("postgres://"):
        ENV_DB_URL = ENV_DB_URL.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = ENV_DB_URL
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///school.db'


app.config['SQLALCHEMY_TRACK_MODIFICATIONS']=False
app.config['SQLALCHEMY_METADATA'] = metadata
db = SQLAlchemy(app)
migrate=Migrate(app,db)

app.config['MAIL_SERVER']='smtp.gmail.com'
app.config['MAIL_PORT']=587
app.config['MAIL_USE_TLS']=True
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")

login_manager = LoginManager(app)
login_manager.login_view = 'login'  # If unauthenticated users access protected spaces, send them here
login_manager.login_message_category = 'info'

mail=Mail(app)
serializer=URLSafeTimedSerializer(app.config['SECRET_KEY'])

from schoolmanagement import models
from schoolmanagement import routes

