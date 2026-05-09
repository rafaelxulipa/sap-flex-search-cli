from __future__ import annotations

import logging
from dataclasses import dataclass, field
from http.cookiejar import LWPCookieJar
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

from .config import Profile

log = logging.getLogger(__name__)


class HacError(Exception):
    pass


class HacAuthError(HacError):
    pass


class HacQueryError(HacError):
    def __init__(self, message: str, *, query: str | None = None, raw: Any = None) -> None:
        super().__init__(message)
        self.query = query
        self.raw = raw


@dataclass
class FlexResult:
    headers: list[str]
    rows: list[list[Any]]
    query: str
    execution_time: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class HacClient:
    def __init__(self, profile: Profile, *, cookie_path: Path | None = None, timeout: int = 60) -> None:
        self.profile = profile
        self.timeout = timeout
        self.cookie_path = cookie_path or profile.cookie_path()
        self.session = requests.Session()
        jar = LWPCookieJar(str(self.cookie_path))
        if self.cookie_path.exists():
            try:
                jar.load(ignore_discard=True, ignore_expires=True)
            except Exception:
                log.warning("Could not load cookie jar at %s; starting fresh.", self.cookie_path)
        self.session.cookies = jar  # type: ignore[assignment]
        self.session.verify = profile.verify_ssl
        if not profile.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # ---- public ---------------------------------------------------------

    def execute(
        self,
        query: str,
        *,
        max_count: int = 200,
        locale: str = "en",
        run_as: str = "admin",
        commit: bool = False,
    ) -> FlexResult:
        body = {
            "flexibleSearchQuery": query,
            "user": run_as,
            "locale": locale,
            "maxCount": str(max_count),
            "commit": "true" if commit else "false",
        }
        try:
            return self._do_execute(body)
        except HacAuthError:
            log.info("Session expired or missing; logging in and retrying.")
            self.login()
            return self._do_execute(body)

    def login(self) -> None:
        # Hit the webapp root and follow redirects to whatever the actual
        # login page is (varies: /login, /login.jsp, /j_spring_security_check).
        entry_url = self._app_url("")
        r = self.session.get(entry_url, timeout=self.timeout, allow_redirects=True)
        if r.status_code >= 400:
            raise HacAuthError(f"GET {entry_url} failed: HTTP {r.status_code}")
        login_url = r.url  # final URL after redirects — used as Referer

        action_url, user_field, pass_field, hidden = self._parse_login_form(r.text, base=login_url)
        if not action_url:
            # Fallback to legacy Spring Security path under the configured base_path.
            action_url = self._app_url("j_spring_security_check")
            user_field, pass_field = "j_username", "j_password"
            log.warning("Could not parse login form; falling back to %s", action_url)

        token, header_name = self._parse_csrf(r.text)
        form: dict[str, str] = dict(hidden)
        form[user_field] = self.profile.user
        form[pass_field] = self.profile.password()
        if token and (header_name or "_csrf") not in form:
            form[header_name or "_csrf"] = token

        log.debug("HAC login POST → %s (fields: %s)", action_url, list(form.keys()))
        r2 = self.session.post(
            action_url,
            data=form,
            timeout=self.timeout,
            allow_redirects=False,
            headers={"Referer": login_url},
        )
        location = r2.headers.get("Location", "")
        ok_status = r2.status_code in (200, 301, 302, 303)
        is_error_redirect = any(
            marker in location.lower() for marker in ("login?error", "login.jsp?error", "/login?failed")
        )
        if not ok_status or is_error_redirect:
            raise HacAuthError(
                f"HAC login failed for user '{self.profile.user}' at {self.profile.base_url} "
                f"(POST {action_url} → status {r2.status_code}{f', Location: {location}' if location else ''})."
            )
        # Follow once to settle the session cookie.
        if location:
            self.session.get(urljoin(action_url, location), timeout=self.timeout)
        self._save_cookies()

    def logout_clear(self) -> None:
        self.session.cookies.clear()  # type: ignore[union-attr]
        if self.cookie_path.exists():
            self.cookie_path.unlink()

    # ---- internals ------------------------------------------------------

    # Candidate console paths (relative to the webapp base_path) across HAC
    # patch versions. First match wins.
    _PAGE_CANDIDATES = (
        "console/flexsearch",
        "platform/flexsearch",
        "flexsearch",
    )
    _EXECUTE_CANDIDATES = (
        "console/flexsearch/execute",
        "platform/flexsearch/execute",
        "flexsearch/execute",
    )

    def _do_execute(self, body: dict[str, str]) -> FlexResult:
        # Get CSRF token: try /hac/ first (always exists post-login), fall
        # back to console pages. The token is per-session so any HAC page works.
        token, header_name, page_url = self._fetch_csrf()
        if not token:
            log.warning("No CSRF token found on any HAC page; sending request without one.")

        last_error: tuple[str, int, str] | None = None
        for path in self._EXECUTE_CANDIDATES:
            exec_url = self._app_url(path)
            headers = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": page_url or self._app_url(""),
            }
            if token:
                headers[header_name or "X-CSRF-TOKEN"] = token
            r = self.session.post(
                exec_url, data=body, headers=headers, timeout=self.timeout, allow_redirects=False
            )
            log.debug("POST %s → %s", exec_url, r.status_code)
            if self._looks_like_login(r) or r.status_code in (401, 403):
                raise HacAuthError(
                    f"flexsearch/execute returned auth failure (status {r.status_code}) at {exec_url}."
                )
            if r.status_code == 404:
                last_error = (exec_url, 404, r.text[:200])
                continue
            if r.status_code >= 400:
                raise HacQueryError(f"flexsearch/execute HTTP {r.status_code} at {exec_url}: {r.text[:300]}")
            try:
                data = r.json()
            except ValueError as e:
                raise HacQueryError(f"Non-JSON response from HAC: {r.text[:300]}") from e
            break
        else:
            tried = ", ".join(self._app_url(p) for p in self._EXECUTE_CANDIDATES)
            raise HacError(
                f"All known FlexibleSearch endpoints returned 404. Tried: {tried}. "
                f"This HAC build may expose the console at a different path. "
                f"Last response body (200 chars): {last_error[2] if last_error else ''!r}"
            )

        self._save_cookies()

        if data.get("exception"):
            exc = data["exception"]
            msg = exc.get("message") if isinstance(exc, dict) else str(exc)
            raise HacQueryError(f"FlexibleSearch error: {msg}", query=body["flexibleSearchQuery"], raw=data)

        headers_out = data.get("headers") or []
        rows = data.get("resultList") or []
        return FlexResult(
            headers=list(headers_out),
            rows=[list(r) for r in rows],
            query=body["flexibleSearchQuery"],
            execution_time=data.get("executionTime"),
            raw=data,
        )

    def _fetch_csrf(self) -> tuple[str | None, str | None, str | None]:
        """Try a list of HAC pages until we find one that yields a CSRF token.

        Returns (token, header_name, page_url_used).
        """
        candidates = [""] + list(self._PAGE_CANDIDATES)
        for path in candidates:
            url = self._app_url(path)
            try:
                resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            except requests.RequestException as e:
                log.debug("GET %s failed: %s", url, e)
                continue
            log.debug("GET %s → %s (final %s)", url, resp.status_code, resp.url)
            if self._looks_like_login(resp) or "login" in resp.url.lower():
                raise HacAuthError(f"Redirected to login when fetching {url}.")
            if resp.status_code >= 400:
                continue
            token, header = self._parse_csrf(resp.text)
            if not token:
                cookie_token = self.session.cookies.get("XSRF-TOKEN")  # type: ignore[union-attr]
                if cookie_token:
                    token, header = cookie_token, "X-XSRF-TOKEN"
            if token:
                return token, header, resp.url
            log.debug("No CSRF found on %s (len=%d).", url, len(resp.text))
        return None, None, None

    def _app_url(self, rel: str) -> str:
        """Build a URL: scheme://host + profile.base_path + rel."""
        parsed = urlparse(self.profile.base_url)
        bp = self.profile.normalized_base_path
        rel = (rel or "").lstrip("/")
        if bp == "/":
            return f"{parsed.scheme}://{parsed.netloc}/{rel}" if rel else f"{parsed.scheme}://{parsed.netloc}/"
        return f"{parsed.scheme}://{parsed.netloc}{bp}/{rel}" if rel else f"{parsed.scheme}://{parsed.netloc}{bp}/"

    @staticmethod
    def _parse_login_form(html: str, base: str) -> tuple[str | None, str, str, dict[str, str]]:
        """Return (action_url, username_field, password_field, hidden_fields)
        for the login form on the HAC login page.
        """
        soup = BeautifulSoup(html, "html.parser")
        password_input = soup.find("input", attrs={"type": "password"})
        if not password_input:
            return None, "j_username", "j_password", {}
        form = password_input.find_parent("form")
        if not form:
            return None, "j_username", "j_password", {}
        action = form.get("action") or ""
        action_url = urljoin(base, action) if action else base

        pass_field = password_input.get("name") or "j_password"
        # username field: nearest text/email input in the same form
        user_field = "j_username"
        for inp in form.find_all("input"):
            t = (inp.get("type") or "text").lower()
            name = inp.get("name")
            if name and t in ("text", "email") and name not in ("_csrf", "CSRFToken"):
                user_field = name
                break

        hidden: dict[str, str] = {}
        for inp in form.find_all("input"):
            t = (inp.get("type") or "").lower()
            name = inp.get("name")
            if t == "hidden" and name:
                hidden[name] = inp.get("value") or ""
        return action_url, user_field, pass_field, hidden

    @staticmethod
    def _parse_csrf(html: str) -> tuple[str | None, str | None]:
        import re as _re

        soup = BeautifulSoup(html, "html.parser")

        # Spring's standard tags: <meta name="_csrf" .../><meta name="_csrf_header" .../>
        meta = soup.find("meta", attrs={"name": "_csrf"})
        header_meta = soup.find("meta", attrs={"name": "_csrf_header"})
        token = meta.get("content") if meta else None
        header = header_meta.get("content") if header_meta else None

        # Permissive meta scan: any name containing "csrf" (case-insensitive),
        # excluding parameter-name meta (`_csrf_parameter`).
        if not token:
            for m in soup.find_all("meta"):
                name = (m.get("name") or "").lower()
                if "csrf" not in name or name in ("_csrf_parameter", "_csrf_header"):
                    continue
                content = m.get("content")
                if content and len(content) > 8:
                    token = content
                    header = header or m.get("name")
                    break

        # Hidden input scan
        if not token:
            for inp in soup.find_all("input"):
                name = (inp.get("name") or "")
                if "csrf" in name.lower() or name == "CSRFToken":
                    val = inp.get("value")
                    if val:
                        token = val
                        header = name
                        break

        # JS variable fallback (some HAC patches render token only via JS)
        if not token:
            for pattern in (
                r"""['"]?_csrf['"]?\s*[:=]\s*['"]([0-9a-fA-F\-]{8,})['"]""",
                r"""csrfToken\s*[:=]\s*['"]([0-9a-fA-F\-]{8,})['"]""",
                r"""CSRFToken['"]?\s*[:=]\s*['"]([0-9a-fA-F\-]{8,})['"]""",
            ):
                m = _re.search(pattern, html)
                if m:
                    token = m.group(1)
                    break
        return token, header

    @staticmethod
    def _looks_like_login(resp: requests.Response) -> bool:
        loc = resp.headers.get("Location", "")
        if "login" in loc.lower():
            return True
        ct = resp.headers.get("Content-Type", "")
        if "html" in ct and "j_spring_security_check" in resp.text[:4000].lower():
            return True
        return False

    def _save_cookies(self) -> None:
        try:
            self.session.cookies.save(ignore_discard=True, ignore_expires=True)  # type: ignore[union-attr]
        except Exception as e:
            log.debug("Cookie save failed: %s", e)
