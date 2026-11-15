from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    # Boleh kosong dulu; akan dipakai mulai langkah 0.4
    database_url: str = ""
    test_database_url: str = ""

    # .env berada di root proyek, satu level di atas folder backend/
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    session_cookie_name: str = "fintrace_session"
    session_ttl_days: int = 7

    @property
    def cookie_secure(self) -> bool:
        """Cookie hanya dikirim lewat HTTPS di luar mode development."""
        return self.app_env != "development"

settings = Settings()