"""Every bound in the annotation schemas is a real one, and says why.

Each ``maxItems``, ``maxLength``, ``maxProperties``, ``maximum`` and
``exclusiveMaximum`` in ``annotations/**/*.schema.json`` and
``annotations/schema.json`` is listed below with its value, its class and its
reason. A new bound fails until someone classifies it; a changed value fails
until the reason is re-checked. The classes are

- FORMAT: fixed by a format (a JavaScript safe integer, a fraction);
- PLAT: a real limit of GitHub, where the files live;
- HOST: a per-item bound on contributor text in a shared file, so one
  contribution cannot crowd out the rest of the 1 MB file every reader loads;
  the Cellucid web app's ``ANNOTATION_LIMITS`` carries the same values.

There are no count limits: how many suggestions, votes, comments, datasets or
merges a file holds is bounded only by the 1 MB file itself.
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
CLASSES = {"FORMAT", "PLAT", "HOST"}
IDENTITY = "A GitHub login is at most 39 characters and a ghid_<id> key at most 21; 64 holds either."
APP_ID = "An identifier the app generates (a UUID is 36 characters); 128 holds any it writes."
TEXT = "Per-item contributor text in a shared file; matches ANNOTATION_LIMITS in the web app."

SCHEMA = "annotations/schema.json#/properties"
SECTION = f"{SCHEMA}/datasets/additionalProperties/properties"
SUGGESTION = f"{SECTION}/suggestions/additionalProperties/items/properties"
CONFIG = "annotations/config.schema.json#/properties/supportedDatasets/items/properties"
MERGE = "annotations/moderation/merges.schema.json#/properties/merges/items/properties"

ALLOWLIST: dict[str, tuple[int, str, str]] = {
    f"{CONFIG}/datasetId:maxLength": (256, "HOST", "A dataset id, bounded as the web app's annotation wire contract bounds it."),
    f"{CONFIG}/name:maxLength": (120, "HOST", TEXT),
    f"{CONFIG}/annotatableSettings/additionalProperties/properties/threshold:maximum": (
        1,
        "FORMAT",
        "A consensus threshold is a fraction of votes.",
    ),
    f"{MERGE}/datasetId:maxLength": (256, "HOST", "A dataset id, bounded as the web app's annotation wire contract bounds it."),
    f"{MERGE}/fromSuggestionId:maxLength": (128, "HOST", APP_ID),
    f"{MERGE}/intoSuggestionId:maxLength": (128, "HOST", APP_ID),
    f"{MERGE}/by:maxLength": (64, "PLAT", IDENTITY),
    f"{MERGE}/note:maxLength": (512, "HOST", TEXT),
    f"{SCHEMA}/username:maxLength": (64, "PLAT", IDENTITY),
    f"{SCHEMA}/githubUserId:maximum": (
        9007199254740991,
        "FORMAT",
        "The largest integer a JavaScript number holds exactly.",
    ),
    f"{SCHEMA}/login:maxLength": (64, "PLAT", IDENTITY),
    f"{SCHEMA}/displayName:maxLength": (120, "HOST", TEXT),
    f"{SCHEMA}/title:maxLength": (120, "HOST", TEXT),
    f"{SCHEMA}/datasets/propertyNames:maxLength": (256, "HOST", "A dataset id, bounded as the web app's annotation wire contract bounds it."),
    f"{SUGGESTION}/id:maxLength": (128, "HOST", APP_ID),
    f"{SUGGESTION}/label:maxLength": (120, "HOST", TEXT),
    f"{SUGGESTION}/ontologyId:maxLength": (64, "HOST", "A CURIE such as CL:0000236; matches the web app."),
    f"{SUGGESTION}/evidence:maxLength": (2000, "HOST", TEXT),
    f"{SUGGESTION}/markers/items/oneOf/0:maxLength": (64, "HOST", "A gene symbol; matches the web app."),
    f"{SUGGESTION}/markers/items/oneOf/1/properties/gene:maxLength": (64, "HOST", "A gene symbol; matches the web app."),
    f"{SUGGESTION}/proposedBy:maxLength": (64, "PLAT", IDENTITY),
    f"{SECTION}/votes/propertyNames:maxLength": (128, "HOST", APP_ID),
    f"{SECTION}/comments/propertyNames:maxLength": (128, "HOST", APP_ID),
    f"{SECTION}/comments/additionalProperties/items/properties/id:maxLength": (128, "HOST", APP_ID),
    f"{SECTION}/comments/additionalProperties/items/properties/text:maxLength": (500, "HOST", TEXT),
    f"{SECTION}/comments/additionalProperties/items/properties/authorUsername:maxLength": (64, "PLAT", IDENTITY),
    f"{SECTION}/deletedSuggestions/additionalProperties/items:maxLength": (128, "HOST", APP_ID),
}


def schema_bounds() -> dict[str, int]:
    bounds: dict[str, int] = {}
    files = sorted((ROOT / "annotations").rglob("*.schema.json")) + [ROOT / "annotations/schema.json"]

    def walk(node: object, file: str, pointer: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in KEYWORDS:
                    bounds[f"{file}#{pointer}:{key}"] = value
                walk(value, file, f"{pointer}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, file, f"{pointer}/{index}")

    for path in files:
        walk(json.loads(path.read_text(encoding="utf-8")), path.relative_to(ROOT).as_posix(), "")
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

    def test_no_schema_bounds_a_count(self) -> None:
        self.assertEqual(
            [key for key in schema_bounds() if key.endswith((":maxItems", ":maxProperties"))],
            [],
        )

    def test_the_file_limit_is_githubs(self) -> None:
        # GitHub's Contents API returns a file's content as JSON only up to 1 MB.
        self.assertEqual(validate_user_files.ANNOTATION_FILE_MAX_UTF8_BYTES, 1_000_000)
        scripts = (ROOT / "scripts" / "validate_user_files.py").read_text(encoding="utf-8")
        names = set(re.findall(r"^([A-Z][A-Z0-9_]*(?:MAX|LIMIT)[A-Z0-9_]*)\s*=", scripts, re.M))
        self.assertEqual(names, {"ANNOTATION_FILE_MAX_UTF8_BYTES"})


if __name__ == "__main__":
    unittest.main()
