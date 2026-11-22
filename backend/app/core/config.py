from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = ""
    test_database_url: str = ""

    session_cookie_name: str = "fintrace_session"
    csrf_cookie_name: str = "fintrace_csrf"
    session_ttl_days: int = 7

    login_window_minutes: int = 15
    login_max_failures_per_account_ip: int = 5
    login_max_failures_per_ip: int = 20

    secret_key: str = ""
    # Daftar origin yang boleh mengirim request pengubah data, dipisah koma
    allowed_origins: str = (
        "http://127.0.0.1:8000,http://localhost:8000,"
        "http://127.0.0.1:3000,http://localhost:3000"
    )

    # .env berada di root proyek, satu level di atas folder backend/
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    @property
    def cookie_secure(self) -> bool:
        """Cookie hanya dikirim lewat HTTPS di luar mode development."""
        return self.app_env != "development"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def check_secret_key(self) -> Self:
        if len(self.secret_key) < 32 or self.secret_key.startswith(
            "ganti_dengan"
        ):
            raise ValueError(
                "SECRET_KEY wajib diisi dengan string acak minimal 32 karakter"
            )
        return self


settings = Settings()