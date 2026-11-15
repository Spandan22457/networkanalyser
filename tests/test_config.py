"""Settings: SQLite default, external URL handling and safe display."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from monitor.core.config import Settings


def _settings(**overrides) -> Settings:
    """Build settings without reading a developer's real ``.env``."""

    options = {"database_url": None, **overrides}

    return Settings(_env_file=None, **options)


def test_default_is_the_sqlite_file():
    settings = _settings()

    assert settings.database_url is None
    assert settings.database_backend == "sqlite"
    assert settings.is_sqlite is True
    assert settings.sqlalchemy_url.startswith("sqlite:///")


def test_sqlite_url_can_be_supplied_explicitly():
    settings = _settings(database_url="sqlite:///C:/tmp/netscope.db")

    assert settings.is_sqlite is True
    assert settings.sqlalchemy_url == "sqlite:///C:/tmp/netscope.db"


def test_postgresql_url_is_used_verbatim():
    url = "postgresql+psycopg://netscope:secret@127.0.0.1:5432/netscope"
    settings = _settings(database_url=url)

    assert settings.sqlalchemy_url == url
    assert settings.database_backend == "postgresql"
    assert settings.is_sqlite is False


@pytest.mark.parametrize("alias", ["postgres://", "postgresql://"])
def test_bare_postgres_urls_get_the_installed_driver(alias):
    settings = _settings(database_url=f"{alias}user:pw@127.0.0.1:5432/netscope")

    assert settings.sqlalchemy_url == (
        "postgresql+psycopg://user:pw@127.0.0.1:5432/netscope"
    )


def test_blank_url_falls_back_to_sqlite():
    assert _settings(database_url="   ").is_sqlite is True


def test_url_without_a_scheme_is_rejected():
    with pytest.raises(ValidationError) as error:
        _settings(database_url="127.0.0.1:5432/netscope")

    assert "NETSCOPE_DATABASE_URL" in str(error.value)


def test_safe_url_masks_the_password():
    settings = _settings(
        database_url="postgresql+psycopg://netscope:hunter2@db.local:5432/netscope"
    )

    assert "hunter2" not in settings.safe_database_url
    assert settings.safe_database_url == (
        "postgresql+psycopg://netscope:***@db.local:5432/netscope"
    )


def test_safe_url_leaves_sqlite_untouched():
    settings = _settings()

    assert settings.safe_database_url == settings.sqlalchemy_url


def test_pool_settings_have_server_safe_defaults():
    settings = _settings()

    assert settings.db_pool_size >= 1
    assert settings.db_max_overflow >= 0
    assert settings.db_pool_recycle >= -1
