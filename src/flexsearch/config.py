from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".flexsearch" / "config.yaml"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "flexsearch"


class ConfigError(Exception):
    pass


@dataclass
class Profile:
    name: str
    url: str
    user: str = "admin"
    password_env: str | None = None
    verify_ssl: bool = True
    # Webapp context root for HAC. Default "/" (CCv2 backgroundprocessing
    # aspect mounts HAC at the host root). Set to "/hac" for legacy/local
    # installs, or anything else the env uses.
    base_path: str = "/"

    @property
    def base_url(self) -> str:
        return self.url.rstrip("/")

    @property
    def normalized_base_path(self) -> str:
        bp = (self.base_path or "/").strip()
        if not bp.startswith("/"):
            bp = "/" + bp
        if bp != "/" and bp.endswith("/"):
            bp = bp.rstrip("/")
        return bp

    def password(self) -> str:
        if not self.password_env:
            raise ConfigError(
                f"Profile '{self.name}': no password_env set. Add password_env: VAR_NAME to config."
            )
        val = os.environ.get(self.password_env)
        if not val:
            raise ConfigError(
                f"Profile '{self.name}': env var '{self.password_env}' is empty or unset."
            )
        return val

    def cookie_path(self, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{self.name}.cookies"


@dataclass
class Config:
    default_profile: str
    profiles: dict[str, Profile]
    source_path: Path | None = None

    def resolve(self, name: str | None = None) -> Profile:
        chosen = name or os.environ.get("FLEXSEARCH_PROFILE") or self.default_profile
        if chosen not in self.profiles:
            available = ", ".join(sorted(self.profiles)) or "<none>"
            raise ConfigError(f"Unknown profile '{chosen}'. Available: {available}.")
        return self.profiles[chosen]


def _profile_from_dict(name: str, data: dict[str, Any]) -> Profile:
    if "url" not in data:
        raise ConfigError(f"Profile '{name}': missing required field 'url'.")
    return Profile(
        name=name,
        url=str(data["url"]),
        user=str(data.get("user", "admin")),
        password_env=data.get("password_env"),
        verify_ssl=bool(data.get("verify_ssl", True)),
        base_path=str(data.get("base_path", "/")),
    )


def load(path: Path | None = None) -> Config:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.exists():
        raise ConfigError(
            f"Config not found at {p}. Run `flexsearch config init` or create the file manually."
        )
    raw = yaml.safe_load(p.read_text()) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"Config at {p} must be a YAML mapping.")

    profiles_raw = raw.get("profiles") or {}
    if not isinstance(profiles_raw, dict) or not profiles_raw:
        raise ConfigError(f"Config at {p}: 'profiles' is missing or empty.")

    profiles = {name: _profile_from_dict(name, body or {}) for name, body in profiles_raw.items()}
    default = raw.get("default_profile") or next(iter(profiles))
    if default not in profiles:
        raise ConfigError(f"default_profile '{default}' is not in profiles.")

    return Config(default_profile=default, profiles=profiles, source_path=p)


SAMPLE_CONFIG = """\
default_profile: local
profiles:
  local:
    url: https://localhost:9002
    user: admin
    password_env: HAC_LOCAL_PASS
    verify_ssl: false
    base_path: /hac        # legacy / local install
  # CCv2 backgroundprocessing aspect mounts HAC at the host root:
  # s1:
  #   url: https://backgroundprocessing.<env>-s1-public.model-t.cc.commerce.ondemand.com
  #   user: admin
  #   password_env: HAC_S1_PASS
  #   base_path: /          # default
"""


def write_sample(path: Path = DEFAULT_CONFIG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ConfigError(f"Refusing to overwrite existing config at {path}.")
    path.write_text(SAMPLE_CONFIG)
    return path
