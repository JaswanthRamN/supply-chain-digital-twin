from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Supply Chain Digital Twin"
    database_url: str = "sqlite:///./supply_chain.db"
    simulation_seed: int = 42
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
