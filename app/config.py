"""Application configuration loaded from environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"
    secret_key: str = "change-me"
    base_url: str = "http://localhost:8000"
    timezone: str = "Asia/Kolkata"

    # Database
    database_url: str = "sqlite:///./app/data/metfraa.db"

    # Microsoft 365 / Azure AD
    ms_client_id: str = ""
    ms_client_secret: str = ""
    ms_tenant_id: str = ""
    ms_redirect_uri: str = "http://localhost:8000/auth/callback"

    # OneDrive
    onedrive_folder: str = "KPI_Tracker"
    onedrive_user_email: str = "info@metfraa.com"

    # SMTP
    smtp_host: str = "smtp.office365.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "info@metfraa.com"
    smtp_from_name: str = "Metfraa KPI Tracker"

    # Reminder schedule
    daily_reminder_time: str = "20:30"
    missed_day_alert_time: str = "09:00"


@lru_cache
def get_settings() -> Settings:
    return Settings()
