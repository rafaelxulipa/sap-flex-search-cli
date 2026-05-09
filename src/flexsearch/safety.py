from __future__ import annotations

import re

WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER", "CREATE", "MERGE", "REPLACE")

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING = re.compile(r"'(?:''|[^'])*'")


def _strip(sql: str) -> str:
    s = _BLOCK_COMMENT.sub(" ", sql)
    s = _LINE_COMMENT.sub(" ", s)
    s = _STRING.sub("''", s)
    return s


def is_read_only(sql: str) -> bool:
    """True if `sql` is a single SELECT-like statement with no DML/DDL verbs.

    FlexibleSearch is read-only by design, but the HAC console can be coerced
    into running raw SQL with commit=true. We refuse anything that smells
    destructive at the CLI layer regardless.
    """
    stripped = _strip(sql).strip().rstrip(";").strip()
    if not stripped:
        return False
    upper = stripped.upper()
    first = upper.split(None, 1)[0]
    if first not in ("SELECT", "WITH"):
        return False
    pattern = r"\b(" + "|".join(WRITE_VERBS) + r")\b"
    return re.search(pattern, upper) is None


def find_write_verbs(sql: str) -> list[str]:
    upper = _strip(sql).upper()
    return sorted({v for v in WRITE_VERBS if re.search(rf"\b{v}\b", upper)})
