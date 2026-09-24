from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SEED_PATH = Path(__file__).resolve().parent.parent.parent / "seed" / "style_cards.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str = "TEST:TOKEN"
    max_access_token: str = ""
    max_api_base: str = "https://platform-api2.max.ru"
    messengers: str = "telegram"
    database_url: str = "postgresql+asyncpg://bot:bot@localhost:5432/bot_game_book"
    llm_api_base: str = "https://api.openai.com/v1"
    llm_api_key: str = "sk-test"
    llm_model: str = "gpt-4o-mini"
    admin_usernames: str = ""
    seed_path: Path = SEED_PATH

    @property
    def messenger_list(self) -> list[str]:
        return [m.strip().lower() for m in self.messengers.split(",") if m.strip()]

    @property
    def admin_username_set(self) -> set[str]:
        return {
            u.strip().lstrip("@").lower()
            for u in self.admin_usernames.split(",")
            if u.strip()
        }


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
