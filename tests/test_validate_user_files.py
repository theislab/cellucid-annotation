from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from typing import Any


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts" / "validate_user_files.py"

SPEC = importlib.util.spec_from_file_location("validate_user_files", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def valid_user() -> dict[str, Any]:
    return {
        "version": 1,
        "username": "ghid_42",
        "githubUserId": 42,
        "login": "researcher",
        "displayName": "Researcher",
        "title": "Scientist",
        "orcid": "0000-0002-1825-0097",
        "linkedin": "researcher-42",
        "updatedAt": "2026-07-25T00:00:00Z",
        "datasets": {
            "synthetic": {
                "fieldsToAnnotate": ["cell_type"],
                "lastAccessedAt": "2026-07-25T00:00:00Z",
            }
        },
        "suggestions": {
            "cell_type:T": [
                {
                    "id": "suggestion-1",
                    "label": "T cell",
                    "ontologyId": "CL:0000084",
                    "evidence": "Synthetic evidence",
                    "markers": [
                        "CD3D",
                        {"gene": "CD3E", "logFC": 2.5, "pval": 0.001},
                    ],
                    "proposedBy": "ghid_42",
                    "proposedAt": "2026-07-25T00:00:00Z",
                    "editedAt": None,
                }
            ]
        },
        "votes": {"suggestion-1": "up"},
        "comments": {
            "suggestion-1": [
                {
                    "id": "comment-1",
                    "text": "Agreed",
                    "authorUsername": "ghid_42",
                    "createdAt": "2026-07-25T00:00:00Z",
                    "editedAt": None,
                }
            ]
        },
        "deletedSuggestions": {"cell_type:T": ["suggestion-old"]},
    }


def valid_config() -> dict[str, Any]:
    return {
        "version": 1,
        "supportedDatasets": [
            {
                "datasetId": "synthetic",
                "name": "Synthetic",
                "fieldsToAnnotate": ["cell_type"],
                "annotatableSettings": {
                    "cell_type": {"minAnnotators": 1, "threshold": 0.5}
                },
                "closedFields": [],
            }
        ],
    }


def valid_merges() -> dict[str, Any]:
    return {
        "version": 1,
        "updatedAt": "2026-07-25T00:00:00Z",
        "merges": [
            {
                "bucket": "cell_type:T",
                "fromSuggestionId": "suggestion-1",
                "intoSuggestionId": "suggestion-2",
                "by": "ghid_99",
                "at": "2026-07-25T00:00:00Z",
                "note": "Same biological population",
                "editedAt": None,
            }
        ],
    }


class ExactContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.user_schema = validator.load_schema(
            REPOSITORY_ROOT / "annotations" / "schema.json"
        )
        cls.config_schema = validator.load_schema(
            REPOSITORY_ROOT / "annotations" / "config.schema.json"
        )
        cls.merges_schema = validator.load_schema(
            REPOSITORY_ROOT / "annotations" / "moderation" / "merges.schema.json"
        )

    def test_shipped_contract_surfaces_contain_only_current_language(self) -> None:
        retired_language = re.compile(
            r"\bfallback\b|fall(?:ing)?[\s-]+back|best[\s_-]*effort|"
            r"\blegacy\b|\bdeprecated\b|deprecation|"
            r"backwards?[\s_-]*compat|\bshim\b",
            re.IGNORECASE,
        )
        files = [
            REPOSITORY_ROOT / "README.md",
            REPOSITORY_ROOT / "annotations" / "schema.json",
            REPOSITORY_ROOT / "annotations" / "config.schema.json",
            REPOSITORY_ROOT / "annotations" / "config.json",
            REPOSITORY_ROOT / "annotations" / "moderation" / "merges.schema.json",
            *sorted((REPOSITORY_ROOT / "scripts").glob("*.py")),
            *sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml")),
            *sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yaml")),
        ]
        violations: list[str] = []
        for path in files:
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if retired_language.search(line):
                    violations.append(
                        f"{path.relative_to(REPOSITORY_ROOT)}:{line_number}: "
                        f"{line.strip()}"
                    )
        self.assertEqual(violations, [])

    def test_readme_cross_references_the_current_cellucid_ecosystem(self) -> None:
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        for url in (
            (
                "https://cellucid.readthedocs.io/en/latest/user_guide/web_app/"
                "j_community_annotation/index.html"
            ),
            "https://github.com/theislab/cellucid",
            "https://github.com/theislab/cellucid-python",
            "https://github.com/theislab/cellucid-r",
            "https://github.com/theislab/cellucid-datasets",
            "https://github.com/theislab/cellucid-demo-custom-datasets",
        ):
            self.assertIn(url, readme)

    def test_readme_documents_the_exact_identity_reservations(self) -> None:
        readme = " ".join(
            (REPOSITORY_ROOT / "README.md")
            .read_text(encoding="utf-8")
            .split()
        )
        self.assertIn(
            "starts with exact lowercase `fk~` and contains `%3A` or `%3a`",
            readme,
        )
        self.assertIn(
            "Suggestion ids cannot contain `:` because Cellucid reserves that "
            "character as the delimiter",
            readme,
        )

    def test_repository_checkout_preserves_the_exact_lf_sentinel(self) -> None:
        result = subprocess.run(
            [
                "git",
                "check-attr",
                "text",
                "eol",
                "--",
                "annotations/users/.gitkeep",
            ],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "annotations/users/.gitkeep: text: set",
                "annotations/users/.gitkeep: eol: lf",
            ],
        )
        workflow_lines = (
            (REPOSITORY_ROOT / ".github" / "workflows" / "validate.yml")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        self.assertEqual(
            sum(line.strip() == '- ".gitattributes"' for line in workflow_lines),
            2,
        )
        self.assertEqual(
            sum(line.strip() == '- "README.md"' for line in workflow_lines),
            2,
        )

    def user_errors(self, doc: Any, filename: str = "ghid_42.json") -> list[str]:
        return validator.validate_user_file(
            doc,
            pathlib.Path("annotations") / "users" / filename,
            self.user_schema,
        )

    def schema_pattern_slots(self) -> tuple[tuple[str, dict[str, Any]], ...]:
        slots: list[tuple[str, dict[str, Any]]] = []

        def visit(value: Any, location: tuple[str, ...]) -> None:
            if isinstance(value, dict):
                if "pattern" in value:
                    slots.append((".".join(location), value))
                for key, child in value.items():
                    visit(child, (*location, str(key)))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, (*location, str(index)))

        for name, schema in (
            ("config", self.config_schema),
            ("user", self.user_schema),
            ("merges", self.merges_schema),
        ):
            visit(schema, (name,))
        return tuple(slots)

    def field_key_surface_errors(self, surface: str, value: str) -> list[str]:
        if surface == "datasets.fieldsToAnnotate":
            document = valid_user()
            document["datasets"]["synthetic"]["fieldsToAnnotate"] = [value]
            return self.user_errors(document)

        document = valid_config()
        dataset = document["supportedDatasets"][0]
        if surface == "fieldsToAnnotate":
            dataset["fieldsToAnnotate"] = [value]
        elif surface == "annotatableSettings":
            dataset["annotatableSettings"] = {
                value: {"minAnnotators": 1, "threshold": 0.5}
            }
        elif surface == "closedFields":
            dataset["closedFields"] = [value]
        else:
            raise AssertionError(f"unknown field-key surface {surface!r}")
        return validator.validate_config(
            document,
            pathlib.Path("annotations/config.json"),
            self.config_schema,
        )

    def suggestion_id_surface_errors(self, surface: str, value: str) -> list[str]:
        if surface in {
            "suggestions.id",
            "votes",
            "comments",
            "deletedSuggestions",
        }:
            document = valid_user()
            if surface == "suggestions.id":
                document["suggestions"]["cell_type:T"][0]["id"] = value
            elif surface == "votes":
                document["votes"] = {value: "up"}
            elif surface == "comments":
                document["comments"] = {
                    value: document["comments"]["suggestion-1"]
                }
            else:
                document["deletedSuggestions"] = {"cell_type:T": [value]}
            return self.user_errors(document)

        document = valid_merges()
        if surface == "fromSuggestionId":
            document["merges"][0]["fromSuggestionId"] = value
        elif surface == "intoSuggestionId":
            document["merges"][0]["intoSuggestionId"] = value
        else:
            raise AssertionError(f"unknown suggestion-id surface {surface!r}")
        return validator.validate_merges(
            document,
            pathlib.Path("annotations/moderation/merges.json"),
            self.merges_schema,
        )

    def bucket_surface_errors(self, surface: str, value: str) -> list[str]:
        if surface in {"suggestions", "deletedSuggestions"}:
            document = valid_user()
            if surface == "suggestions":
                suggestions = document["suggestions"].pop("cell_type:T")
                document["suggestions"][value] = suggestions
            else:
                document["deletedSuggestions"] = {value: ["suggestion-old"]}
            return self.user_errors(document)

        if surface != "merges.bucket":
            raise AssertionError(f"unknown bucket surface {surface!r}")
        document = valid_merges()
        document["merges"][0]["bucket"] = value
        return validator.validate_merges(
            document,
            pathlib.Path("annotations/moderation/merges.json"),
            self.merges_schema,
        )

    def test_complete_valid_user_file(self) -> None:
        self.assertEqual(self.user_errors(valid_user()), [])

    def test_orcid_requires_one_canonical_checksum_valid_representation(self) -> None:
        for value in (
            "https://orcid.org/0000-0002-1825-0097",
            "0000000218250097",
            "0000-0002-1825-0098",
            " 0000-0002-1825-0097",
        ):
            with self.subTest(value=value):
                document = valid_user()
                document["orcid"] = value
                self.assertTrue(
                    any(
                        "orcid" in error.lower() for error in self.user_errors(document)
                    )
                )

    def test_unknown_fields_are_rejected_at_every_object_layer(self) -> None:
        documents: list[dict[str, Any]] = []

        top = valid_user()
        top["unknown"] = True
        documents.append(top)

        dataset = valid_user()
        dataset["datasets"]["synthetic"]["unknown"] = True
        documents.append(dataset)

        suggestion = valid_user()
        suggestion["suggestions"]["cell_type:T"][0]["unknown"] = True
        documents.append(suggestion)

        marker = valid_user()
        marker["suggestions"]["cell_type:T"][0]["markers"][1]["unknown"] = True
        documents.append(marker)

        comment = valid_user()
        comment["comments"]["suggestion-1"][0]["unknown"] = True
        documents.append(comment)

        for document in documents:
            with self.subTest(document=document):
                errors = self.user_errors(document)
                self.assertTrue(
                    any("unknown field 'unknown'" in error for error in errors)
                )

    def test_wrong_json_types_are_not_coerced(self) -> None:
        mutations = (
            ("version", True),
            ("username", 42),
            ("githubUserId", "42"),
            ("updatedAt", 123),
            ("suggestions", []),
            ("votes", []),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                document = valid_user()
                document[key] = value
                errors = self.user_errors(document)
                self.assertTrue(any("must have JSON type" in error for error in errors))

        document = valid_user()
        document["suggestions"]["cell_type:T"][0]["label"] = 7
        self.assertTrue(
            any(
                "must have JSON type string" in error
                for error in self.user_errors(document)
            )
        )

    def test_schema_integer_semantics_match_browser_json_numbers(self) -> None:
        document = valid_user()
        document["version"] = 1.0
        document["githubUserId"] = 42.0
        self.assertEqual(self.user_errors(document), [])

    def test_all_user_timestamps_use_exact_valid_utc_machine_format(self) -> None:
        document = valid_user()
        document["updatedAt"] = "2026-07-25T01:02:03.456Z"
        document["datasets"]["synthetic"]["lastAccessedAt"] = "2026-07-25T01:02:03.456Z"
        suggestion = document["suggestions"]["cell_type:T"][0]
        suggestion["proposedAt"] = "2026-07-25T01:02:03.456Z"
        suggestion["editedAt"] = "2026-07-25T01:02:03.456Z"
        comment = document["comments"]["suggestion-1"][0]
        comment["createdAt"] = "2026-07-25T01:02:03.456Z"
        comment["editedAt"] = "2026-07-25T01:02:03.456Z"
        self.assertEqual(self.user_errors(document), [])

        invalid_values = (
            "2026-02-29T01:02:03Z",
            "2026-07-25T24:02:03Z",
            "2026-07-25T01:02:03+00:00",
            "2026-07-25T01:02:03.12Z",
            "2026-07-25t01:02:03z",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                invalid = valid_user()
                invalid["updatedAt"] = value
                self.assertTrue(
                    any(
                        "must be a valid UTC date-time" in error
                        for error in self.user_errors(invalid)
                    )
                )

        invalid_locations = (
            lambda item: item["datasets"]["synthetic"].__setitem__(
                "lastAccessedAt", "2026-02-30T00:00:00Z"
            ),
            lambda item: item["suggestions"]["cell_type:T"][0].__setitem__(
                "proposedAt", "2026-02-30T00:00:00Z"
            ),
            lambda item: item["suggestions"]["cell_type:T"][0].__setitem__(
                "editedAt", "2026-02-30T00:00:00Z"
            ),
            lambda item: item["comments"]["suggestion-1"][0].__setitem__(
                "createdAt", "2026-02-30T00:00:00Z"
            ),
            lambda item: item["comments"]["suggestion-1"][0].__setitem__(
                "editedAt", "2026-02-30T00:00:00Z"
            ),
        )
        for mutate in invalid_locations:
            invalid = valid_user()
            mutate(invalid)
            self.assertTrue(
                any(
                    "must be a valid UTC date-time" in error
                    for error in self.user_errors(invalid)
                )
            )

    def test_every_suggestion_after_item_500_is_validated(self) -> None:
        document = valid_user()
        item = document["suggestions"]["cell_type:T"][0]
        document["suggestions"]["cell_type:T"] = [
            copy.deepcopy(item) for _ in range(501)
        ]
        document["suggestions"]["cell_type:T"][500]["label"] = 7
        errors = self.user_errors(document)
        self.assertTrue(any("[500]" in error and "label" in error for error in errors))

    def test_every_nested_tail_item_is_validated(self) -> None:
        document = valid_user()
        suggestion = document["suggestions"]["cell_type:T"][0]
        suggestion["markers"] = ["CD3D" for _ in range(201)]
        suggestion["markers"][200] = 7
        comment = document["comments"]["suggestion-1"][0]
        document["comments"]["suggestion-1"] = [
            copy.deepcopy(comment) for _ in range(101)
        ]
        document["comments"]["suggestion-1"][100]["text"] = 7
        errors = self.user_errors(document)
        self.assertTrue(
            any("[200]" in error and "markers" in error for error in errors)
        )
        self.assertTrue(
            any("[100]" in error and "comments" in error for error in errors)
        )

    def test_filename_and_embedded_identity_must_match_exactly(self) -> None:
        for filename in ("alice.json", "ghid_0042.json", "ghid_999.json"):
            with self.subTest(filename=filename):
                errors = self.user_errors(valid_user(), filename)
                self.assertTrue(
                    any(
                        "filename must be exactly 'ghid_42.json'" in error
                        for error in errors
                    )
                )

        document = valid_user()
        document["username"] = "researcher"
        self.assertTrue(
            any(
                "$[\"username\"] must equal 'ghid_42'" in error
                for error in self.user_errors(document)
            )
        )

    def test_config_schema_and_relationships_are_exact(self) -> None:
        self.assertEqual(
            validator.validate_config(
                valid_config(),
                pathlib.Path("annotations/config.json"),
                self.config_schema,
            ),
            [],
        )

        unknown = valid_config()
        unknown["unknown"] = True
        self.assertTrue(
            any(
                "unknown field 'unknown'" in error
                for error in validator.validate_config(
                    unknown,
                    pathlib.Path("annotations/config.json"),
                    self.config_schema,
                )
            )
        )

        wrong_type = valid_config()
        wrong_type["supportedDatasets"][0]["annotatableSettings"]["cell_type"][
            "threshold"
        ] = True
        self.assertTrue(
            any(
                "must have JSON type number" in error
                for error in validator.validate_config(
                    wrong_type,
                    pathlib.Path("annotations/config.json"),
                    self.config_schema,
                )
            )
        )

        wrong_field = valid_config()
        wrong_field["supportedDatasets"][0]["closedFields"] = ["other"]
        self.assertTrue(
            any(
                "is not in fieldsToAnnotate" in error
                for error in validator.validate_config(
                    wrong_field,
                    pathlib.Path("annotations/config.json"),
                    self.config_schema,
                )
            )
        )

    def test_config_requires_complete_current_dataset_and_settings_shape(self) -> None:
        required_dataset_fields = (
            "datasetId",
            "name",
            "fieldsToAnnotate",
            "annotatableSettings",
            "closedFields",
        )
        for field in required_dataset_fields:
            with self.subTest(field=field):
                document = valid_config()
                del document["supportedDatasets"][0][field]
                errors = validator.validate_config(
                    document,
                    pathlib.Path("annotations/config.json"),
                    self.config_schema,
                )
                self.assertTrue(
                    any(
                        f"missing required field '{field}'" in error for error in errors
                    )
                )

        for field in ("minAnnotators", "threshold"):
            with self.subTest(setting=field):
                document = valid_config()
                del document["supportedDatasets"][0]["annotatableSettings"][
                    "cell_type"
                ][field]
                errors = validator.validate_config(
                    document,
                    pathlib.Path("annotations/config.json"),
                    self.config_schema,
                )
                self.assertTrue(
                    any(
                        f"missing required field '{field}'" in error for error in errors
                    )
                )

        document = valid_config()
        document["supportedDatasets"][0]["fieldsToAnnotate"] = []
        errors = validator.validate_config(
            document,
            pathlib.Path("annotations/config.json"),
            self.config_schema,
        )
        self.assertTrue(
            any("must contain at least 1 item" in error for error in errors)
        )

        document = valid_config()
        document["supportedDatasets"][0]["name"] = "   "
        errors = validator.validate_config(
            document,
            pathlib.Path("annotations/config.json"),
            self.config_schema,
        )
        self.assertTrue(any("must match pattern" in error for error in errors))

    def test_every_config_field_after_item_500_is_validated(self) -> None:
        document = valid_config()
        document["supportedDatasets"][0]["fieldsToAnnotate"] = [
            f"field_{index}" for index in range(500)
        ] + [7]
        errors = validator.validate_config(
            document,
            pathlib.Path("annotations/config.json"),
            self.config_schema,
        )
        self.assertTrue(
            any("[500]" in error and "fieldsToAnnotate" in error for error in errors)
        )

    def test_every_merge_and_merge_shape_is_validated(self) -> None:
        self.assertEqual(
            validator.validate_merges(
                valid_merges(),
                pathlib.Path("annotations/moderation/merges.json"),
                self.merges_schema,
            ),
            [],
        )

        document = valid_merges()
        item = document["merges"][0]
        document["merges"] = [copy.deepcopy(item) for _ in range(10001)]
        document["merges"][10000]["unknown"] = True
        errors = validator.validate_merges(
            document,
            pathlib.Path("annotations/moderation/merges.json"),
            self.merges_schema,
        )
        self.assertTrue(
            any("[10000]" in error and "unknown field" in error for error in errors)
        )

        same_target = valid_merges()
        same_target["merges"][0]["intoSuggestionId"] = "suggestion-1"
        errors = validator.validate_merges(
            same_target,
            pathlib.Path("annotations/moderation/merges.json"),
            self.merges_schema,
        )
        self.assertTrue(any("must differ" in error for error in errors))

    def test_all_merge_timestamps_use_exact_valid_utc_machine_format(self) -> None:
        document = valid_merges()
        document["updatedAt"] = "2026-07-25T01:02:03.456Z"
        document["merges"][0]["at"] = "2026-07-25T01:02:03.456Z"
        document["merges"][0]["editedAt"] = "2026-07-25T01:02:03.456Z"
        self.assertEqual(
            validator.validate_merges(
                document,
                pathlib.Path("annotations/moderation/merges.json"),
                self.merges_schema,
            ),
            [],
        )

        invalid = valid_merges()
        invalid["updatedAt"] = "2026-02-30T00:00:00Z"
        errors = validator.validate_merges(
            invalid,
            pathlib.Path("annotations/moderation/merges.json"),
            self.merges_schema,
        )
        self.assertTrue(
            any("must be a valid UTC date-time" in error for error in errors)
        )

        for field in ("at", "editedAt"):
            with self.subTest(field=field):
                invalid = valid_merges()
                invalid["merges"][0][field] = "2026-02-30T00:00:00Z"
                errors = validator.validate_merges(
                    invalid,
                    pathlib.Path("annotations/moderation/merges.json"),
                    self.merges_schema,
                )
                self.assertTrue(
                    any("must be a valid UTC date-time" in error for error in errors)
                )

    def test_user_ownership_and_ids_are_exact(self) -> None:
        wrong_owner = valid_user()
        wrong_owner["suggestions"]["cell_type:T"][0]["proposedBy"] = "ghid_7"
        wrong_owner["comments"]["suggestion-1"][0]["authorUsername"] = "ghid_7"
        errors = self.user_errors(wrong_owner)
        self.assertTrue(any("proposedBy must equal file identity" in e for e in errors))
        self.assertTrue(
            any("authorUsername must equal file identity" in e for e in errors)
        )

        duplicate = valid_user()
        duplicate["suggestions"]["cell_type:B"] = [
            copy.deepcopy(duplicate["suggestions"]["cell_type:T"][0])
        ]
        errors = self.user_errors(duplicate)
        self.assertTrue(any("must be globally unique" in e for e in errors))

    def test_repository_suggestion_ids_cannot_cross_owners_or_buckets(self) -> None:
        first = valid_user()
        second = valid_user()
        second["username"] = "ghid_7"
        second["githubUserId"] = 7
        second["suggestions"]["cell_type:T"][0]["proposedBy"] = "ghid_7"
        errors = validator.validate_user_repository(
            [
                (pathlib.Path("annotations/users/ghid_42.json"), first),
                (pathlib.Path("annotations/users/ghid_7.json"), second),
            ]
        )
        self.assertTrue(
            any("conflicts with the suggestion owned by" in e for e in errors)
        )

    def test_blank_markers_and_explicit_limits_are_rejected(self) -> None:
        blank = valid_user()
        blank["suggestions"]["cell_type:T"][0]["markers"] = ["   "]
        self.assertTrue(any("must match pattern" in e for e in self.user_errors(blank)))

        edge_whitespace = valid_user()
        edge_whitespace["suggestions"]["cell_type:T"][0]["markers"] = [" CD3D"]
        self.assertTrue(
            any(
                "must match pattern" in error
                for error in self.user_errors(edge_whitespace)
            )
        )

        over_limit = valid_user()
        over_limit["suggestions"]["cell_type:T"][0]["markers"] = [
            f"G{index}" for index in range(51)
        ]
        self.assertTrue(
            any(
                "must contain at most 50 item" in e
                for e in self.user_errors(over_limit)
            )
        )

        unicode_boundary = valid_user()
        unicode_boundary["suggestions"]["cell_type:T"][0]["label"] = "😀" * 120
        self.assertEqual(self.user_errors(unicode_boundary), [])

        unicode_over_limit = valid_user()
        unicode_over_limit["suggestions"]["cell_type:T"][0]["label"] = "😀" * 121
        self.assertTrue(
            any(
                "at most 120 character" in error
                for error in self.user_errors(unicode_over_limit)
            )
        )

    def test_config_settings_cover_fields_exactly(self) -> None:
        missing = valid_config()
        missing["supportedDatasets"][0]["fieldsToAnnotate"].append("batch")
        errors = validator.validate_config(
            missing,
            pathlib.Path("annotations/config.json"),
            self.config_schema,
        )
        self.assertTrue(
            any("is missing settings for field 'batch'" in e for e in errors)
        )

        extra = valid_config()
        extra["supportedDatasets"][0]["annotatableSettings"]["batch"] = {
            "minAnnotators": 1,
            "threshold": 0.5,
        }
        errors = validator.validate_config(
            extra,
            pathlib.Path("annotations/config.json"),
            self.config_schema,
        )
        self.assertTrue(any("is not in fieldsToAnnotate" in e for e in errors))

    def test_field_keys_reject_only_the_ambiguous_encoded_prefix_shape(self) -> None:
        accepted_field_keys = (
            "fk~foo",
            "plain%3Afoo",
            "fk~foo%253Abar",
            "fk~literal%3A:real-colon",
            "FK~foo%3Abar",
        )
        for field_key in accepted_field_keys:
            with self.subTest(field_key=field_key):
                config = valid_config()
                dataset = config["supportedDatasets"][0]
                dataset["fieldsToAnnotate"] = [field_key]
                dataset["annotatableSettings"] = {
                    field_key: {"minAnnotators": 1, "threshold": 0.5}
                }
                dataset["closedFields"] = [field_key]
                self.assertEqual(
                    validator.validate_config(
                        config,
                        pathlib.Path("annotations/config.json"),
                        self.config_schema,
                    ),
                    [],
                )

                user = valid_user()
                user["datasets"]["synthetic"]["fieldsToAnnotate"] = [field_key]
                self.assertEqual(self.user_errors(user), [])

        for field_key in ("fk~foo%3Abar", "fk~foo%3abar"):
            with self.subTest(field_key=field_key):
                config = valid_config()
                dataset = config["supportedDatasets"][0]
                dataset["fieldsToAnnotate"] = [field_key]
                dataset["annotatableSettings"] = {
                    field_key: {"minAnnotators": 1, "threshold": 0.5}
                }
                dataset["closedFields"] = [field_key]
                config_errors = validator.validate_config(
                    config,
                    pathlib.Path("annotations/config.json"),
                    self.config_schema,
                )
                pattern_errors = [
                    error
                    for error in config_errors
                    if "must match pattern" in error
                ]
                self.assertEqual(len(pattern_errors), 3)
                for boundary in (
                    "fieldsToAnnotate",
                    "annotatableSettings",
                    "closedFields",
                ):
                    self.assertTrue(
                        any(boundary in error for error in pattern_errors),
                        (boundary, pattern_errors),
                    )

                user = valid_user()
                user["datasets"]["synthetic"]["fieldsToAnnotate"] = [field_key]
                self.assertTrue(
                    any(
                        "must match pattern" in error
                        for error in self.user_errors(user)
                    )
                )

    def test_field_key_surfaces_reject_every_trailing_line_terminator(self) -> None:
        surfaces = (
            "fieldsToAnnotate",
            "annotatableSettings",
            "closedFields",
            "datasets.fieldsToAnnotate",
        )
        line_terminators = ("\n", "\r", "\r\n", "\u2028", "\u2029")
        for surface in surfaces:
            for terminator in line_terminators:
                with self.subTest(surface=surface, terminator=repr(terminator)):
                    errors = self.field_key_surface_errors(
                        surface,
                        f"cell_type{terminator}",
                    )
                    self.assertTrue(
                        any(
                            surface.rsplit(".", 1)[-1] in error
                            and "must match pattern" in error
                            for error in errors
                        ),
                        errors,
                    )

    def test_bucket_surfaces_reject_every_trailing_line_terminator(self) -> None:
        surfaces = ("suggestions", "deletedSuggestions", "merges.bucket")
        line_terminators = ("\n", "\r", "\r\n", "\u2028", "\u2029")
        for surface in surfaces:
            for terminator in line_terminators:
                with self.subTest(surface=surface, terminator=repr(terminator)):
                    errors = self.bucket_surface_errors(
                        surface,
                        f"cell_type:T{terminator}",
                    )
                    self.assertTrue(
                        any("must match pattern" in error for error in errors),
                        errors,
                    )

    def test_encoded_bucket_fields_and_colon_bearing_categories_remain_valid(
        self,
    ) -> None:
        document = valid_user()
        suggestion = document["suggestions"].pop("cell_type:T")[0]
        document["suggestions"]["fk~celltype%3Acoarse:T:activated"] = [suggestion]
        document["deletedSuggestions"] = {
            "fk~celltype%3Acoarse:T:activated": ["suggestion-old"]
        }
        self.assertEqual(self.user_errors(document), [])

        merges = valid_merges()
        merges["merges"][0]["bucket"] = "fk~celltype%3Acoarse:T:activated"
        self.assertEqual(
            validator.validate_merges(
                merges,
                pathlib.Path("annotations/moderation/merges.json"),
                self.merges_schema,
            ),
            [],
        )

    def test_identity_surfaces_preserve_internal_line_terminators(
        self,
    ) -> None:
        line_terminators = ("\n", "\r", "\r\n", "\u2028", "\u2029")
        suggestion_id_surfaces = (
            "suggestions.id",
            "votes",
            "comments",
            "deletedSuggestions",
            "fromSuggestionId",
            "intoSuggestionId",
        )
        for terminator in line_terminators:
            with self.subTest(identity="field-key", terminator=repr(terminator)):
                field_key = f"cell{terminator}type"
                config = valid_config()
                dataset = config["supportedDatasets"][0]
                dataset["fieldsToAnnotate"] = [field_key]
                dataset["annotatableSettings"] = {
                    field_key: {"minAnnotators": 1, "threshold": 0.5}
                }
                dataset["closedFields"] = [field_key]
                self.assertEqual(
                    validator.validate_config(
                        config,
                        pathlib.Path("annotations/config.json"),
                        self.config_schema,
                    ),
                    [],
                )

                user = valid_user()
                user["datasets"]["synthetic"]["fieldsToAnnotate"] = [field_key]
                self.assertEqual(self.user_errors(user), [])

            for surface in ("suggestions", "deletedSuggestions", "merges.bucket"):
                for bucket in (
                    f"cell{terminator}type:T",
                    f"cell_type:T{terminator}activated",
                ):
                    with self.subTest(
                        identity=surface,
                        terminator=repr(terminator),
                        bucket=bucket,
                    ):
                        self.assertEqual(
                            self.bucket_surface_errors(surface, bucket),
                            [],
                        )

            for surface in suggestion_id_surfaces:
                with self.subTest(
                    identity=surface,
                    terminator=repr(terminator),
                ):
                    self.assertEqual(
                        self.suggestion_id_surface_errors(
                            surface,
                            f"suggestion{terminator}id",
                        ),
                        [],
                    )

    def test_suggestion_id_surfaces_reject_every_trailing_line_terminator(
        self,
    ) -> None:
        surfaces = (
            "suggestions.id",
            "votes",
            "comments",
            "deletedSuggestions",
            "fromSuggestionId",
            "intoSuggestionId",
        )
        line_terminators = ("\n", "\r", "\r\n", "\u2028", "\u2029")
        for surface in surfaces:
            for terminator in line_terminators:
                with self.subTest(surface=surface, terminator=repr(terminator)):
                    errors = self.suggestion_id_surface_errors(
                        surface,
                        f"suggestion{terminator}",
                    )
                    self.assertTrue(
                        any("must match pattern" in error for error in errors),
                        errors,
                    )

    def test_suggestion_ids_cannot_contain_colons_at_any_boundary_or_position(
        self,
    ) -> None:
        surfaces = (
            "suggestions.id",
            "votes",
            "comments",
            "deletedSuggestions",
            "fromSuggestionId",
            "intoSuggestionId",
        )
        values = (":suggestion", "sug:gestion", "suggestion:")
        for surface in surfaces:
            for value in values:
                with self.subTest(surface=surface, value=value):
                    errors = self.suggestion_id_surface_errors(surface, value)
                    self.assertTrue(
                        any("must match pattern" in error for error in errors),
                        errors,
                    )

    def test_non_delimiter_colons_and_encoded_text_remain_valid(self) -> None:
        document = valid_user()
        suggestion = document["suggestions"]["cell_type:T"][0]
        suggestion["id"] = "suggestion%3A1"
        suggestion["label"] = "T: activated"
        suggestion["ontologyId"] = "CL:0000084"
        document["votes"] = {"suggestion%3A1": "up"}
        document["comments"] = {
            "suggestion%3A1": [
                {
                    **document["comments"]["suggestion-1"][0],
                    "id": "comment:1",
                }
            ]
        }
        document["deletedSuggestions"] = {
            "cell_type:T:activated": ["suggestion%3Aold"]
        }
        self.assertEqual(self.user_errors(document), [])

    def test_merge_mapping_is_unique_and_acyclic(self) -> None:
        duplicate = valid_merges()
        duplicate["merges"].append(
            {
                **duplicate["merges"][0],
                "intoSuggestionId": "suggestion-3",
            }
        )
        errors = validator.validate_merges(
            duplicate,
            pathlib.Path("annotations/moderation/merges.json"),
            self.merges_schema,
        )
        self.assertTrue(any("duplicates the bucket/from mapping" in e for e in errors))

        cycle = valid_merges()
        cycle["merges"].append(
            {
                "bucket": "cell_type:T",
                "fromSuggestionId": "suggestion-2",
                "intoSuggestionId": "suggestion-1",
                "by": "ghid_99",
                "at": "2026-07-25T00:00:01Z",
            }
        )
        errors = validator.validate_merges(
            cycle,
            pathlib.Path("annotations/moderation/merges.json"),
            self.merges_schema,
        )
        self.assertTrue(any("contain a cycle" in e for e in errors))

    def test_checked_in_schema_identities_are_exact(self) -> None:
        config, user, merges = validator._load_contracts()
        self.assertEqual(
            user["$id"],
            "https://cellucid.com/contracts/community-annotation/user-v1.schema.json",
        )
        self.assertEqual(
            config["$id"],
            "https://cellucid.com/contracts/community-annotation/config-v1.schema.json",
        )
        self.assertEqual(
            merges["$id"],
            "https://cellucid.com/contracts/community-annotation/merges-v1.schema.json",
        )

    def test_identity_schema_slots_use_true_end_assertions(self) -> None:
        field_pattern = (
            r"^(?!fk~[^:]*%3[Aa][^:]*$(?![\s\S]))"
            r"\S(?:[\s\S]*\S)?$(?![\s\S])"
        )
        config_properties = self.config_schema["properties"]["supportedDatasets"][
            "items"
        ]["properties"]
        field_slots = (
            config_properties["fieldsToAnnotate"]["items"]["pattern"],
            config_properties["annotatableSettings"]["propertyNames"]["pattern"],
            config_properties["closedFields"]["items"]["pattern"],
            self.user_schema["properties"]["datasets"]["additionalProperties"][
                "properties"
            ]["fieldsToAnnotate"]["items"]["pattern"],
        )
        self.assertEqual(field_slots, (field_pattern,) * 4)

        suggestion_id_pattern = r"^[^:\s](?:[^:]*[^:\s])?$(?![\s\S])"
        user_properties = self.user_schema["properties"]
        suggestion_id_slots = (
            user_properties["suggestions"]["additionalProperties"]["items"][
                "properties"
            ]["id"]["pattern"],
            user_properties["votes"]["propertyNames"]["pattern"],
            user_properties["comments"]["propertyNames"]["pattern"],
            user_properties["deletedSuggestions"]["additionalProperties"]["items"][
                "pattern"
            ],
            self.merges_schema["properties"]["merges"]["items"]["properties"][
                "fromSuggestionId"
            ]["pattern"],
            self.merges_schema["properties"]["merges"]["items"]["properties"][
                "intoSuggestionId"
            ]["pattern"],
        )
        self.assertEqual(suggestion_id_slots, (suggestion_id_pattern,) * 6)

        bucket_pattern = (
            r"^[^:\s](?:[^:]*[^:\s])?:"
            r"\S(?:[\s\S]*\S)?$(?![\s\S])"
        )
        bucket_slots = (
            user_properties["suggestions"]["propertyNames"]["pattern"],
            user_properties["deletedSuggestions"]["propertyNames"]["pattern"],
            self.merges_schema["properties"]["merges"]["items"]["properties"][
                "bucket"
            ]["pattern"],
        )
        self.assertEqual(bucket_slots, (bucket_pattern,) * 3)

    def test_remaining_pattern_inventory_uses_only_portable_true_end_forms(
        self,
    ) -> None:
        free_text = r"^\S(?:[\s\S]*\S)?$"
        utc_date_time = (
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
            r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(\.[0-9]{3})?Z$"
        )
        github_identity = r"^ghid_[1-9][0-9]*$"
        orcid = r"^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$"
        linkedin = r"^[a-z0-9-]{3,120}$"
        expected_counts = {
            free_text: 15,
            utc_date_time: 9,
            github_identity: 3,
            orcid: 1,
            linkedin: 1,
        }
        true_end = r"(?![\s\S])"
        all_slots = self.schema_pattern_slots()
        refinement_slots = [
            (location, schema, schema["pattern"].removesuffix(true_end))
            for location, schema in all_slots
            if schema["pattern"].removesuffix(true_end) in expected_counts
        ]

        self.assertEqual(len(all_slots), 42)
        self.assertEqual(len(refinement_slots), 29)
        self.assertEqual(len(all_slots) - len(refinement_slots), 13)
        self.assertEqual(
            {
                pattern: sum(
                    normalized == pattern
                    for _, _, normalized in refinement_slots
                )
                for pattern in expected_counts
            },
            expected_counts,
        )
        for location, schema, normalized in refinement_slots:
            with self.subTest(location=location):
                self.assertEqual(schema["pattern"], f"{normalized}{true_end}")

    def test_remaining_patterns_reject_every_final_line_terminator(self) -> None:
        true_end = r"(?![\s\S])"
        examples = {
            r"^\S(?:[\s\S]*\S)?$": "Example",
            (
                r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
                r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
                r"(\.[0-9]{3})?Z$"
            ): "2026-07-25T01:02:03.456Z",
            r"^ghid_[1-9][0-9]*$": "ghid_42",
            r"^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$": (
                "0000-0002-1825-0097"
            ),
            r"^[a-z0-9-]{3,120}$": "researcher-42",
        }
        line_terminators = ("\n", "\r", "\r\n", "\u2028", "\u2029")
        refinement_slots = [
            (location, schema, schema["pattern"].removesuffix(true_end))
            for location, schema in self.schema_pattern_slots()
            if schema["pattern"].removesuffix(true_end) in examples
        ]

        self.assertEqual(len(refinement_slots), 29)
        for location, schema, normalized in refinement_slots:
            example = examples[normalized]
            self.assertEqual(
                validator._schema_errors(example, schema, "$"),
                [],
                location,
            )
            for terminator in line_terminators:
                with self.subTest(
                    location=location,
                    terminator=repr(terminator),
                ):
                    value = f"{example}{terminator}"
                    self.assertIsNone(re.search(schema["pattern"], value))
                    self.assertTrue(
                        any(
                            "must match pattern" in error
                            for error in validator._schema_errors(
                                value,
                                schema,
                                "$",
                            )
                        )
                    )

    def test_free_text_patterns_preserve_internal_terminators_and_lengths(
        self,
    ) -> None:
        free_text = r"^\S(?:[\s\S]*\S)?$"
        true_end = r"(?![\s\S])"
        free_text_slots = [
            (location, schema)
            for location, schema in self.schema_pattern_slots()
            if schema["pattern"].removesuffix(true_end) == free_text
        ]
        self.assertEqual(len(free_text_slots), 15)

        for location, schema in free_text_slots:
            maximum = schema["maxLength"]
            self.assertEqual(
                validator._schema_errors("x" * maximum, schema, "$"),
                [],
                location,
            )
            self.assertTrue(
                any(
                    f"at most {maximum} character" in error
                    for error in validator._schema_errors(
                        "x" * (maximum + 1),
                        schema,
                        "$",
                    )
                ),
                location,
            )
            for terminator in ("\n", "\r", "\r\n", "\u2028", "\u2029"):
                with self.subTest(
                    location=location,
                    terminator=repr(terminator),
                ):
                    self.assertEqual(
                        validator._schema_errors(
                            f"left{terminator}right",
                            schema,
                            "$",
                        ),
                        [],
                    )

        linkedin_slot = next(
            schema
            for location, schema in self.schema_pattern_slots()
            if location == "user.properties.linkedin"
        )
        for value in ("abc", "a" * 120):
            self.assertEqual(validator._schema_errors(value, linkedin_slot, "$"), [])
        for value in ("ab", "a" * 121):
            self.assertTrue(
                any(
                    "must match pattern" in error
                    for error in validator._schema_errors(
                        value,
                        linkedin_slot,
                        "$",
                    )
                )
            )

    def test_strict_json_reader_rejects_duplicate_keys_and_nonfinite_numbers(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = pathlib.Path(raw_directory)
            duplicate = directory / "duplicate.json"
            duplicate.write_text('{"version": 1, "version": 1}', encoding="utf-8")
            with self.assertRaisesRegex(
                validator.JsonInputError, "duplicate JSON object key"
            ):
                validator.read_json(duplicate)

            nonfinite = directory / "nonfinite.json"
            nonfinite.write_text('{"value": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(
                validator.JsonInputError, "not a valid JSON number"
            ):
                validator.read_json(nonfinite)

    def test_schema_loader_rejects_unimplemented_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path = pathlib.Path(raw_directory) / "schema.json"
            path.write_text(
                json.dumps({"type": "object", "unevaluatedProperties": False}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                validator.SchemaDefinitionError, "unsupported schema keyword"
            ):
                validator.load_schema(path)


class CliTests(unittest.TestCase):
    def make_repository(self, directory: pathlib.Path) -> pathlib.Path:
        annotations = directory / "annotations"
        moderation = annotations / "moderation"
        users = annotations / "users"
        scripts = directory / "scripts"
        moderation.mkdir(parents=True)
        users.mkdir()
        scripts.mkdir()

        shutil.copy2(SCRIPT, scripts / SCRIPT.name)
        shutil.copy2(
            REPOSITORY_ROOT / "annotations" / "schema.json",
            annotations / "schema.json",
        )
        shutil.copy2(
            REPOSITORY_ROOT / "annotations" / "config.schema.json",
            annotations / "config.schema.json",
        )
        shutil.copy2(
            REPOSITORY_ROOT / "annotations" / "moderation" / "merges.schema.json",
            moderation / "merges.schema.json",
        )
        (annotations / "config.json").write_text(
            json.dumps(valid_config()), encoding="utf-8"
        )
        (moderation / "merges.json").write_text(
            json.dumps(valid_merges()), encoding="utf-8"
        )
        return directory

    def run_cli(self, repository: pathlib.Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(repository / "scripts" / SCRIPT.name)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_cli_returns_zero_for_complete_valid_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            repository = self.make_repository(pathlib.Path(raw_directory))
            (repository / "annotations" / "users" / "ghid_42.json").write_text(
                json.dumps(valid_user()), encoding="utf-8"
            )
            result = self.run_cli(repository)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")

    def test_cli_enforces_the_exact_active_annotation_file_byte_boundary(
        self,
    ) -> None:
        cases = (
            (
                pathlib.Path("annotations/config.json"),
                valid_config(),
            ),
            (
                pathlib.Path("annotations/users/ghid_42.json"),
                valid_user(),
            ),
            (
                pathlib.Path("annotations/moderation/merges.json"),
                valid_merges(),
            ),
        )
        for relative_path, document in cases:
            with self.subTest(path=relative_path):
                with tempfile.TemporaryDirectory() as raw_directory:
                    repository = self.make_repository(pathlib.Path(raw_directory))
                    path = repository / relative_path
                    encoded = json.dumps(document).encode("utf-8")
                    self.assertLess(
                        len(encoded),
                        validator.ANNOTATION_FILE_MAX_UTF8_BYTES,
                    )
                    exact = encoded + b" " * (
                        validator.ANNOTATION_FILE_MAX_UTF8_BYTES - len(encoded)
                    )
                    path.write_bytes(exact)
                    accepted = self.run_cli(repository)
                    self.assertEqual(accepted.returncode, 0, accepted.stderr)

                    path.write_bytes(exact + b" ")
                    rejected = self.run_cli(repository)
                    self.assertEqual(rejected.returncode, 1)
                    self.assertIn(
                        "exceeds 1000000 bytes",
                        rejected.stderr,
                    )

    def test_cli_returns_one_and_reports_all_invalid_user_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            repository = self.make_repository(pathlib.Path(raw_directory))
            users = repository / "annotations" / "users"

            malformed = users / "ghid_7.json"
            malformed.write_text('{"version": 1', encoding="utf-8")

            document = valid_user()
            document["updatedAt"] = 123
            document["unknown"] = True
            item = document["suggestions"]["cell_type:T"][0]
            document["suggestions"]["cell_type:T"] = [
                copy.deepcopy(item) for _ in range(501)
            ]
            document["suggestions"]["cell_type:T"][500]["label"] = 7
            (users / "ghid_999.json").write_text(json.dumps(document), encoding="utf-8")

            result = self.run_cli(repository)
            self.assertEqual(result.returncode, 1)
            self.assertIn("cannot read valid JSON", result.stderr)
            self.assertIn("must have JSON type string", result.stderr)
            self.assertIn("unknown field 'unknown'", result.stderr)
            self.assertIn("[500]", result.stderr)
            self.assertIn("filename must be exactly 'ghid_42.json'", result.stderr)

    def test_cli_returns_one_for_filename_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            repository = self.make_repository(pathlib.Path(raw_directory))
            (repository / "annotations" / "users" / "alice.json").write_text(
                json.dumps(valid_user()), encoding="utf-8"
            )
            result = self.run_cli(repository)
            self.assertEqual(result.returncode, 1)
            self.assertIn("filename must be exactly 'ghid_42.json'", result.stderr)

    def test_cli_rejects_nested_user_json_instead_of_skipping_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            repository = self.make_repository(pathlib.Path(raw_directory))
            nested = repository / "annotations" / "users" / "nested"
            nested.mkdir()
            (nested / "ghid_42.json").write_text(
                json.dumps(valid_user()), encoding="utf-8"
            )
            result = self.run_cli(repository)
            self.assertEqual(result.returncode, 1)
            self.assertIn("user files must be direct children", result.stderr)

    def test_cli_rejects_every_unknown_user_directory_entry(self) -> None:
        cases = (
            ("notes.txt", "only canonical user JSON files"),
            ("GHID_42.JSON", "only canonical user JSON files"),
            ("nested", "directories are not permitted"),
        )
        for name, expected in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw_directory:
                    repository = self.make_repository(pathlib.Path(raw_directory))
                    target = repository / "annotations" / "users" / name
                    if name == "nested":
                        target.mkdir()
                    else:
                        target.write_text("unexpected", encoding="utf-8")
                    result = self.run_cli(repository)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(expected, result.stderr)

    def test_cli_requires_the_exact_repository_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            repository = self.make_repository(pathlib.Path(raw_directory))
            sentinel = repository / "annotations" / "users" / ".gitkeep"
            sentinel.write_text("not empty", encoding="utf-8")
            result = self.run_cli(repository)
            self.assertEqual(result.returncode, 1)
            self.assertIn(".gitkeep must contain exactly one LF byte", result.stderr)

    def test_cli_rejects_cross_user_suggestion_id_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            repository = self.make_repository(pathlib.Path(raw_directory))
            users = repository / "annotations" / "users"
            (users / "ghid_42.json").write_text(
                json.dumps(valid_user()), encoding="utf-8"
            )
            second = valid_user()
            second["username"] = "ghid_7"
            second["githubUserId"] = 7
            second["suggestions"]["cell_type:T"][0]["proposedBy"] = "ghid_7"
            second["comments"]["suggestion-1"][0]["authorUsername"] = "ghid_7"
            (users / "ghid_7.json").write_text(json.dumps(second), encoding="utf-8")
            result = self.run_cli(repository)
            self.assertEqual(result.returncode, 1)
            self.assertIn("conflicts with the suggestion owned by", result.stderr)

    def test_cli_rejects_incomplete_config_and_invalid_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            repository = self.make_repository(pathlib.Path(raw_directory))
            config = valid_config()
            del config["supportedDatasets"][0]["closedFields"]
            (repository / "annotations" / "config.json").write_text(
                json.dumps(config), encoding="utf-8"
            )
            user = valid_user()
            user["updatedAt"] = "2026-02-30T00:00:00Z"
            (repository / "annotations" / "users" / "ghid_42.json").write_text(
                json.dumps(user), encoding="utf-8"
            )

            result = self.run_cli(repository)
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing required field 'closedFields'", result.stderr)
            self.assertIn("must be a valid UTC date-time", result.stderr)


if __name__ == "__main__":
    unittest.main()
