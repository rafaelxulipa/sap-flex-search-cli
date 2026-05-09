from flexsearch.safety import find_write_verbs, is_read_only


def test_simple_select():
    assert is_read_only("select {pk} from {Product}")


def test_select_with_semicolon():
    assert is_read_only("SELECT {pk} FROM {Product};")


def test_with_cte():
    assert is_read_only("WITH x AS (SELECT 1) SELECT * FROM x")


def test_update_blocked():
    assert not is_read_only("update {Product} set {name}='x'")
    assert "UPDATE" in find_write_verbs("update {Product} set {name}='x'")


def test_delete_blocked():
    assert not is_read_only("delete from {Product}")


def test_insert_inside_string_still_blocked_safely():
    # Even if 'INSERT' appears inside a string literal, leading verb check passes,
    # but the standalone check still catches the leading verb if it's a write verb.
    assert is_read_only("select 'INSERT INTO foo' from {Product}")


def test_comment_stripped():
    sql = """
    -- DELETE all
    /* UPDATE foo */
    SELECT {pk} FROM {Product}
    """
    assert is_read_only(sql)


def test_empty():
    assert not is_read_only("")
    assert not is_read_only("   ;  ")


def test_subquery_with_update_keyword_in_string():
    sql = "select 'no UPDATE here' from {Product}"
    assert is_read_only(sql)
