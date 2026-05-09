import os
from pathlib import Path

import pytest

from flexsearch import config as cfg


def write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(body)
    return p


def test_load_basic(tmp_path):
    p = write(tmp_path, """
default_profile: local
profiles:
  local:
    url: https://localhost:9002
    user: admin
    password_env: HAC_LOCAL_PASS
    verify_ssl: false
""")
    c = cfg.load(p)
    assert c.default_profile == "local"
    prof = c.resolve()
    assert prof.url == "https://localhost:9002"
    assert prof.verify_ssl is False
    assert prof.user == "admin"


def test_resolve_unknown(tmp_path):
    p = write(tmp_path, """
profiles:
  local:
    url: https://x
""")
    c = cfg.load(p)
    with pytest.raises(cfg.ConfigError):
        c.resolve("missing")


def test_password_env_unset(tmp_path, monkeypatch):
    p = write(tmp_path, """
profiles:
  local:
    url: https://x
    password_env: NOPE_NOT_SET
""")
    c = cfg.load(p)
    monkeypatch.delenv("NOPE_NOT_SET", raising=False)
    with pytest.raises(cfg.ConfigError):
        c.resolve().password()


def test_password_env_resolved(tmp_path, monkeypatch):
    p = write(tmp_path, """
profiles:
  local:
    url: https://x
    password_env: TEST_PASS_VAR
""")
    monkeypatch.setenv("TEST_PASS_VAR", "secret123")
    c = cfg.load(p)
    assert c.resolve().password() == "secret123"


def test_missing_url(tmp_path):
    p = write(tmp_path, """
profiles:
  local:
    user: admin
""")
    with pytest.raises(cfg.ConfigError):
        cfg.load(p)
