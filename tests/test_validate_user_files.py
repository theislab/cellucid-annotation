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
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "validate.yml"
TESTS_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "tests.yml"

SPEC = importlib.util.spec_from_file_location("validate_user_files", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

# Every file at the repository root is text this project publishes, so the root
# is governed by exclusion rather than by naming files one at a time. The only
# exclusion is the Finder index macOS drops beside them, which is binary. Two
# rules read this: the retired-language sweep, and the check that CI actually
# runs when one of these files changes. Keeping it in one place is what stops
# those two from drifting apart.
UNGOVERNED_ROOT_FILES = {".DS_Store"}


def governed_root_files() -> list[pathlib.Path]:
    return sorted(
        path
        for path in REPOSITORY_ROOT.iterdir()
        if path.is_file() and path.name not in UNGOVERNED_ROOT_FILES
    )


def valid_user() -> dict[str, Any]:
    return {
        "version": 3,
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
                "suggestions": {
                    "cell_type:T": [
                        {
                            "id": "ghid_42_suggestion-1",
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
                "votes": {"ghid_42_suggestion-1": "up", "ghid_7_other": "down"},
                "comments": {
                    "ghid_42_suggestion-1": [
                        {
                            "id": "comment-1",
                            "text": "Agreed",
                            "authorUsername": "ghid_42",
                            "createdAt": "2026-07-25T00:00:00Z",
                            "editedAt": None,
                        }
                    ]
                },
                "deletedSuggestions": {"cell_type:T": ["ghid_42_suggestion-old"]},
            }
        },
    }


def section(document: dict[str, Any], dataset_id: str = "synthetic") -> dict[str, Any]:
    """One dataset's section of a user file."""
    return document["datasets"][dataset_id]


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
        "version": 3,
        "updatedAt": "2026-07-25T00:00:00Z",
        "merges": [
            {
                "datasetId": "synthetic",
                "bucket": "cell_type:T",
                "fromSuggestionId": "ghid_42_suggestion-1",
                "intoSuggestionId": "ghid_7_suggestion-2",
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
        schemas = validator.load_contracts()
        cls.user_schema = schemas["user"]
        cls.config_schema = schemas["config"]
        cls.merges_schema = schemas["merges"]

    def test_shipped_contract_surfaces_contain_only_current_language(self) -> None:
        retired_language = re.compile(
            r"\bfallback\b|fall(?:ing)?[\s-]+back|best[\s_-]*effort|"
            r"\blegacy\b|\bdeprecated\b|deprecation|"
            r"backwards?[\s_-]*compat|\bshim\b",
            re.IGNORECASE,
        )
        # The governance files at the root -- LICENSE, CONTRIBUTING.md,
        # SECURITY.md, SUPPORT.md, CODE_OF_CONDUCT.md, CITATION.cff -- describe
        # this repository to its readers just as the README does, so the sweep
        # covers the whole root rather than naming README.md and nothing else.
        files = [
            *governed_root_files(),
            REPOSITORY_ROOT / "annotations" / "schema.json",
            REPOSITORY_ROOT / "annotations" / "config.schema.json",
            REPOSITORY_ROOT / "annotations" / "config.json",
            REPOSITORY_ROOT / "annotations" / "moderation" / "merges.schema.json",
            *sorted((REPOSITORY_ROOT / "scripts").glob("*.py")),
            *sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml")),
            *sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yaml")),
        ]
        self.assertIn(REPOSITORY_ROOT / "README.md", files)
        self.assertIn(REPOSITORY_ROOT / "LICENSE", files)
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

    def test_ci_runs_for_every_root_file_the_sweep_governs(self) -> None:
        # The sweep above governs the whole repository root, but the template
        # test workflow decides whether its CI runs at all, and it does that
        # from a list of paths. This holds the two together, in both triggers,
        # so the list cannot fall behind the root.
        workflow_lines = TESTS_WORKFLOW.read_text(encoding="utf-8").splitlines()
        for path in governed_root_files():
            name = path.relative_to(REPOSITORY_ROOT).as_posix()
            self.assertEqual(
                sum(line.strip() == f'- "{name}"' for line in workflow_lines),
                2,
                f"{name} is swept for retired language but does not appear in "
                "both the push and pull_request path filters of "
                ".github/workflows/tests.yml, so changing it runs no CI.",
            )

    def test_shipped_workflow_runs_only_the_validator_with_read_access(self) -> None:
        # An annotation repository copies validate.yml and the layout, not
        # tests/ or this README: the workflow may need nothing else.
        text = WORKFLOW.read_text(encoding="utf-8")
        runs = [
            line.strip().removeprefix("run:").strip()
            for line in text.splitlines()
            if line.strip().startswith("run:")
        ]
        self.assertEqual(runs, ["python scripts/validate_user_files.py"])
        self.assertIn("\npermissions:\n  contents: read\n", text)
        self.assertNotIn("tests", text.split("\njobs:", 1)[1])
        self.assertIn("on: [push, pull_request]\n", text)
        tests_text = TESTS_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("\npermissions:\n  contents: read\n", tests_text)
        self.assertIn("python -m unittest discover -s tests -v", tests_text)
        self.assertIn("python scripts/generate_contract_corpus.py --check", tests_text)

    def test_readme_copy_list_is_the_layout_the_shipped_workflow_needs(self) -> None:
        readme = " ".join((REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8").split())
        self.assertIn(
            "copy the layout files listed above — `annotations/` (with "
            "`annotations/users/.gitkeep`), `scripts/validate_user_files.py`, "
            "`.github/workflows/validate.yml` and `.gitattributes` — into its root",
            readme,
        )
        # A copy of exactly those paths validates: the validator needs nothing
        # from tests/, the README or the governance files.
        with tempfile.TemporaryDirectory() as raw_directory:
            copy_root = pathlib.Path(raw_directory)
            for relative in (
                "annotations",
                "scripts/validate_user_files.py",
                ".github/workflows/validate.yml",
                ".gitattributes",
            ):
                source = REPOSITORY_ROOT / relative
                target = copy_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)
            result = subprocess.run(
                [sys.executable, str(copy_root / "scripts" / "validate_user_files.py")],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_readme_cross_references_the_current_cellucid_ecosystem(self) -> None:
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        for url in (
            (
                "https://docs.cellucid.com/en/latest/user_guide/web_app/"
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
        self.assertIn(
            "Every suggestion id names its owner: it is `ghid_<id>_<rest>`",
            readme,
        )
        self.assertIn(
            "`deletedSuggestions` names only the file owner's own",
            readme,
        )
        self.assertIn(f"`{validator.ANNOTATION_WHITESPACE_CLASS}`", readme)
        self.assertIn("No text and no count has a length limit.", readme)
        self.assertNotIn("0 through 50", readme)
        for identity in (
            "user-v3.schema.json",
            "config-v1.schema.json",
            "merges-v3.schema.json",
        ):
            self.assertIn(
                f"`https://cellucid.com/contracts/community-annotation/{identity}`",
                readme,
            )
        self.assertIn(
            f"must be at most **{validator.ANNOTATION_FILE_MAX_UTF8_BYTES:,} "
            "UTF-8 bytes**",
            readme,
        )
        self.assertIn(
            f"JSON nested deeper than {validator.ANNOTATION_JSON_MAX_DEPTH} levels",
            readme,
        )
        self.assertIn(
            "Every timestamp is UTC and must use exactly "
            "`YYYY-MM-DDTHH:MM:SSZ` or `YYYY-MM-DDTHH:MM:SS.sssZ`. Calendar "
            "dates and clock values must be real; offsets, lowercase `z`, and "
            "other fractional precision are rejected.",
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
        workflow_lines = TESTS_WORKFLOW.read_text(encoding="utf-8").splitlines()
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

    def suggestion_id_surface_errors(self, surface: str, rest: str) -> list[str]:
        """Errors for the id `ghid_42_<rest>` at one suggestion-id surface."""
        value = f"ghid_42_{rest}"
        if surface in {
            "suggestions.id",
            "votes",
            "comments",
            "deletedSuggestions",
        }:
            document = valid_user()
            if surface == "suggestions.id":
                section(document)["suggestions"]["cell_type:T"][0]["id"] = value
            elif surface == "votes":
                section(document)["votes"] = {value: "up"}
            elif surface == "comments":
                section(document)["comments"] = {
                    value: section(document)["comments"]["ghid_42_suggestion-1"]
                }
            else:
                section(document)["deletedSuggestions"] = {"cell_type:T": [value]}
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
                suggestions = section(document)["suggestions"].pop("cell_type:T")
                section(document)["suggestions"][value] = suggestions
            else:
                section(document)["deletedSuggestions"] = {value: ["ghid_42_suggestion-old"]}
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
        section(suggestion)["suggestions"]["cell_type:T"][0]["unknown"] = True
        documents.append(suggestion)

        marker = valid_user()
        section(marker)["suggestions"]["cell_type:T"][0]["markers"][1]["unknown"] = True
        documents.append(marker)

        comment = valid_user()
        section(comment)["comments"]["ghid_42_suggestion-1"][0]["unknown"] = True
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
            ("datasets", []),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                document = valid_user()
                document[key] = value
                errors = self.user_errors(document)
                self.assertTrue(any("must have JSON type" in error for error in errors))
        for key in ("suggestions", "votes"):
            with self.subTest(section_key=key):
                document = valid_user()
                section(document)[key] = []
                errors = self.user_errors(document)
                self.assertTrue(any("must have JSON type" in error for error in errors))

        document = valid_user()
        section(document)["suggestions"]["cell_type:T"][0]["label"] = 7
        self.assertTrue(
            any(
                "must have JSON type string" in error
                for error in self.user_errors(document)
            )
        )

    def test_schema_integer_semantics_match_browser_json_numbers(self) -> None:
        document = valid_user()
        document["version"] = 3.0
        document["githubUserId"] = 42.0
        self.assertEqual(self.user_errors(document), [])

    def test_all_user_timestamps_use_exact_valid_utc_machine_format(self) -> None:
        document = valid_user()
        document["updatedAt"] = "2026-07-25T01:02:03.456Z"
        document["datasets"]["synthetic"]["lastAccessedAt"] = "2026-07-25T01:02:03.456Z"
        suggestion = section(document)["suggestions"]["cell_type:T"][0]
        suggestion["proposedAt"] = "2026-07-25T01:02:03.456Z"
        suggestion["editedAt"] = "2026-07-25T01:02:03.456Z"
        comment = section(document)["comments"]["ghid_42_suggestion-1"][0]
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
            lambda item: section(item)["suggestions"]["cell_type:T"][0].__setitem__(
                "proposedAt", "2026-02-30T00:00:00Z"
            ),
            lambda item: section(item)["suggestions"]["cell_type:T"][0].__setitem__(
                "editedAt", "2026-02-30T00:00:00Z"
            ),
            lambda item: section(item)["comments"]["ghid_42_suggestion-1"][0].__setitem__(
                "createdAt", "2026-02-30T00:00:00Z"
            ),
            lambda item: section(item)["comments"]["ghid_42_suggestion-1"][0].__setitem__(
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
        item = section(document)["suggestions"]["cell_type:T"][0]
        section(document)["suggestions"]["cell_type:T"] = [
            copy.deepcopy(item) for _ in range(501)
        ]
        section(document)["suggestions"]["cell_type:T"][500]["label"] = 7
        errors = self.user_errors(document)
        self.assertTrue(any("[500]" in error and "label" in error for error in errors))

    def test_every_nested_tail_item_is_validated(self) -> None:
        document = valid_user()
        suggestion = section(document)["suggestions"]["cell_type:T"][0]
        suggestion["markers"] = ["CD3D" for _ in range(201)]
        suggestion["markers"][200] = 7
        comment = section(document)["comments"]["ghid_42_suggestion-1"][0]
        section(document)["comments"]["ghid_42_suggestion-1"] = [
            copy.deepcopy(comment) for _ in range(101)
        ]
        section(document)["comments"]["ghid_42_suggestion-1"][100]["text"] = 7
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
        same_target["merges"][0]["intoSuggestionId"] = "ghid_42_suggestion-1"
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
        section(wrong_owner)["suggestions"]["cell_type:T"][0]["proposedBy"] = "ghid_7"
        section(wrong_owner)["comments"]["ghid_42_suggestion-1"][0]["authorUsername"] = "ghid_7"
        errors = self.user_errors(wrong_owner)
        self.assertTrue(any("proposedBy must equal file identity" in e for e in errors))
        self.assertTrue(
            any("authorUsername must equal file identity" in e for e in errors)
        )

        duplicate = valid_user()
        section(duplicate)["suggestions"]["cell_type:B"] = [
            copy.deepcopy(section(duplicate)["suggestions"]["cell_type:T"][0])
        ]
        errors = self.user_errors(duplicate)
        self.assertTrue(any("must be unique in its dataset" in e for e in errors))

        # The same id in two datasets names two suggestions.
        two_datasets = valid_user()
        two_datasets["datasets"]["other"] = copy.deepcopy(section(two_datasets))
        self.assertEqual(self.user_errors(two_datasets), [])

    def test_suggestion_ids_are_owned_by_their_proposer(self) -> None:
        # Another contributor's file cannot hold an id that names ghid_42 (it
        # would collide with or claim ghid_42's suggestion), and ghid_1_ is
        # never a prefix of ghid_12_: the digits end at the separator.
        second = valid_user()
        second["username"] = "ghid_7"
        second["githubUserId"] = 7
        suggestion = section(second)["suggestions"]["cell_type:T"][0]
        suggestion["proposedBy"] = "ghid_7"
        section(second)["comments"]["ghid_42_suggestion-1"][0]["authorUsername"] = "ghid_7"
        section(second)["deletedSuggestions"] = {}
        errors = self.user_errors(second, "ghid_7.json")
        self.assertTrue(any("must start with 'ghid_7_'" in e for e in errors), errors)
        suggestion["id"] = "ghid_7_suggestion-1"
        self.assertEqual(self.user_errors(second, "ghid_7.json"), [])

        shorter = valid_user()
        shorter["username"] = "ghid_12"
        shorter["githubUserId"] = 12
        item = section(shorter)["suggestions"]["cell_type:T"][0]
        item["proposedBy"] = "ghid_12"
        item["id"] = "ghid_1_2_suggestion"
        errors = validator._section_errors(
            section(shorter), pathlib.Path("ghid_12.json"), "synthetic", "ghid_12"
        )
        self.assertTrue(any("must start with 'ghid_12_'" in e for e in errors), errors)

    def test_deleted_suggestions_name_only_the_owners_suggestions(self) -> None:
        document = valid_user()
        section(document)["deletedSuggestions"] = {"cell_type:T": ["ghid_7_theirs"]}
        errors = self.user_errors(document)
        self.assertTrue(
            any("must name a suggestion of the file owner" in e for e in errors), errors
        )
        section(document)["deletedSuggestions"] = {"cell_type:T": ["theirs"]}
        self.assertTrue(
            any("must match pattern" in e for e in self.user_errors(document))
        )

    def test_votes_comments_and_merges_may_name_anyones_suggestion(self) -> None:
        document = valid_user()
        section(document)["votes"] = {"ghid_7_theirs": "up", "ghid_99_x": "down"}
        section(document)["comments"] = {
            "ghid_7_theirs": section(document)["comments"]["ghid_42_suggestion-1"]
        }
        self.assertEqual(self.user_errors(document), [])
        merges = valid_merges()
        merges["merges"][0]["fromSuggestionId"] = "ghid_99_x"
        self.assertEqual(
            validator.validate_merges(
                merges,
                pathlib.Path("annotations/moderation/merges.json"),
                self.merges_schema,
            ),
            [],
        )
        for value in ("suggestion-1", "ghid_0_x", "ghid_07_x", "GHID_7_x", "ghid_7_"):
            with self.subTest(value=value):
                bad = valid_user()
                section(bad)["votes"] = {value: "up"}
                self.assertTrue(
                    any("must match pattern" in e for e in self.user_errors(bad))
                )

    def test_blank_markers_are_checked_and_text_has_no_length_limit(self) -> None:
        blank = valid_user()
        section(blank)["suggestions"]["cell_type:T"][0]["markers"] = ["   "]
        self.assertTrue(any("must match pattern" in e for e in self.user_errors(blank)))

        edge_whitespace = valid_user()
        section(edge_whitespace)["suggestions"]["cell_type:T"][0]["markers"] = [" CD3D"]
        self.assertTrue(
            any(
                "must match pattern" in error
                for error in self.user_errors(edge_whitespace)
            )
        )

        # Counts are bounded by the 1 MB file, not by a fixed item cap: a
        # long marker list is accepted.
        many_markers = valid_user()
        section(many_markers)["suggestions"]["cell_type:T"][0]["markers"] = [
            f"G{index}" for index in range(5_000)
        ]
        self.assertEqual(self.user_errors(many_markers), [])

        # A bucket is `field:category`, named by the dataset's obs column and
        # category, which carry no length limit, so a long category label can
        # be annotated.
        long_bucket = valid_user()
        section(long_bucket)["suggestions"]["cell_type:" + "T" * 5_000] = section(
            long_bucket
        )["suggestions"].pop("cell_type:T")
        self.assertEqual(self.user_errors(long_bucket), [])

        # Nor does anything a contributor types: the file is the only bound.
        long_text = valid_user()
        long_text["login"] = "l" * 5_000
        long_text["displayName"] = "D" * 5_000
        long_text["title"] = "T" * 5_000
        long_text["linkedin"] = "a" * 500
        item = section(long_text)["suggestions"]["cell_type:T"][0]
        item["label"] = "\U0001F600" * 5_000
        item["evidence"] = "e" * 50_000
        item["ontologyId"] = "o" * 5_000
        item["markers"] = ["g" * 5_000, {"gene": "g" * 5_000}]
        comment = section(long_text)["comments"]["ghid_42_suggestion-1"][0]
        comment["id"] = "c" * 5_000
        comment["text"] = "t" * 50_000
        self.assertEqual(self.user_errors(long_text), [])

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
        suggestion = section(document)["suggestions"].pop("cell_type:T")[0]
        section(document)["suggestions"]["fk~celltype%3Acoarse:T:activated"] = [suggestion]
        section(document)["deletedSuggestions"] = {
            "fk~celltype%3Acoarse:T:activated": ["ghid_42_suggestion-old"]
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
        suggestion = section(document)["suggestions"]["cell_type:T"][0]
        suggestion["id"] = "ghid_42_suggestion%3A1"
        suggestion["label"] = "T: activated"
        suggestion["ontologyId"] = "CL:0000084"
        section(document)["votes"] = {"ghid_42_suggestion%3A1": "up"}
        section(document)["comments"] = {
            "ghid_42_suggestion%3A1": [
                {
                    **section(document)["comments"]["ghid_42_suggestion-1"][0],
                    "id": "comment:1",
                }
            ]
        }
        section(document)["deletedSuggestions"] = {
            "cell_type:T:activated": ["ghid_42_suggestion%3Aold"]
        }
        self.assertEqual(self.user_errors(document), [])

    def test_merge_mapping_is_unique_and_acyclic(self) -> None:
        duplicate = valid_merges()
        duplicate["merges"].append(
            {
                **duplicate["merges"][0],
                "intoSuggestionId": "ghid_7_suggestion-3",
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
                "datasetId": "synthetic",
                "bucket": "cell_type:T",
                "fromSuggestionId": "ghid_7_suggestion-2",
                "intoSuggestionId": "ghid_42_suggestion-1",
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

        # The reverse merge in another dataset is another bucket, not a cycle.
        other_dataset = valid_merges()
        other_dataset["merges"].append(
            {
                "datasetId": "other",
                "bucket": "cell_type:T",
                "fromSuggestionId": "ghid_7_suggestion-2",
                "intoSuggestionId": "ghid_42_suggestion-1",
                "by": "ghid_99",
                "at": "2026-07-25T00:00:01Z",
            }
        )
        self.assertEqual(
            validator.validate_merges(
                other_dataset,
                pathlib.Path("annotations/moderation/merges.json"),
                self.merges_schema,
            ),
            [],
        )

    def test_checked_in_schemas_are_the_canonical_blobs(self) -> None:
        schemas = validator.load_contracts()
        self.assertEqual(
            {kind: schema["$id"] for kind, schema in schemas.items()},
            {
                "user": "https://cellucid.com/contracts/community-annotation/user-v3.schema.json",
                "config": "https://cellucid.com/contracts/community-annotation/config-v1.schema.json",
                "merges": "https://cellucid.com/contracts/community-annotation/merges-v3.schema.json",
            },
        )
        for relative, oid in validator.SCHEMA_BLOB_OIDS.items():
            raw = (REPOSITORY_ROOT / relative).read_bytes()
            self.assertEqual(validator.git_blob_oid(raw), oid, relative)

    def test_a_changed_schema_is_refused_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            repository = CliTests.make_repository(pathlib.Path(raw_directory))
            schema = repository / "annotations" / "config.schema.json"
            schema.write_bytes(schema.read_bytes().replace(b"\n", b"\r\n"))
            result = CliTests.run_cli(repository)
            self.assertEqual(result.returncode, 1)
            self.assertIn("annotations/config.schema.json: is not the canonical schema", result.stderr)
            self.assertIn("copy it unchanged from https://github.com/theislab/cellucid-annotation", result.stderr)

    def test_identity_schema_slots_use_true_end_assertions(self) -> None:
        not_space = f"[^{validator.ANNOTATION_WHITESPACE_CLASS[1:-1]}]"
        not_colon_or_space = f"[^:{validator.ANNOTATION_WHITESPACE_CLASS[1:-1]}]"
        exact = rf"{not_space}(?:[\s\S]*{not_space})?$(?![\s\S])"
        field_pattern = rf"^(?!fk~[^:]*%3[Aa][^:]*$(?![\s\S])){exact}"
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

        suggestion_id_pattern = (
            rf"^ghid_[1-9][0-9]*_{not_colon_or_space}"
            rf"(?:[^:]*{not_colon_or_space})?$(?![\s\S])"
        )
        # Everything a contributor writes sits in a dataset's section.
        user_properties = self.user_schema["properties"]["datasets"][
            "additionalProperties"
        ]["properties"]
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
            rf"^{not_colon_or_space}(?:[^:]*{not_colon_or_space})?:{exact}"
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
        not_space = f"[^{validator.ANNOTATION_WHITESPACE_CLASS[1:-1]}]"
        free_text = rf"^{not_space}(?:[\s\S]*{not_space})?$"
        utc_date_time = (
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
            r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(\.[0-9]{3})?Z$"
        )
        github_identity = r"^ghid_[1-9][0-9]*$"
        orcid = r"^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$"
        linkedin = r"^[a-z0-9-]{3,}$"
        expected_counts = {
            free_text: 15,
            utc_date_time: 9,
            github_identity: 4,
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

        # 4 field-key, 6 suggestion-id and 3 bucket slots are checked above.
        self.assertEqual(len(all_slots), 43)
        self.assertEqual(len(refinement_slots), 30)
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
        not_space = f"[^{validator.ANNOTATION_WHITESPACE_CLASS[1:-1]}]"
        examples = {
            rf"^{not_space}(?:[\s\S]*{not_space})?$": "Example",
            (
                r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
                r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
                r"(\.[0-9]{3})?Z$"
            ): "2026-07-25T01:02:03.456Z",
            r"^ghid_[1-9][0-9]*$": "ghid_42",
            r"^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$": (
                "0000-0002-1825-0097"
            ),
            r"^[a-z0-9-]{3,}$": "researcher-42",
        }
        line_terminators = ("\n", "\r", "\r\n", "\u2028", "\u2029")
        refinement_slots = [
            (location, schema, schema["pattern"].removesuffix(true_end))
            for location, schema in self.schema_pattern_slots()
            if schema["pattern"].removesuffix(true_end) in examples
        ]

        self.assertEqual(len(refinement_slots), 30)
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

    def test_free_text_patterns_preserve_internal_whitespace_and_any_length(
        self,
    ) -> None:
        not_space = f"[^{validator.ANNOTATION_WHITESPACE_CLASS[1:-1]}]"
        free_text = rf"^{not_space}(?:[\s\S]*{not_space})?$"
        true_end = r"(?![\s\S])"
        free_text_slots = [
            (location, schema)
            for location, schema in self.schema_pattern_slots()
            if schema["pattern"].removesuffix(true_end) == free_text
        ]
        self.assertEqual(len(free_text_slots), 15)

        for location, schema in free_text_slots:
            self.assertNotIn("maxLength", schema, location)
            self.assertEqual(
                validator._schema_errors("x" * 100_000, schema, "$"),
                [],
                location,
            )
            for terminator in ("\n", "\r", "\r\n", "\u2028", "\u2029", "\u0085", "\ufeff"):
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
        for value in ("abc", "a" * 5_000):
            self.assertEqual(validator._schema_errors(value, linkedin_slot, "$"), [])
        for value in ("ab", "Ab-c", "@abc", "https://www.linkedin.com/in/abc"):
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

    def test_every_whitespace_character_is_an_edge_and_nothing_else_is(self) -> None:
        not_space = f"[^{validator.ANNOTATION_WHITESPACE_CLASS[1:-1]}]"
        schema = {"type": "string", "pattern": rf"^{not_space}(?:[\s\S]*{not_space})?$(?![\s\S])"}
        whitespace = {
            code
            for code in range(0x110000)
            if not 0xD800 <= code <= 0xDFFF
            and re.fullmatch(validator.ANNOTATION_WHITESPACE_CLASS, chr(code))
        }
        self.assertLessEqual({code for code in range(0x110000) if chr(code).isspace()}, whitespace)
        self.assertIn(0xFEFF, whitespace)
        for code in sorted(whitespace):
            with self.subTest(code=hex(code)):
                self.assertTrue(validator._schema_errors(f"{chr(code)}x", schema, "$"))
                self.assertTrue(validator._schema_errors(f"x{chr(code)}", schema, "$"))
        for code in (0x180E, 0x200B, 0x200C, 0x2060, 0x00AD):
            self.assertEqual(validator._schema_errors(f"{chr(code)}x", schema, "$"), [])

    def test_strict_json_reader_rejects_duplicate_keys_and_nonfinite_numbers(
        self,
    ) -> None:
        for raw, message in (
            (b'{"version": 1, "version": 1}', 'duplicate JSON object key "version"'),
            (b'{"version": 1, "\\u0076ersion": 1}', 'duplicate JSON object key "version"'),
            (b'{"value": NaN}', "not a valid JSON number"),
            (b'{"value": -Infinity}', "not a valid JSON number"),
            (b"\xef\xbb\xbf{}", "BOM"),
            (b'{"value": "\xe9"}', "not UTF-8"),
            (b'{"value": 1' + b"0" * 5_000 + b"}", ""),
        ):
            with self.subTest(raw=raw[:40]):
                with self.assertRaisesRegex(validator.JsonInputError, re.escape(message)):
                    validator.parse_annotation_bytes(raw)

    def test_nesting_is_read_to_the_shared_depth_and_never_crashes(self) -> None:
        depth = validator.ANNOTATION_JSON_MAX_DEPTH
        value = validator.parse_annotation_bytes(b"[" * depth + b"]" * depth)
        for _ in range(depth - 1):
            self.assertEqual(len(value), 1)
            value = value[0]
        self.assertEqual(value, [])
        for deeper in (depth + 1, 1_200, 100_000, 499_000):
            with self.subTest(depth=deeper):
                with self.assertRaisesRegex(
                    validator.JsonInputError, f"JSON nesting exceeds {depth} levels"
                ):
                    validator.parse_annotation_bytes(b"[" * deeper + b"]" * deeper)
        # Brackets inside strings are text, not nesting.
        self.assertEqual(
            validator.parse_annotation_bytes(b'{"a": "' + b"[" * 10_000 + b'"}'),
            {"a": "[" * 10_000},
        )

    def test_integers_of_any_size_are_reported_not_raised(self) -> None:
        for digits in (400, 4_000, 5_000):
            huge = b"1" + b"0" * (digits - 1)
            for name, raw in (
                ("githubUserId", json.dumps(valid_user()).encode().replace(b'"githubUserId": 42', b'"githubUserId": ' + huge)),
                ("version", json.dumps(valid_user()).encode().replace(b'"version": 3', b'"version": ' + huge)),
                ("logFC", json.dumps(valid_user()).encode().replace(b'"logFC": 2.5', b'"logFC": ' + huge)),
            ):
                with self.subTest(field=name, digits=digits):
                    errors = validator.validate_bytes(
                        "user", raw, pathlib.Path("annotations/users/ghid_42.json"),
                        {"user": self.user_schema},
                    )
                    self.assertTrue(errors)

    def test_schema_loader_rejects_unimplemented_keywords(self) -> None:
        with self.assertRaisesRegex(
            validator.SchemaDefinitionError, "unsupported schema keyword"
        ):
            validator.parse_schema(
                json.dumps({"type": "object", "unevaluatedProperties": False}).encode(),
                "schema.json",
            )

class CliTests(unittest.TestCase):
    @staticmethod
    def make_repository(directory: pathlib.Path) -> pathlib.Path:
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

    @staticmethod
    def run_cli(repository: pathlib.Path) -> subprocess.CompletedProcess[str]:
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
            item = section(document)["suggestions"]["cell_type:T"][0]
            section(document)["suggestions"]["cell_type:T"] = [
                copy.deepcopy(item) for _ in range(501)
            ]
            section(document)["suggestions"]["cell_type:T"][500]["label"] = 7
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
            (repository / "annotations" / "users" / "ghid_43.json").write_text(
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
            self.assertIn("directories are not permitted", result.stderr)

    def test_cli_rejects_every_unknown_user_directory_entry(self) -> None:
        only_user_files = "only ghid_<GitHub user id>.json user files and .gitkeep"
        cases = (
            ("notes.txt", only_user_files),
            ("README.md", only_user_files),
            ("alice.json", only_user_files),
            ("ghid_042.json", only_user_files),
            ("ghid_0.json", only_user_files),
            ("ghid_42.json.bak", only_user_files),
            ("GHID_42.JSON", only_user_files),
            (".GITKEEP", only_user_files),
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
                    self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_case_variants_of_layout_paths(self) -> None:
        # Cellucid reads only the exact paths; a case variant is never read,
        # and on a case-insensitive checkout it would shadow the real path.
        cases = (
            ("annotations/users", "annotations/Users", "case variant of 'users'"),
            ("annotations/moderation", "annotations/Moderation", "case variant of 'moderation'"),
            ("annotations/config.json", "annotations/Config.json", "case variant of 'config.json'"),
            ("annotations/moderation/merges.json", "annotations/moderation/MERGES.json", "case variant of 'merges.json'"),
            ("annotations", "Annotations", "case variant of 'annotations'"),
        )
        for original, variant, expected in cases:
            with self.subTest(variant=variant):
                with tempfile.TemporaryDirectory() as raw_directory:
                    repository = self.make_repository(pathlib.Path(raw_directory))
                    source = repository / original
                    target = repository / variant
                    probe = repository / "Case-Probe"
                    probe.write_bytes(b"")
                    case_sensitive = not (repository / "case-probe").exists()
                    probe.unlink()
                    if case_sensitive:
                        # Both spellings can exist side by side, as in Git.
                        if source.is_dir():
                            target.mkdir()
                        else:
                            target.write_bytes(source.read_bytes())
                    else:
                        # One entry, spelled as the variant: the file system
                        # still finds the exact path through it.
                        source.rename(target)
                    result = self.run_cli(repository)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(expected, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_cli_requires_the_exact_repository_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            repository = self.make_repository(pathlib.Path(raw_directory))
            sentinel = repository / "annotations" / "users" / ".gitkeep"
            sentinel.write_text("not empty", encoding="utf-8")
            result = self.run_cli(repository)
            self.assertEqual(result.returncode, 1)
            self.assertIn(".gitkeep must contain exactly one LF byte", result.stderr)

    def test_cli_rejects_ids_that_name_another_owner(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            repository = self.make_repository(pathlib.Path(raw_directory))
            users = repository / "annotations" / "users"
            (users / "ghid_42.json").write_text(
                json.dumps(valid_user()), encoding="utf-8"
            )
            # ghid_7 reuses ghid_42's public suggestion id.
            second = valid_user()
            second["username"] = "ghid_7"
            second["githubUserId"] = 7
            section(second)["suggestions"]["cell_type:T"][0]["proposedBy"] = "ghid_7"
            section(second)["comments"]["ghid_42_suggestion-1"][0]["authorUsername"] = "ghid_7"
            section(second)["deletedSuggestions"] = {}
            (users / "ghid_7.json").write_text(json.dumps(second), encoding="utf-8")
            result = self.run_cli(repository)
            self.assertEqual(result.returncode, 1)
            self.assertIn("must start with 'ghid_7_'", result.stderr)
            self.assertNotIn("ghid_42.json", result.stderr)

    def test_cli_reports_hostile_json_without_crashing(self) -> None:
        documents = {
            "deep": b'{"x": ' + b"[" * 200_000 + b"]" * 200_000 + b"}",
            "huge_int": json.dumps(valid_user()).encode().replace(
                b'"githubUserId": 42', b'"githubUserId": 1' + b"0" * 5_000
            ),
            "huge_float_int": json.dumps(valid_user()).encode().replace(
                b'"logFC": 2.5', b'"logFC": 1' + b"0" * 400
            ),
            "bom": b"\xef\xbb\xbf" + json.dumps(valid_user()).encode(),
            "latin1": json.dumps(valid_user()).encode().replace(b"T cell", b"T c\xe9ll"),
            "truncated": json.dumps(valid_user()).encode()[:100],
        }
        for name, raw in documents.items():
            with self.subTest(document=name):
                with tempfile.TemporaryDirectory() as raw_directory:
                    repository = self.make_repository(pathlib.Path(raw_directory))
                    (repository / "annotations" / "users" / "ghid_42.json").write_bytes(raw)
                    result = self.run_cli(repository)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("ghid_42.json", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            repository = self.make_repository(pathlib.Path(raw_directory))
            target = repository / "elsewhere.json"
            target.write_text(json.dumps(valid_user()), encoding="utf-8")
            try:
                (repository / "annotations" / "users" / "ghid_42.json").symlink_to(target)
            except OSError as error:  # Windows without the symlink privilege
                self.skipTest(f"cannot create a symbolic link here: {error}")
            result = self.run_cli(repository)
            self.assertEqual(result.returncode, 1)
            self.assertIn("symbolic links are not permitted", result.stderr)

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



class NoFabricatedCountLimitsTests(unittest.TestCase):
    """The schemas carry no item-count caps and no length cap on keys named
    by the dataset (field keys, `field:category` buckets): the 1 MB file is
    the only bound on how much one contributor file holds."""

    def test_schemas_have_no_count_caps(self) -> None:
        import json

        def walk(node, location):
            if isinstance(node, dict):
                for keyword in ("maxItems", "maxProperties"):
                    self.assertNotIn(keyword, node, location)
                for key, value in node.items():
                    walk(value, f"{location}/{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{location}/{index}")

        root = pathlib.Path(__file__).resolve().parents[1] / "annotations"
        for name in ("schema.json", "config.schema.json", "moderation/merges.schema.json"):
            walk(json.loads((root / name).read_text(encoding="utf-8")), name)

    def test_schemas_have_no_length_caps(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1] / "annotations"
        for name in ("schema.json", "config.schema.json", "moderation/merges.schema.json"):
            text = (root / name).read_text(encoding="utf-8")
            self.assertNotIn('"maxLength"', text, name)
            self.assertNotIn('"maxItems"', text, name)
            self.assertNotIn('"maxProperties"', text, name)


if __name__ == "__main__":
    unittest.main()
