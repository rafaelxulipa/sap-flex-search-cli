from flexsearch.client import HacClient


def test_standard_meta_pair():
    html = """
    <html><head>
      <meta name="_csrf" content="abc-123-def-456"/>
      <meta name="_csrf_header" content="X-CSRF-TOKEN"/>
    </head></html>
    """
    token, header = HacClient._parse_csrf(html)
    assert token == "abc-123-def-456"
    assert header == "X-CSRF-TOKEN"


def test_csrftoken_input_fallback():
    html = """
    <form>
      <input type="hidden" name="CSRFToken" value="11111111-2222-3333"/>
    </form>
    """
    token, header = HacClient._parse_csrf(html)
    assert token == "11111111-2222-3333"
    assert header == "CSRFToken"


def test_alternative_meta_name():
    html = '<meta name="csrfToken" content="aaaaaaaaaaaaaaaaa"/>'
    token, _ = HacClient._parse_csrf(html)
    assert token == "aaaaaaaaaaaaaaaaa"


def test_js_variable_fallback():
    html = """
    <script>
      var csrfToken = "deadbeef-1234-5678";
    </script>
    """
    token, _ = HacClient._parse_csrf(html)
    assert token == "deadbeef-1234-5678"


def test_no_token_returns_none():
    token, header = HacClient._parse_csrf("<html><body>nothing here</body></html>")
    assert token is None
    assert header is None


def test_ignores_parameter_meta():
    html = '<meta name="_csrf_parameter" content="_csrf"/>'
    token, _ = HacClient._parse_csrf(html)
    assert token is None
