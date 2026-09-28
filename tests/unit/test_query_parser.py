import pytest

from contextvault.query.ast import All, Any, Not, Predicate, all_content, any_content, deserialize, serialize
from contextvault.query.errors import QueryParseError, QueryValidationError
from contextvault.query.parser import parse_query


def test_documented_query_examples_build_typed_ast():
    simple = parse_query('type:pdf AND content:"vector database"')
    assert simple == All((
        Predicate("extension", "eq", ".pdf"),
        Predicate("content", "phrase", "vector database"),
    ))

    nested = parse_query(
        '(extension:pdf OR extension:docx) AND content:"operating systems" AND NOT content:"assignment"'
    )
    assert isinstance(nested, All)
    assert isinstance(nested.children[0], Any)
    assert isinstance(nested.children[2], Not)
    assert nested.children[2].child == Predicate("content", "phrase", "assignment")


def test_operator_precedence_is_not_or_and():
    node = parse_query("name:notes OR path:school AND content:retrieval")
    assert isinstance(node, Any)
    assert node.children[0] == Predicate("name", "contains", "notes")
    assert node.children[1] == All((
        Predicate("path", "contains", "school"),
        Predicate("content", "contains", "retrieval"),
    ))


def test_quoted_escapes_phrase_and_regex_are_preserved():
    phrase = parse_query(r'name:"Lecture \"two\" notes"')
    assert phrase == Predicate("name", "contains", 'lecture "two" notes')
    regex = parse_query('path~"(?i)lecture-[0-9]+\\.pdf"')
    assert regex == Predicate("path", "regex", r"(?i)lecture-[0-9]+\.pdf")


def test_size_and_timestamp_values_are_typed_and_canonical():
    assert parse_query("size>=1.5MB") == Predicate("size", "gte", 1_572_864)
    assert parse_query('modified>"2025-01-02T03:00:00+03:00"') == Predicate(
        "modified", "gt", "2025-01-02T00:00:00+00:00"
    )
    assert parse_query("created>=2025-01-02") == Predicate(
        "created", "gte", "2025-01-02T00:00:00+00:00"
    )


def test_ast_json_round_trip_and_gui_builders():
    node = all_content("retrieval", "ranking")
    assert isinstance(node, All)
    assert deserialize(serialize(node)) == node
    assert any_content("pdf", "docx") == Any((
        Predicate("content", "contains", "pdf"), Predicate("content", "contains", "docx")
    ))


@pytest.mark.parametrize("query, column", [
    ("unknown:x", 1),
    ("size~\"huge\"", 5),
    ("modified>never", 10),
    ('content~"text"', 8),
    ("name:", 6),
    ("name:\"unterminated", 6),
])
def test_invalid_query_reports_column(query, column):
    with pytest.raises((QueryParseError, QueryValidationError)) as error:
        parse_query(query)
    assert error.value.column == column


def test_excessive_nesting_and_regex_complexity_are_rejected():
    with pytest.raises(QueryParseError, match="nesting"):
        parse_query("(" * 33 + "name:x" + ")" * 33)
    with pytest.raises(QueryValidationError, match="Nested repetition"):
        parse_query('name~"(a+)+"')
    with pytest.raises(QueryValidationError, match="backreferences"):
        parse_query('name~"(a)\\1"')
    with pytest.raises(QueryParseError, match="nesting"):
        parse_query("NOT " * 33 + "name:x")


def test_query_error_renders_column_caret():
    with pytest.raises(QueryParseError) as error:
        parse_query("name:")
    assert error.value.render("name:").splitlines()[1] == "     ^"


def test_invalid_serialized_ast_and_empty_groups_are_rejected():
    with pytest.raises(QueryValidationError, match="version"):
        deserialize({"version": 2, "root": {"kind": "predicate"}})
    with pytest.raises(QueryValidationError, match="empty"):
        serialize(All(()))


def test_implicit_whitespace_and_unquoted_regex_are_not_silently_interpreted():
    with pytest.raises(QueryParseError):
        parse_query("name:notes content:retrieval")
    with pytest.raises(QueryParseError, match="quoted"):
        parse_query("name~notes")
