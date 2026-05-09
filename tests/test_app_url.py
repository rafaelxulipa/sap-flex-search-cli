from flexsearch.client import HacClient
from flexsearch.config import Profile


def _client(base_path: str) -> HacClient:
    p = Profile(name="t", url="https://example.com", base_path=base_path)
    return HacClient.__new__(HacClient).__class__.__init__.__wrapped__ if False else _make(p)


def _make(profile: Profile) -> HacClient:
    obj = HacClient.__new__(HacClient)
    obj.profile = profile  # type: ignore[attr-defined]
    return obj


def test_root_base_path_default():
    c = _make(Profile(name="t", url="https://example.com"))
    assert c._app_url("") == "https://example.com/"
    assert c._app_url("console/flexsearch") == "https://example.com/console/flexsearch"
    assert c._app_url("/console/flexsearch/execute") == "https://example.com/console/flexsearch/execute"


def test_hac_base_path():
    c = _make(Profile(name="t", url="https://example.com", base_path="/hac"))
    assert c._app_url("") == "https://example.com/hac/"
    assert c._app_url("console/flexsearch") == "https://example.com/hac/console/flexsearch"


def test_base_path_normalization_trailing_slash():
    c = _make(Profile(name="t", url="https://example.com", base_path="/hac/"))
    assert c.profile.normalized_base_path == "/hac"
    assert c._app_url("login") == "https://example.com/hac/login"


def test_base_path_normalization_missing_slash():
    c = _make(Profile(name="t", url="https://example.com", base_path="hac"))
    assert c.profile.normalized_base_path == "/hac"


def test_url_with_path_in_base_url_is_ignored_for_app_url():
    # We always rebuild from scheme + netloc, so any path on the configured
    # url is ignored — base_path is the source of truth.
    c = _make(Profile(name="t", url="https://example.com/extra", base_path="/hac"))
    assert c._app_url("login") == "https://example.com/hac/login"
