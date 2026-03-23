import os
from pathlib import Path

from dotenv import load_dotenv


def _load_environment_file():
    """Optionally load local .env for developer convenience.

    Values already present in the real process environment always win because
    dotenv is loaded with override=False.
    """
    current_file = Path(__file__).resolve()
    scraper_root = current_file.parents[2]  # .../scraper
    project_root = current_file.parents[3]  # .../SeekSpider_Waleed

    candidate_paths = [
        Path.cwd() / '.env',
        scraper_root / '.env',
        project_root / '.env',
    ]

    seen = set()
    for env_path in candidate_paths:
        resolved = env_path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)

        if env_path.is_file():
            load_dotenv(dotenv_path=env_path, override=False)
            return str(env_path)

    return None


def _get_first_env(*names):
    """Return the first non-empty environment variable value from names."""
    for name in names:
        value = os.getenv(name)
        if value is not None:
            value = value.strip()
            if value:
                return value
    return None


class Config:
    def __init__(self):
        self.ENV_FILE_PATH = _load_environment_file()

        # Canonical env contract shared with API.
        self.DATABASE_ENGINE = (_get_first_env('DATABASE_ENGINE') or '').lower()

        # Canonical first, then aliases for backward compatibility.
        self.DATABASE_TABLE = _get_first_env(
            'DATABASE_TABLE',
            'POSTGRESQL_TABLE',
            'POSTGRES_TABLE',
        )

        # PostgreSQL canonical names with alias support.
        self.POSTGRESQL_HOST = _get_first_env('POSTGRESQL_HOST', 'POSTGRES_HOST')
        self.POSTGRESQL_PORT_RAW = _get_first_env('POSTGRESQL_PORT', 'POSTGRES_PORT')
        self.POSTGRESQL_PORT = self._safe_int(self.POSTGRESQL_PORT_RAW)
        self.POSTGRESQL_USER = _get_first_env('POSTGRESQL_USER', 'POSTGRES_USER')
        self.POSTGRESQL_PASSWORD = _get_first_env('POSTGRESQL_PASSWORD', 'POSTGRES_PASSWORD')
        self.POSTGRESQL_DATABASE = _get_first_env('POSTGRESQL_DATABASE', 'POSTGRES_DB')
        self.POSTGRESQL_TABLE = self.DATABASE_TABLE

        self.SQLITE_DB_PATH = _get_first_env('SQLITE_DB_PATH')

    @staticmethod
    def _safe_int(value):
        if value in (None, ''):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


    def validate(self):
        """Validate startup configuration and fail fast with actionable guidance."""
        errors = []

        if not self.DATABASE_ENGINE:
            errors.append(
                'DATABASE_ENGINE is required and must be one of: postgres, sqlite'
            )
        elif self.DATABASE_ENGINE not in {'postgres', 'sqlite'}:
            errors.append(
                f'DATABASE_ENGINE="{self.DATABASE_ENGINE}" is invalid; use "postgres" or "sqlite"'
            )

        if self.DATABASE_ENGINE == 'sqlite':
            if not self.SQLITE_DB_PATH:
                errors.append('SQLITE_DB_PATH is required when DATABASE_ENGINE=sqlite')
            if not self.DATABASE_TABLE:
                errors.append('DATABASE_TABLE is required when DATABASE_ENGINE=sqlite')

        if self.DATABASE_ENGINE == 'postgres':
            if not self.POSTGRESQL_HOST:
                errors.append('POSTGRESQL_HOST (or POSTGRES_HOST alias) is required when DATABASE_ENGINE=postgres')
            if not self.POSTGRESQL_PORT_RAW:
                errors.append('POSTGRESQL_PORT (or POSTGRES_PORT alias) is required when DATABASE_ENGINE=postgres')
            elif self.POSTGRESQL_PORT is None:
                errors.append(
                    f'POSTGRESQL_PORT must be an integer; got "{self.POSTGRESQL_PORT_RAW}"'
                )
            if not self.POSTGRESQL_USER:
                errors.append('POSTGRESQL_USER (or POSTGRES_USER alias) is required when DATABASE_ENGINE=postgres')
            if not self.POSTGRESQL_PASSWORD:
                errors.append('POSTGRESQL_PASSWORD (or POSTGRES_PASSWORD alias) is required when DATABASE_ENGINE=postgres')
            if not self.POSTGRESQL_DATABASE:
                errors.append('POSTGRESQL_DATABASE (or POSTGRES_DB alias) is required when DATABASE_ENGINE=postgres')
            if not self.DATABASE_TABLE:
                errors.append('DATABASE_TABLE (or POSTGRESQL_TABLE/POSTGRES_TABLE alias) is required when DATABASE_ENGINE=postgres')

        if errors:
            raise ValueError('Invalid scraper configuration:\n- ' + '\n- '.join(errors))


config = Config()
config.validate()
