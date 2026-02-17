import os

DEBUG = os.environ.get("DEBUG", "False").strip().lower() in ["true", "on", "1"]
APP_ENV = os.environ.get("APP_ENV", "local").strip().lower()
