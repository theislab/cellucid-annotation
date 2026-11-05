"""The shared accept/reject corpus holds this validator to the contract.

``tests/fixtures/contract-corpus.json`` is written by
``scripts/generate_contract_corpus.py``. The Cellucid web app keeps a
byte-identical copy (``tests/fixtures/community-annotation-contract-corpus.json``
in theislab/cellucid) and pins the same SHA-256, so the browser and this
validator must give every case the same verdict. Update the digest here and
there together.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import unittest
from typing import Any

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "contract-corpus.json"
FIXTURE_SHA256 = "81239badc82ce335ea3cd82c1685baf5b4ce64021e4e15cc40935156d00508ba"

SPEC = importlib.util.spec_from_file_location(
    "validate_user_files", REPOSITORY_ROOT / "scripts" / "validate_user_files.py"
)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def case_bytes(case: dict[str, Any]) -> bytes:
    raw = base64.b64decode(case["base64"]) if "base64" in case else case["text"].encode("utf-8")
    if "padToBytes" in case:
        raw += b" " * (case["padToBytes"] - len(raw))
        assert len(raw) == case["padToBytes"]
    return raw


class ContractCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = FIXTURE.read_bytes()
        cls.corpus = json.loads(cls.raw)
        cls.schemas = validator.load_contracts()

    def test_corpus_is_the_pinned_one(self) -> None:
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), FIXTURE_SHA256)

    def test_corpus_is_generated_from_the_current_sources(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPOSITORY_ROOT / "scripts" / "generate_contract_corpus.py"), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_corpus_carries_the_checked_in_schemas_and_their_blob_ids(self) -> None:
        self.assertEqual(set(self.corpus["schemas"]), {"user", "config", "merges"})
        for kind, entry in self.corpus["schemas"].items():
            with self.subTest(kind=kind):
                raw = (REPOSITORY_ROOT / entry["path"]).read_bytes()
                self.assertEqual(raw.decode("utf-8"), entry["text"])
                self.assertEqual(validator.git_blob_oid(raw), entry["blobOid"])
                self.assertEqual(validator.SCHEMA_BLOB_OIDS[entry["path"]], entry["blobOid"])
                # The id git computes is the id GitHub's tree names.
                git = subprocess.run(
                    ["git", "hash-object", "--no-filters", "--stdin"],
                    input=raw,
                    capture_output=True,
                    check=True,
                )
                self.assertEqual(git.stdout.decode("ascii").strip(), entry["blobOid"])

    def test_corpus_carries_the_validators_shared_parameters(self) -> None:
        self.assertEqual(self.corpus["fileMaxUtf8Bytes"], validator.ANNOTATION_FILE_MAX_UTF8_BYTES)
        self.assertEqual(self.corpus["jsonMaxDepth"], validator.ANNOTATION_JSON_MAX_DEPTH)
        self.assertEqual(self.corpus["whitespaceClass"], validator.ANNOTATION_WHITESPACE_CLASS)

    def test_whitespace_class_covers_python_whitespace_and_nothing_unlisted(self) -> None:
        listed = set(self.corpus["whitespaceCodePoints"])
        matched = {
            code
            for code in range(0x110000)
            if not 0xD800 <= code <= 0xDFFF
            and re.fullmatch(validator.ANNOTATION_WHITESPACE_CLASS, chr(code))
        }
        self.assertEqual(matched, listed)
        python_whitespace = {code for code in range(0x110000) if chr(code).isspace()}
        self.assertLessEqual(python_whitespace, listed)
        # ECMAScript adds U+FEFF, which str.isspace() does not count.
        self.assertEqual(listed - python_whitespace, {0xFEFF})

    def test_every_whitespace_pattern_uses_the_contract_class(self) -> None:
        body = validator.ANNOTATION_WHITESPACE_CLASS[1:-1]
        for kind, entry in self.corpus["schemas"].items():
            patterns: list[str] = []

            def visit(node: Any) -> None:
                if isinstance(node, dict):
                    if "pattern" in node:
                        patterns.append(node["pattern"])
                    for child in node.values():
                        visit(child)
                elif isinstance(node, list):
                    for child in node:
                        visit(child)

            visit(json.loads(entry["text"]))
            for pattern in patterns:
                with self.subTest(kind=kind, pattern=pattern[:60]):
                    # \s and \S appear only together, as "any character".
                    self.assertNotRegex(pattern.replace(r"[\s\S]", ""), r"\\[sS]")
                    # Every negated class is "not whitespace" (optionally "not
                    # ':' either") or exactly "not ':'".
                    for negated in re.findall(r"\[\^([^\]]*)\]", pattern):
                        if negated != ":":
                            self.assertEqual(negated.removeprefix(":"), body)

    def test_every_case_gets_its_verdict(self) -> None:
        kinds = {case["kind"] for case in self.corpus["cases"]}
        self.assertEqual(kinds, {"user", "config", "merges"})
        for case in self.corpus["cases"]:
            with self.subTest(case=case["name"]):
                raw = case_bytes(case)
                try:
                    errors = validator.validate_bytes(
                        case["kind"], raw, pathlib.Path(case["path"]), self.schemas
                    )
                except BaseException as error:  # the validator never crashes
                    self.fail(f"{case['name']}: {type(error).__name__}: {error}")
                verdict = "reject" if errors else "accept"
                self.assertEqual(verdict, case["expect"], errors[:3])

    def test_corpus_covers_the_contract_it_promises(self) -> None:
        names = {case["name"] for case in self.corpus["cases"]}
        for code in self.corpus["whitespaceCodePoints"]:
            self.assertIn(f"user/whitespace_u{code:04x}_label_leading", names)
        for required in (
            "user/version_2_file",
            "merges/version_2_file",
            "user/id_other_owner",
            "user/id_longer_owner_prefix",
            "user/deleted_other_owner",
            "user/githubUserId_bigint5000",
            "config/minAnnotators_2p53_plus_1",
            "config/minAnnotators_100",
            "user/nesting_513",
            "user/nesting_100000",
            "user/raw_duplicate_key_escaped",
            "user/size_1000001_bytes",
            "user/other_dataset_section_invalid",
        ):
            self.assertIn(required, names)


if __name__ == "__main__":
    unittest.main()
