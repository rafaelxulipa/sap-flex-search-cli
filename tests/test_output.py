import io
import json

from flexsearch.client import FlexResult
from flexsearch.output import render_csv, render_json, render_table


def sample() -> FlexResult:
    return FlexResult(
        headers=["pk", "code"],
        rows=[[8796093022208, "PROD_A"], [8796093022209, "PROD_B"]],
        query="select {pk}, {code} from {Product}",
        execution_time=12,
        raw={"headers": ["pk", "code"], "resultList": [[1, "a"]]},
    )


def test_csv():
    buf = io.StringIO()
    render_csv(sample(), stream=buf)
    out = buf.getvalue().splitlines()
    assert out[0] == "pk,code"
    assert "PROD_A" in out[1]
    assert "PROD_B" in out[2]


def test_json_default():
    buf = io.StringIO()
    render_json(sample(), stream=buf)
    payload = json.loads(buf.getvalue())
    assert payload["executionTime"] == 12
    assert payload["rows"][0] == {"pk": 8796093022208, "code": "PROD_A"}


def test_json_raw():
    buf = io.StringIO()
    render_json(sample(), stream=buf, raw=True)
    payload = json.loads(buf.getvalue())
    assert "resultList" in payload


def test_table_no_throw():
    buf = io.StringIO()
    render_table(sample(), stream=buf)
    assert "PROD_A" in buf.getvalue()
