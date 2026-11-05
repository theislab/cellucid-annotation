"""Every bound in the annotation schemas is a real one, and says why.

Each ``maxItems``, ``maxLength``, ``maxProperties``, ``maximum`` and
``exclusiveMaximum`` in ``annotations/**/*.schema.json`` and
``annotations/schema.json`` is listed below with its value, its class and its
reason. A new bound fails until someone classifies it; a changed value fails
until the reason is re-checked. The classes are

- FORMAT: fixed by a format (a JavaScript safe integer, a fraction);
- PLAT: a real limit of GitHub, where the files live.

There are no length or count limits: how long a text is, and how many
suggestions, votes, comments, datasets or merges a file holds, is bounded only
by the 1,000,000-byte file itself.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_user_files  # noqa: E402

KEYWORDS = {"maxItems", "maxLength", "maxProperties", "maximum", "exclusiveMaximum"}
CLASSES = {"FORMAT", "PLAT"}
SAFE = 9007199254740991
SAFE_REASON = "The largest integer a JavaScript number holds exactly; the web app requires safe integers."

SCHEMA = "annotations/schema.json#/properties"
CONFIG = "annotations/config.schema.json#/properties"
SETTING = f"{CONFIG}/supportedDatasets/items/properties/annotatableSettings/additionalProperties/properties"
MERGES = "annotations/moderation/merges.schema.json#/properties"

ALLOWLIST: dict[str, tuple[int, str, str]] = {
    f"{SCHEMA}/version:maximum": (SAFE, "FORMAT", SAFE_REASON),
    f"{SCHEMA}/githubUserId:maximum": (SAFE, "FORMAT", SAFE_REASON),
    f"{CONFIG}/version:maximum": (SAFE, "FORMAT", SAFE_REASON),
    f"{SETTING}/minAnnotators:maximum": (SAFE, "FORMAT", SAFE_REASON),
    f"{SETTING}/threshold:maximum": (1, "FORMAT", "A consensus threshold is a fraction of votes."),
    f"{MERGES}/version:maximum": (SAFE, "FORMAT", SAFE_REASON),
}


def schema_files() -> list[Path]:
    return sorted((ROOT / "annotations").rglob("*.schema.json")) + [ROOT / "annotations/schema.json"]


def walk(node: object, file: str, pointer: str, visit) -> None:
    if isinstance(node, dict):
        visit(node, file, pointer)
        for key, value in node.items():
            walk(value, file, f"{pointer}/{key}", visit)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            walk(value, file, f"{pointer}/{index}", visit)


def schema_bounds() -> dict[str, int]:
    bounds: dict[str, int] = {}

    def visit(node: dict, file: str, pointer: str) -> None:
        for key, value in node.items():
            if key in KEYWORDS:
                bounds[f"{file}#{pointer}:{key}"] = value

    for path in schema_files():
        walk(json.loads(path.read_text(encoding="utf-8")), path.relative_to(ROOT).as_posix(), "", visit)
    return bounds


class SchemaLimitsTest(unittest.TestCase):
    def test_every_schema_bound_is_classified_at_its_value(self) -> None:
        bounds = schema_bounds()
        self.assertEqual(sorted(set(bounds) - set(ALLOWLIST)), [], "unclassified schema bounds")
        self.assertEqual(sorted(set(ALLOWLIST) - set(bounds)), [], "allowlist names bounds that are gone")
        for key, value in bounds.items():
            expected, kind, reason = ALLOWLIST[key]
            self.assertEqual(value, expected, f"{key} changed; re-check its reason")
            self.assertIn(kind, CLASSES, key)
            self.assertTrue(reason.strip(), key)

    def test_no_schema_bounds_a_length_or_a_count(self) -> None:
        self.assertEqual(
            [key for key in schema_bounds() if not key.endswith(":maximum")],
            [],
        )

    def test_every_integer_is_a_safe_integer(self) -> None:
        integers: list[tuple[str, object]] = []

        def visit(node: dict, file: str, pointer: str) -> None:
            if node.get("type") == "integer":
                integers.append((f"{file}#{pointer}", node.get("maximum")))

        for path in schema_files():
            walk(json.loads(path.read_text(encoding="utf-8")), path.relative_to(ROOT).as_posix(), "", visit)
        self.assertEqual(len(integers), 5)
        for location, maximum in integers:
            self.assertEqual(maximum, SAFE, location)

    def test_the_validator_bounds_are_real(self) -> None:
        # GitHub's Contents API returns a file's content as JSON only up to
        # 1 MB; Python's json decoder stops at the recursion limit (1000 by
        # default), so the validator reads at most 512 nesting levels.
        self.assertEqual(validate_user_files.ANNOTATION_FILE_MAX_UTF8_BYTES, 1_000_000)
        self.assertEqual(validate_user_files.ANNOTATION_JSON_MAX_DEPTH, 512)
        self.assertLess(validate_user_files.ANNOTATION_JSON_MAX_DEPTH, sys.getrecursionlimit())
        scripts = (ROOT / "scripts" / "validate_user_files.py").read_text(encoding="utf-8")
        names = set(re.findall(r"^([A-Z][A-Z0-9_]*(?:MAX|LIMIT)[A-Z0-9_]*)\s*=", scripts, re.M))
        self.assertEqual(names, {"ANNOTATION_FILE_MAX_UTF8_BYTES", "ANNOTATION_JSON_MAX_DEPTH"})

    def test_the_validator_refuses_schemas_with_length_or_count_limits(self) -> None:
        for keyword in ("maxLength", "maxItems", "maxProperties"):
            with self.subTest(keyword=keyword):
                schema = json.dumps({"type": "string", keyword: 10}).encode("utf-8")
                with self.assertRaisesRegex(
                    validate_user_files.SchemaDefinitionError, "unsupported schema keyword"
                ):
                    validate_user_files.parse_schema(schema, "test")


if __name__ == "__main__":
    unittest.main()
