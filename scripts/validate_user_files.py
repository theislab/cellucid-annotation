#!/usr/bin/env python3
"""Validate every author-written Cellucid annotation repository input."""

from __future__ import annotations

import datetime
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
CONFIG_FILE = ANNOTATIONS_DIR / "config.json"
CONFIG_SCHEMA_FILE = ANNOTATIONS_DIR / "config.schema.json"
USER_SCHEMA_FILE = ANNOTATIONS_DIR / "schema.json"
MERGES_FILE = ANNOTATIONS_DIR / "moderation" / "merges.json"
MERGES_SCHEMA_FILE = ANNOTATIONS_DIR / "moderation" / "merges.schema.json"

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
        "maxLength",
        "minItems",
        "maxItems",
        "maxProperties",
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


class JsonInputError(ValueError):
    """Raised when input uses syntax that is not valid, unambiguous JSON."""


class SchemaDefinitionError(ValueError):
    """Raised when a checked-in schema uses an unsupported or invalid shape."""


def _reject_json_constant(value: str) -> None:
    raise JsonInputError(f"{value} is not a valid JSON number")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonInputError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def read_json(path: pathlib.Path) -> Any:
    """Read strict UTF-8 JSON, rejecting duplicate keys and non-finite numbers."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(
            handle,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )


def fail(errors: Sequence[str]) -> int:
    """Print validation errors to stderr and return the CLI failure code."""
    for error in errors:
        print(error, file=sys.stderr)
    return 1


def _child_location(location: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{location}[{key}]"
    return f"{location}[{json.dumps(key, ensure_ascii=False)}]"


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
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
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and float(value).is_integer()
        )
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
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
        maximum_properties = schema.get("maxProperties")
        if maximum_properties is not None and len(value) > maximum_properties:
            errors.append(
                f"{location}: must contain at most {maximum_properties} field(s)"
            )
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
        maximum_items = schema.get("maxItems")
        if minimum_items is not None and len(value) < minimum_items:
            errors.append(f"{location}: must contain at least {minimum_items} item(s)")
        if maximum_items is not None and len(value) > maximum_items:
            errors.append(f"{location}: must contain at most {maximum_items} item(s)")
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
        maximum_length = schema.get("maxLength")
        if minimum_length is not None and len(value) < minimum_length:
            errors.append(
                f"{location}: must contain at least {minimum_length} character(s)"
            )
        if maximum_length is not None and len(value) > maximum_length:
            errors.append(
                f"{location}: must contain at most {maximum_length} character(s)"
            )
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            errors.append(f"{location}: must match pattern {pattern!r}")
        if schema.get("format") == "date-time" and not _is_valid_utc_date_time(value):
            errors.append(
                f"{location}: must be a valid UTC date-time in "
                "YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DDTHH:MM:SS.sssZ form"
            )

    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
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
        names = ", ".join(sorted(repr(name) for name in unknown))
        raise SchemaDefinitionError(
            f"{location}: unsupported schema keyword(s): {names}"
        )

    if "type" in schema:
        declared = schema["type"]
        if isinstance(declared, str):
            names = (declared,)
        elif (
            isinstance(declared, list)
            and declared
            and all(isinstance(name, str) for name in declared)
        ):
            names = tuple(declared)
        else:
            raise SchemaDefinitionError(
                f"{location}.type: must be a type name or non-empty array"
            )
        if len(set(names)) != len(names) or any(
            name not in _JSON_TYPES for name in names
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
        if keyword not in schema:
            continue
        bound = schema[keyword]
        if (
            not isinstance(bound, (int, float))
            or isinstance(bound, bool)
            or not math.isfinite(bound)
        ):
            raise SchemaDefinitionError(f"{location}.{keyword}: invalid bound")

    for keyword in (
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "maxProperties",
    ):
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


def load_schema(path: pathlib.Path) -> dict[str, Any]:
    """Load a checked-in schema and reject unsupported schema declarations."""
    schema = read_json(path)
    _validate_schema_definition(schema)
    return schema


def _assert_schema_identity(schema: Mapping[str, Any], expected_id: str) -> None:
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise SchemaDefinitionError(
            f"$schema must equal JSON Schema draft 2020-12 for {expected_id}"
        )
    if schema.get("$id") != expected_id:
        raise SchemaDefinitionError(f"$id must equal {expected_id!r}")


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

        fields = entry.get("fieldsToAnnotate")
        if fields is None:
            continue
        field_set = set(fields)
        for field in entry.get("closedFields", ()):
            if field not in field_set:
                errors.append(
                    f"{path}: dataset {dataset_id!r} closed field {field!r} "
                    "is not in fieldsToAnnotate"
                )
        for field in entry.get("annotatableSettings", {}):
            if field not in field_set:
                errors.append(
                    f"{path}: dataset {dataset_id!r} settings field {field!r} "
                    "is not in fieldsToAnnotate"
                )
        settings_fields = set(entry.get("annotatableSettings", {}))
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
    if (
        not isinstance(github_user_id, (int, float))
        or isinstance(github_user_id, bool)
        or not math.isfinite(github_user_id)
        or not float(github_user_id).is_integer()
        or github_user_id <= 0
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
        errors.append(
            f'{path}: $["orcid"] must be an exact checksum-valid ORCID iD'
        )
    suggestion_ids: set[str] = set()
    suggestions = doc.get("suggestions")
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
                            f"{path}: suggestion id {suggestion_id!r} at "
                            f"{bucket!r}[{index}] must be globally unique"
                        )
                    suggestion_ids.add(suggestion_id)
                proposed_by = suggestion.get("proposedBy")
                if isinstance(proposed_by, str) and proposed_by != expected_identity:
                    errors.append(
                        f"{path}: suggestion {suggestion_id!r} proposedBy must "
                        f"equal file identity {expected_identity!r}"
                    )

    comments = doc.get("comments")
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
                            f"{path}: comment id {comment_id!r} for "
                            f"{suggestion_id!r} at index {index} must be unique"
                        )
                    comment_ids.add(comment_id)
                author = comment.get("authorUsername")
                if isinstance(author, str) and author != expected_identity:
                    errors.append(
                        f"{path}: comment {comment_id!r} authorUsername must "
                        f"equal file identity {expected_identity!r}"
                    )
    return errors


def validate_user_repository(
    documents: Sequence[tuple[pathlib.Path, Mapping[str, Any]]],
) -> list[str]:
    """Validate invariants that span the complete set of exact user files."""
    errors: list[str] = []
    user_paths: dict[str, pathlib.Path] = {}
    suggestion_identities: dict[str, tuple[str, str, pathlib.Path]] = {}

    for path, document in documents:
        username = document["username"]
        previous_user_path = user_paths.get(username)
        if previous_user_path is not None:
            errors.append(
                f"{path}: duplicate user identity {username!r}; "
                f"already provided by {previous_user_path}"
            )
        else:
            user_paths[username] = path

        for bucket, suggestions in document["suggestions"].items():
            for index, suggestion in enumerate(suggestions):
                suggestion_id = suggestion["id"]
                proposed_by = suggestion["proposedBy"]
                previous = suggestion_identities.get(suggestion_id)
                if previous is not None:
                    previous_bucket, previous_owner, previous_path = previous
                    if previous_bucket != bucket or previous_owner != proposed_by:
                        errors.append(
                            f"{path}: suggestion id {suggestion_id!r} at "
                            f"{bucket!r}[{index}] conflicts with the suggestion "
                            f"owned by {previous_owner!r} in {previous_bucket!r} "
                            f"from {previous_path}"
                        )
                else:
                    suggestion_identities[suggestion_id] = (
                        bucket,
                        proposed_by,
                        path,
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
    edges_by_bucket: dict[str, dict[str, str]] = {}
    for index, merge in enumerate(doc["merges"]):
        if merge["fromSuggestionId"] == merge["intoSuggestionId"]:
            errors.append(
                f'{path}: $["merges"][{index}]: fromSuggestionId and '
                "intoSuggestionId must differ"
            )
        bucket = merge["bucket"]
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
                        f"{path}: merges contain a cycle in bucket {bucket!r}"
                    )
                    break
                seen.add(current)
    return errors


def _input_error(path: pathlib.Path, error: BaseException) -> str:
    return f"{path}: cannot read valid JSON ({error})"


def _read_and_validate(
    path: pathlib.Path,
    schema: Mapping[str, Any],
    validator: Any,
) -> list[str]:
    try:
        doc = read_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError, JsonInputError) as error:
        return [_input_error(path, error)]
    return validator(doc, path, schema)


def _load_contracts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    config = load_schema(CONFIG_SCHEMA_FILE)
    user = load_schema(USER_SCHEMA_FILE)
    merges = load_schema(MERGES_SCHEMA_FILE)
    _assert_schema_identity(
        config,
        "https://cellucid.com/contracts/community-annotation/config-v1.schema.json",
    )
    _assert_schema_identity(
        user,
        "https://cellucid.com/contracts/community-annotation/user-v1.schema.json",
    )
    _assert_schema_identity(
        merges,
        "https://cellucid.com/contracts/community-annotation/merges-v1.schema.json",
    )
    return config, user, merges


def main() -> int:
    """Validate the complete repository input set and return a process exit code."""
    errors: list[str] = []
    try:
        config_schema, user_schema, merges_schema = _load_contracts()
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        JsonInputError,
        SchemaDefinitionError,
    ) as error:
        return fail([f"annotation schema is invalid: {error}"])

    if CONFIG_FILE.is_file():
        errors.extend(_read_and_validate(CONFIG_FILE, config_schema, validate_config))
    else:
        errors.append(f"{CONFIG_FILE}: missing required file")

    if not USERS_DIR.is_dir():
        errors.append(f"{USERS_DIR}: missing required directory")
        user_paths: list[pathlib.Path] = []
    else:
        try:
            user_entries = sorted(USERS_DIR.rglob("*"))
        except OSError as error:
            errors.append(f"{USERS_DIR}: cannot list user files ({error})")
            user_entries = []
        user_paths = []
        for path in user_entries:
            if path.is_symlink():
                errors.append(f"{path}: symbolic links are not permitted")
                continue
            if path.is_dir():
                errors.append(
                    f"{path}: directories are not permitted under {USERS_DIR}"
                )
                continue
            if not path.is_file():
                errors.append(f"{path}: must be a regular file")
                continue
            if path.parent != USERS_DIR:
                errors.append(
                    f"{path}: user files must be direct children of {USERS_DIR}"
                )
                continue
            if path.name == ".gitkeep":
                try:
                    sentinel_bytes = path.read_bytes()
                except OSError as error:
                    errors.append(f"{path}: cannot inspect .gitkeep ({error})")
                    continue
                if sentinel_bytes != b"\n":
                    errors.append(
                        f"{path}: .gitkeep must contain exactly one LF byte"
                    )
                continue
            if path.suffix != ".json":
                errors.append(
                    f"{path}: only canonical user JSON files are permitted"
                )
                continue
            user_paths.append(path)
    valid_user_documents: list[tuple[pathlib.Path, Mapping[str, Any]]] = []
    for path in user_paths:
        try:
            document = read_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError, JsonInputError) as error:
            errors.append(_input_error(path, error))
            continue
        file_errors = validate_user_file(document, path, user_schema)
        errors.extend(file_errors)
        if not file_errors:
            valid_user_documents.append((path, document))
    errors.extend(validate_user_repository(valid_user_documents))

    if MERGES_FILE.exists():
        if MERGES_FILE.is_file():
            errors.extend(
                _read_and_validate(MERGES_FILE, merges_schema, validate_merges)
            )
        else:
            errors.append(f"{MERGES_FILE}: must be a regular file")

    if errors:
        return fail(errors)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
