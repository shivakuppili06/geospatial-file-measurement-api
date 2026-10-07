from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./geo_files.db"
    max_upload_size_mb: int = 25
    allowed_extensions: tuple[str, ...] = (".zip", ".kml")
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="GEOAPI_")


settings = Settings()
