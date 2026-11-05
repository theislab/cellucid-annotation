#!/usr/bin/env python3
"""Validate every author-written Cellucid annotation repository input.

The Cellucid web app (``assets/js/app/community-annotations/wire-contract.js``
in theislab/cellucid) applies the same contract; one shared accept/reject
corpus (``tests/fixtures/contract-corpus.json``) holds this validator and the
app to the same verdict on every case. Any input is reported as a validation
error, never as a crash: oversized files, invalid UTF-8, malformed or deeply
nested JSON and integers of any size included.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import pathlib
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
ANNOTATIONS_DIR = ROOT / "annotations"
USERS_DIR = ANNOTATIONS_DIR / "users"
MODERATION_DIR = ANNOTATIONS_DIR / "moderation"
CONFIG_FILE = ANNOTATIONS_DIR / "config.json"
CONFIG_SCHEMA_FILE = ANNOTATIONS_DIR / "config.schema.json"
USER_SCHEMA_FILE = ANNOTATIONS_DIR / "schema.json"
MERGES_FILE = MODERATION_DIR / "merges.json"
MERGES_SCHEMA_FILE = MODERATION_DIR / "merges.schema.json"

# GitHub's repository Contents API returns a file's content as JSON only up to
# 1 MB (https://docs.github.com/en/rest/repos/contents#get-repository-content),
# and Cellucid reads annotation files through it.
ANNOTATION_FILE_MAX_UTF8_BYTES = 1_000_000

# Python's json decoder recurses once per nesting level and stops at the
# interpreter's recursion limit (sys.getrecursionlimit(), 1000 by default:
# https://docs.python.org/3/library/sys.html#sys.getrecursionlimit), so JSON
# nested deeper than this is refused before decoding, with the sentence the web
# app uses for the same documents. No valid annotation document nests deeper
# than 7 levels.
ANNOTATION_JSON_MAX_DEPTH = 512

# The whitespace of the annotation contract: the union of ECMAScript \s and
# str.isspace(). The schemas use exactly this class, and so does the web app.
ANNOTATION_WHITESPACE_CLASS = (
    r"[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a"
    r"\u2028\u2029\u202f\u205f\u3000\ufeff]"
)

# Git blob object ids (SHA-1 of b"blob <size>\0" + bytes) of the canonical
# schema files. Cellucid accepts a repository only when these paths hold
# exactly these blobs; so does this validator.
SCHEMA_BLOB_OIDS = {
    "annotations/schema.json": "9c7263612ce91052cddca9bc5b25680bcaf09194",
    "annotations/config.schema.json": "967093fe91eb99234239399ab067d63305952a6b",
    "annotations/moderation/merges.schema.json": "102bae917d6fe7810acb5c494cee498ceadf6e27",
}
TEMPLATE_URL = "https://github.com/theislab/cellucid-annotation"

USER_FILE_NAME = re.compile(r"ghid_[1-9][0-9]*\.json")
USERS_SENTINEL = ".gitkeep"

# The exact names Cellucid reads at each level of the layout. Any other entry
# whose name differs from one of them only in letter case is a case variant:
# Cellucid never reads it, and on a case-insensitive file system it would
# shadow the real path.
LAYOUT_NAMES = {
    ROOT: ("annotations",),
    ANNOTATIONS_DIR: ("users", "moderation", "config.json", "config.schema.json", "schema.json"),
    MODERATION_DIR: ("merges.json", "merges.schema.json"),
}

_SCHEMA_KEYS = frozenset(
    {
        "$schema",
        "$id",
        "title",
        "description",
        "type",
        "required",
        "properties",
        "propertyNames",
        "additionalProperties",
        "items",
        "oneOf",
        "const",
        "enum",
        "format",
        "minimum",
        "maximum",
        "minLength",
        "minItems",
        "uniqueItems",
        "pattern",
    }
)
_JSON_TYPES = frozenset(
    {"null", "boolean", "object", "array", "number", "integer", "string"}
)
_UTC_DATE_TIME = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?:\.(?P<millisecond>[0-9]{3}))?Z$"
)
_ORCID_ID = re.compile(r"^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$")
_SUGGESTION_ID_OWNER = re.compile(r"ghid_[1-9][0-9]*(?=_)")
# One JSON string token, or a bracket, or the quote of a string that never ends.
_JSON_DEPTH_TOKEN = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"|[\[\]{}]|"', re.DOTALL)
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


class JsonInputError(ValueError):
    """Raised when input is not one valid, unambiguous JSON document."""


class AnnotationFileTooLargeError(JsonInputError):
    """Raised before parsing an active annotation file over GitHub's limit."""


class SchemaDefinitionError(ValueError):
    """Raised when a checked-in schema is not the canonical one or is invalid."""


def git_blob_oid(raw: bytes) -> str:
    """The Git object id of a blob holding ``raw``."""
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


def _reject_json_constant(value: str) -> None:
    raise JsonInputError(f"{value} is not a valid JSON number")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonInputError(f"duplicate JSON object key {json.dumps(key)}")
        result[key] = value
    return result


def _check_json_depth(text: str) -> None:
    depth = 0
    for match in _JSON_DEPTH_TOKEN.finditer(text):
        token = match.group()
        if token in ("[", "{"):
            depth += 1
            if depth > ANNOTATION_JSON_MAX_DEPTH:
                raise JsonInputError(
                    f"JSON nesting exceeds {ANNOTATION_JSON_MAX_DEPTH} levels"
                )
        elif token in ("]", "}"):
            depth -= 1
        elif token == '"':
            # A string that never ends: the decoder reports it.
            return


def parse_annotation_bytes(raw: bytes) -> Any:
    """Decode one active annotation file as strict UTF-8 JSON.

    Duplicate keys, non-finite constants, a byte-order mark, invalid UTF-8,
    nesting deeper than ``ANNOTATION_JSON_MAX_DEPTH`` and integers too long
    for this Python to read all raise ``JsonInputError``.
    """
    if len(raw) > ANNOTATION_FILE_MAX_UTF8_BYTES:
        raise AnnotationFileTooLargeError(
            f"active annotation file exceeds {ANNOTATION_FILE_MAX_UTF8_BYTES} bytes"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise JsonInputError(f"not UTF-8 text ({error})") from error
    _check_json_depth(text)
    try:
        return json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except JsonInputError:
        raise
    except (ValueError, RecursionError) as error:
        # json.JSONDecodeError, and the integer-digit limit of Python 3.10.7+
        # (sys.get_int_max_str_digits()), are ValueErrors. A RecursionError
        # needs a recursion limit set below the nesting checked above, which a
        # program importing this module may do; it is reported all the same.
        raise JsonInputError(str(error)) from error


def read_annotation_json(path: pathlib.Path) -> Any:
    """Read one active annotation file as strict UTF-8 JSON."""
    with path.open("rb") as handle:
        raw = handle.read(ANNOTATION_FILE_MAX_UTF8_BYTES + 1)
    return parse_annotation_bytes(raw)


def fail(errors: Sequence[str]) -> int:
    """Print validation errors to stderr and return the CLI failure code."""
    for error in errors:
        print(error, file=sys.stderr)
    return 1


def _child_location(location: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{location}[{key}]"
    return f"{location}[{json.dumps(key, ensure_ascii=False)}]"


def _is_number_value(value: Any) -> bool:
    """A JSON number Python holds: an int of any size or a finite float."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _is_json_number(value: Any) -> bool:
    """A JSON number the web app reads as a finite number.

    The app reads every JSON number as an IEEE double, so an integer too large
    for one (about 1.8e308 and above) is not a finite number there.
    """
    if not _is_number_value(value):
        return False
    if isinstance(value, int):
        try:
            float(value)
        except OverflowError:
            return False
    return True


def _is_json_integer(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value) and value.is_integer()


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if _is_number_value(left) and _is_number_value(right):
        return left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    return type(left) is type(right) and left == right


def _json_fingerprint(value: Any) -> Any:
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float)):
        return ("number", value)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, list):
        return ("array", tuple(_json_fingerprint(item) for item in value))
    if isinstance(value, dict):
        return (
            "object",
            tuple((key, _json_fingerprint(value[key])) for key in sorted(value)),
        )
    raise TypeError(f"value is not a JSON value: {type(value).__name__}")


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return _is_json_integer(value)
    if expected == "number":
        return _is_json_number(value)
    raise SchemaDefinitionError(f"unsupported JSON type {expected!r}")


def _schema_type_names(schema: Mapping[str, Any]) -> tuple[str, ...]:
    declared = schema.get("type")
    if declared is None:
        return ()
    if isinstance(declared, str):
        return (declared,)
    return tuple(declared)


def _is_valid_utc_date_time(value: str) -> bool:
    match = _UTC_DATE_TIME.fullmatch(value)
    if match is None:
        return False
    parts = match.groupdict()
    millisecond = parts["millisecond"]
    try:
        datetime.datetime(
            year=int(parts["year"]),
            month=int(parts["month"]),
            day=int(parts["day"]),
            hour=int(parts["hour"]),
            minute=int(parts["minute"]),
            second=int(parts["second"]),
            microsecond=0 if millisecond is None else int(millisecond) * 1000,
            tzinfo=datetime.timezone.utc,
        )
    except ValueError:
        return False
    return True


def _is_valid_orcid_id(value: str) -> bool:
    if _ORCID_ID.fullmatch(value) is None:
        return False
    compact = value.replace("-", "")
    total = 0
    for character in compact[:15]:
        total = (total + int(character)) * 2
    result = (12 - (total % 11)) % 11
    expected = "X" if result == 10 else str(result)
    return compact[15] == expected


def suggestion_id_owner(value: Any) -> str | None:
    """The ``ghid_<n>`` a suggestion id names, or None when it has no owner.

    A suggestion id is ``ghid_<n>_<rest>``; the schemas state its shape, so
    this reads the owner of an id that already matched them.
    """
    if not isinstance(value, str):
        return None
    match = _SUGGESTION_ID_OWNER.match(value)
    return None if match is None else match.group()


def _schema_errors(value: Any, schema: Mapping[str, Any], location: str) -> list[str]:
    errors: list[str] = []
    type_names = _schema_type_names(schema)
    if type_names and not any(_matches_json_type(value, name) for name in type_names):
        expected = "|".join(type_names)
        return [f"{location}: must have JSON type {expected}"]

    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(f"{location}: must equal {schema['const']!r}")
    if "enum" in schema and not any(
        _json_equal(value, item) for item in schema["enum"]
    ):
        errors.append(f"{location}: must be one of {schema['enum']!r}")

    if "oneOf" in schema:
        matches = 0
        type_matched_errors: list[list[str]] = []
        for option in schema["oneOf"]:
            option_errors = _schema_errors(value, option, location)
            if not option_errors:
                matches += 1
            option_types = _schema_type_names(option)
            if not option_types or any(
                _matches_json_type(value, name) for name in option_types
            ):
                type_matched_errors.append(option_errors)
        if matches != 1:
            if matches == 0 and len(type_matched_errors) == 1:
                errors.extend(type_matched_errors[0])
            errors.append(f"{location}: must match exactly one allowed schema")

    if isinstance(value, dict):
        required = schema.get("required", ())
        for key in required:
            if key not in value:
                errors.append(f"{location}: missing required field {key!r}")

        properties = schema.get("properties", {})
        property_names = schema.get("propertyNames")
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            item_location = _child_location(location, key)
            if property_names is not None:
                errors.extend(_schema_errors(key, property_names, item_location))
            if key in properties:
                errors.extend(_schema_errors(item, properties[key], item_location))
            elif additional is False:
                errors.append(f"{location}: unknown field {key!r}")
            elif isinstance(additional, dict):
                errors.extend(_schema_errors(item, additional, item_location))

    if isinstance(value, list):
        minimum_items = schema.get("minItems")
        if minimum_items is not None and len(value) < minimum_items:
            errors.append(f"{location}: must contain at least {minimum_items} item(s)")
        if schema.get("uniqueItems") is True:
            seen_items: set[Any] = set()
            for index, item in enumerate(value):
                fingerprint = _json_fingerprint(item)
                if fingerprint in seen_items:
                    errors.append(f"{location}[{index}]: duplicates an earlier item")
                seen_items.add(fingerprint)
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                errors.extend(
                    _schema_errors(item, item_schema, _child_location(location, index))
                )

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if minimum_length is not None and len(value) < minimum_length:
            errors.append(
                f"{location}: must contain at least {minimum_length} character(s)"
            )
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            errors.append(f"{location}: must match pattern {pattern!r}")
        if schema.get("format") == "date-time" and not _is_valid_utc_date_time(value):
            errors.append(
                f"{location}: must be a valid UTC date-time in "
                "YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DDTHH:MM:SS.sssZ form"
            )

    if _is_number_value(value):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            errors.append(f"{location}: must be at least {minimum}")
        if maximum is not None and value > maximum:
            errors.append(f"{location}: must be at most {maximum}")

    return errors


def _validate_schema_definition(schema: Any, location: str = "$") -> None:
    if not isinstance(schema, dict):
        raise SchemaDefinitionError(f"{location}: schema must be an object")
    unknown = set(schema) - _SCHEMA_KEYS
    if unknown:
        unknown_names = ", ".join(sorted(repr(name) for name in unknown))
        raise SchemaDefinitionError(
            f"{location}: unsupported schema keyword(s): {unknown_names}"
        )

    if "type" in schema:
        declared = schema["type"]
        if isinstance(declared, str):
            type_names = (declared,)
        elif (
            isinstance(declared, list)
            and declared
            and all(isinstance(name, str) for name in declared)
        ):
            type_names = tuple(declared)
        else:
            raise SchemaDefinitionError(
                f"{location}.type: must be a type name or non-empty array"
            )
        if len(set(type_names)) != len(type_names) or any(
            name not in _JSON_TYPES for name in type_names
        ):
            raise SchemaDefinitionError(
                f"{location}.type: contains an invalid or duplicate type"
            )

    if "required" in schema:
        required = schema["required"]
        if (
            not isinstance(required, list)
            or not all(isinstance(name, str) for name in required)
            or len(set(required)) != len(required)
        ):
            raise SchemaDefinitionError(
                f"{location}.required: must contain unique string names"
            )

    if "properties" in schema:
        properties = schema["properties"]
        if not isinstance(properties, dict):
            raise SchemaDefinitionError(f"{location}.properties: must be an object")
        for key, child in properties.items():
            _validate_schema_definition(child, f"{location}.properties[{key!r}]")

    if "additionalProperties" in schema:
        additional = schema["additionalProperties"]
        if not isinstance(additional, bool):
            _validate_schema_definition(additional, f"{location}.additionalProperties")

    for keyword in ("items", "propertyNames"):
        if keyword in schema:
            _validate_schema_definition(schema[keyword], f"{location}.{keyword}")

    if "oneOf" in schema:
        one_of = schema["oneOf"]
        if not isinstance(one_of, list) or not one_of:
            raise SchemaDefinitionError(f"{location}.oneOf: must be a non-empty array")
        for index, child in enumerate(one_of):
            _validate_schema_definition(child, f"{location}.oneOf[{index}]")

    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or not enum:
            raise SchemaDefinitionError(f"{location}.enum: must be a non-empty array")

    for keyword in ("minimum", "maximum"):
        if keyword in schema and not _is_json_number(schema[keyword]):
            raise SchemaDefinitionError(f"{location}.{keyword}: invalid bound")

    for keyword in ("minLength", "minItems"):
        if keyword not in schema:
            continue
        bound = schema[keyword]
        if not isinstance(bound, int) or isinstance(bound, bool) or bound < 0:
            raise SchemaDefinitionError(f"{location}.{keyword}: invalid bound")

    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        raise SchemaDefinitionError(f"{location}.uniqueItems: must be boolean")
    if "pattern" in schema:
        pattern = schema["pattern"]
        if not isinstance(pattern, str):
            raise SchemaDefinitionError(f"{location}.pattern: must be a string")
        try:
            re.compile(pattern)
        except re.error as error:
            raise SchemaDefinitionError(
                f"{location}.pattern: invalid regular expression"
            ) from error
    if "format" in schema and schema["format"] != "date-time":
        raise SchemaDefinitionError(
            f"{location}.format: only the exact 'date-time' format is supported"
        )
    for keyword in ("$schema", "$id"):
        if keyword in schema and not isinstance(schema[keyword], str):
            raise SchemaDefinitionError(f"{location}.{keyword}: must be a string")


def parse_schema(raw: bytes, label: str) -> dict[str, Any]:
    """Parse one schema and reject keywords this validator does not implement."""
    try:
        schema = parse_annotation_bytes(raw)
    except JsonInputError as error:
        raise SchemaDefinitionError(f"{label}: {error}") from error
    _validate_schema_definition(schema)
    return schema


def load_schema(path: pathlib.Path) -> dict[str, Any]:
    """Load one checked-in schema; it must be the canonical one, byte for byte."""
    relative = path.relative_to(ROOT).as_posix()
    raw = path.read_bytes()
    actual = git_blob_oid(raw)
    expected = SCHEMA_BLOB_OIDS[relative]
    if actual != expected:
        raise SchemaDefinitionError(
            f"{relative}: is not the canonical schema (git blob {actual}, expected "
            f"{expected}); copy it unchanged from {TEMPLATE_URL}"
        )
    return parse_schema(raw, relative)


def _document_errors(
    doc: Any,
    path: pathlib.Path,
    schema: Mapping[str, Any],
) -> list[str]:
    return [f"{path}: {error}" for error in _schema_errors(doc, schema, "$")]


def validate_config(
    doc: Any,
    path: pathlib.Path,
    schema: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate `annotations/config.json` against its exact current contract."""
    contract = load_schema(CONFIG_SCHEMA_FILE) if schema is None else schema
    errors = _document_errors(doc, path, contract)
    if errors:
        return errors

    dataset_entries = doc["supportedDatasets"]
    seen_dataset_ids: set[str] = set()
    for index, entry in enumerate(dataset_entries):
        dataset_id = entry["datasetId"]
        if dataset_id in seen_dataset_ids:
            errors.append(
                f'{path}: $["supportedDatasets"][{index}]["datasetId"]: '
                f"duplicates dataset id {dataset_id!r}"
            )
        seen_dataset_ids.add(dataset_id)

        fields = entry["fieldsToAnnotate"]
        field_set = set(fields)
        for field in entry["closedFields"]:
            if field not in field_set:
                errors.append(
                    f"{path}: dataset {dataset_id!r} closed field {field!r} "
                    "is not in fieldsToAnnotate"
                )
        settings_fields = set(entry["annotatableSettings"])
        for field in sorted(settings_fields - field_set):
            errors.append(
                f"{path}: dataset {dataset_id!r} settings field {field!r} "
                "is not in fieldsToAnnotate"
            )
        for field in fields:
            if field not in settings_fields:
                errors.append(
                    f"{path}: dataset {dataset_id!r} is missing settings for "
                    f"field {field!r}"
                )
    return errors


def validate_user_file(
    doc: Any,
    path: pathlib.Path,
    schema: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate one `annotations/users/ghid_<githubUserId>.json` file."""
    contract = load_schema(USER_SCHEMA_FILE) if schema is None else schema
    errors = _document_errors(doc, path, contract)
    if not isinstance(doc, dict):
        return errors

    github_user_id = doc.get("githubUserId")
    if not (
        _is_json_integer(github_user_id)
        and 1 <= github_user_id <= _MAX_SAFE_INTEGER
    ):
        return errors
    expected_identity = f"ghid_{int(github_user_id)}"
    expected_filename = f"{expected_identity}.json"
    username = doc.get("username")
    if isinstance(username, str) and username != expected_identity:
        errors.append(
            f'{path}: $["username"] must equal {expected_identity!r} for githubUserId'
        )
    if path.name != expected_filename:
        errors.append(
            f"{path}: filename must be exactly {expected_filename!r} for githubUserId"
        )
    orcid = doc.get("orcid")
    if isinstance(orcid, str) and not _is_valid_orcid_id(orcid):
        errors.append(f'{path}: $["orcid"] must be an exact checksum-valid ORCID iD')
    datasets = doc.get("datasets")
    if isinstance(datasets, dict):
        for dataset_id, section in datasets.items():
            if isinstance(section, dict):
                errors.extend(
                    _section_errors(section, path, dataset_id, expected_identity)
                )
    return errors


def _section_errors(
    section: Mapping[str, Any],
    path: pathlib.Path,
    dataset_id: str,
    expected_identity: str,
) -> list[str]:
    """Invariants of one dataset's section of a user file.

    Every suggestion id starts with its proposer's ``ghid_<n>_``, and the
    proposer is the file's owner, so no contributor can write an id that
    collides with or claims another contributor's suggestion.
    """
    errors: list[str] = []
    where = f"dataset {dataset_id!r}"
    suggestion_ids: set[str] = set()
    suggestions = section.get("suggestions")
    if isinstance(suggestions, dict):
        for bucket, values in suggestions.items():
            if not isinstance(values, list):
                continue
            for index, suggestion in enumerate(values):
                if not isinstance(suggestion, dict):
                    continue
                suggestion_id = suggestion.get("id")
                if isinstance(suggestion_id, str):
                    if suggestion_id in suggestion_ids:
                        errors.append(
                            f"{path}: {where}: suggestion id {suggestion_id!r} at "
                            f"{bucket!r}[{index}] must be unique in its dataset"
                        )
                    suggestion_ids.add(suggestion_id)
                proposed_by = suggestion.get("proposedBy")
                if isinstance(proposed_by, str) and proposed_by != expected_identity:
                    errors.append(
                        f"{path}: {where}: suggestion {suggestion_id!r} proposedBy must "
                        f"equal file identity {expected_identity!r}"
                    )
                owner = suggestion_id_owner(suggestion_id)
                if owner is not None and owner != expected_identity:
                    errors.append(
                        f"{path}: {where}: suggestion id {suggestion_id!r} at "
                        f"{bucket!r}[{index}] must start with "
                        f"{expected_identity + '_'!r}, its proposer's identity"
                    )

    comments = section.get("comments")
    if isinstance(comments, dict):
        for suggestion_id, values in comments.items():
            if not isinstance(values, list):
                continue
            comment_ids: set[str] = set()
            for index, comment in enumerate(values):
                if not isinstance(comment, dict):
                    continue
                comment_id = comment.get("id")
                if isinstance(comment_id, str):
                    if comment_id in comment_ids:
                        errors.append(
                            f"{path}: {where}: comment id {comment_id!r} for "
                            f"{suggestion_id!r} at index {index} must be unique"
                        )
                    comment_ids.add(comment_id)
                author = comment.get("authorUsername")
                if isinstance(author, str) and author != expected_identity:
                    errors.append(
                        f"{path}: {where}: comment {comment_id!r} authorUsername must "
                        f"equal file identity {expected_identity!r}"
                    )

    deleted = section.get("deletedSuggestions")
    if isinstance(deleted, dict):
        for bucket, values in deleted.items():
            if not isinstance(values, list):
                continue
            for index, suggestion_id in enumerate(values):
                owner = suggestion_id_owner(suggestion_id)
                if owner is not None and owner != expected_identity:
                    errors.append(
                        f"{path}: {where}: deleted suggestion id {suggestion_id!r} at "
                        f"{bucket!r}[{index}] must name a suggestion of the file "
                        f"owner (start with {expected_identity + '_'!r})"
                    )
    return errors


def validate_merges(
    doc: Any,
    path: pathlib.Path,
    schema: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate optional author-only `annotations/moderation/merges.json`."""
    contract = load_schema(MERGES_SCHEMA_FILE) if schema is None else schema
    errors = _document_errors(doc, path, contract)
    if errors:
        return errors
    # A merge joins two suggestions of one bucket of one dataset; the same
    # bucket name in another dataset is another bucket.
    edges_by_bucket: dict[tuple[str, str], dict[str, str]] = {}
    for index, merge in enumerate(doc["merges"]):
        if merge["fromSuggestionId"] == merge["intoSuggestionId"]:
            errors.append(
                f'{path}: $["merges"][{index}]: fromSuggestionId and '
                "intoSuggestionId must differ"
            )
        bucket = (merge["datasetId"], merge["bucket"])
        source = merge["fromSuggestionId"]
        target = merge["intoSuggestionId"]
        bucket_edges = edges_by_bucket.setdefault(bucket, {})
        if source in bucket_edges:
            errors.append(
                f'{path}: $["merges"][{index}] duplicates the bucket/from '
                "mapping of an earlier merge"
            )
        else:
            bucket_edges[source] = target

    for bucket, edges in edges_by_bucket.items():
        for start in edges:
            seen = {start}
            current = start
            while current in edges:
                current = edges[current]
                if current in seen:
                    errors.append(
                        f"{path}: merges contain a cycle in bucket {bucket[1]!r} "
                        f"of dataset {bucket[0]!r}"
                    )
                    break
                seen.add(current)
    return errors


VALIDATORS = {
    "user": (validate_user_file, USER_SCHEMA_FILE),
    "config": (validate_config, CONFIG_SCHEMA_FILE),
    "merges": (validate_merges, MERGES_SCHEMA_FILE),
}


def validate_bytes(
    kind: str,
    raw: bytes,
    path: pathlib.Path,
    schemas: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Validate one file's bytes as the ``kind`` ("user", "config", "merges")."""
    try:
        doc = parse_annotation_bytes(raw)
    except JsonInputError as error:
        return [f"{path}: cannot read valid JSON ({error})"]
    validator, _ = VALIDATORS[kind]
    return validator(doc, path, schemas[kind])


def _read_and_validate(
    kind: str,
    path: pathlib.Path,
    schemas: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    if path.is_symlink() or not path.is_file():
        return [f"{path}: must be a regular file (not a link or a directory)"]
    try:
        with path.open("rb") as handle:
            raw = handle.read(ANNOTATION_FILE_MAX_UTF8_BYTES + 1)
    except OSError as error:
        return [f"{path}: cannot read ({error})"]
    return validate_bytes(kind, raw, path, schemas)


def load_contracts() -> dict[str, dict[str, Any]]:
    """Load the three canonical schemas, by kind."""
    return {kind: load_schema(schema_path) for kind, (_, schema_path) in VALIDATORS.items()}


def _layout_errors() -> list[str]:
    """Case variants of the layout's paths, which Cellucid never reads."""
    errors: list[str] = []
    for directory, names in LAYOUT_NAMES.items():
        if not directory.is_dir():
            continue
        folded = {name.casefold(): name for name in names}
        try:
            entries = sorted(entry.name for entry in directory.iterdir())
        except OSError as error:
            errors.append(f"{directory}: cannot list ({error})")
            continue
        for entry in entries:
            exact = folded.get(entry.casefold())
            if exact is not None and entry != exact:
                errors.append(
                    f"{directory / entry}: case variant of {exact!r}; Cellucid "
                    f"reads only the exact path {exact!r}"
                )
    return errors


def _user_paths(errors: list[str]) -> list[pathlib.Path]:
    """The user files under `annotations/users/`, reporting anything else there."""
    if not USERS_DIR.is_dir():
        errors.append(f"{USERS_DIR}: missing required directory")
        return []
    try:
        entries = sorted(USERS_DIR.iterdir())
    except OSError as error:
        errors.append(f"{USERS_DIR}: cannot list user files ({error})")
        return []
    paths: list[pathlib.Path] = []
    for path in entries:
        if path.is_symlink():
            errors.append(f"{path}: symbolic links are not permitted")
        elif path.is_dir():
            errors.append(f"{path}: directories are not permitted under {USERS_DIR}")
        elif not path.is_file():
            errors.append(f"{path}: must be a regular file")
        elif path.name == USERS_SENTINEL:
            try:
                sentinel_bytes = path.read_bytes()
            except OSError as error:
                errors.append(f"{path}: cannot inspect .gitkeep ({error})")
                continue
            if sentinel_bytes != b"\n":
                errors.append(f"{path}: .gitkeep must contain exactly one LF byte")
        elif USER_FILE_NAME.fullmatch(path.name) is None:
            errors.append(
                f"{path}: only ghid_<GitHub user id>.json user files and .gitkeep "
                f"are permitted under {USERS_DIR}"
            )
        else:
            paths.append(path)
    return paths


def main() -> int:
    """Validate the complete repository input set and return a process exit code."""
    try:
        schemas = load_contracts()
    except (OSError, SchemaDefinitionError) as error:
        return fail([f"annotation schema is invalid: {error}"])

    errors = _layout_errors()
    if CONFIG_FILE.is_symlink() or CONFIG_FILE.exists():
        errors.extend(_read_and_validate("config", CONFIG_FILE, schemas))
    else:
        errors.append(f"{CONFIG_FILE}: missing required file")

    for path in _user_paths(errors):
        errors.extend(_read_and_validate("user", path, schemas))

    if MERGES_FILE.is_symlink() or MERGES_FILE.exists():
        errors.extend(_read_and_validate("merges", MERGES_FILE, schemas))

    if errors:
        return fail(errors)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
