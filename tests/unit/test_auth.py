"""Unit tests for the authentication providers and config validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from zvec_server.auth.provider import (
    ApiKeyAuthProvider,
    DisabledAuthProvider,
    build_auth_provider,
)
from zvec_server.config import Settings
from zvec_server.errors import AuthenticationError


def test_disabled_provider_allows_anything() -> None:
    provider = DisabledAuthProvider()
    assert provider.enabled is False
    # Must not raise regardless of what (if anything) the client sent.
    provider.authenticate(None)
    provider.authenticate("Bearer whatever")


def test_api_key_provider_accepts_valid_key() -> None:
    provider = ApiKeyAuthProvider("s3cret")
    assert provider.enabled is True
    provider.authenticate("Bearer s3cret")  # no raise


def test_api_key_provider_scheme_is_case_insensitive() -> None:
    ApiKeyAuthProvider("s3cret").authenticate("bearer s3cret")


def test_api_key_provider_tolerates_extra_whitespace() -> None:
    ApiKeyAuthProvider("s3cret").authenticate("Bearer   s3cret  ")


@pytest.mark.parametrize(
    "header",
    [
        None,  # no header at all
        "",  # empty header
        "s3cret",  # missing scheme
        "Basic s3cret",  # wrong scheme
        "Bearer",  # scheme but no token
        "Bearer ",  # scheme but blank token
        "Bearer wrong",  # valid shape, wrong key
    ],
)
def test_api_key_provider_rejects_bad_credentials(header: str | None) -> None:
    provider = ApiKeyAuthProvider("s3cret")
    with pytest.raises(AuthenticationError):
        provider.authenticate(header)


def test_api_key_provider_requires_non_empty_key() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        ApiKeyAuthProvider("")


def test_build_provider_returns_disabled_when_off() -> None:
    provider = build_auth_provider(Settings(auth_enabled=False))
    assert isinstance(provider, DisabledAuthProvider)


def test_build_provider_returns_api_key_when_on() -> None:
    provider = build_auth_provider(Settings(auth_enabled=True, api_key="k"))
    assert isinstance(provider, ApiKeyAuthProvider)


def test_settings_requires_key_when_auth_enabled() -> None:
    with pytest.raises(ValidationError):
        Settings(auth_enabled=True)


def test_settings_rejects_blank_key_when_auth_enabled() -> None:
    with pytest.raises(ValidationError):
        Settings(auth_enabled=True, api_key="   ")
