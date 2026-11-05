#!/usr/bin/env python3
"""Write the shared accept/reject corpus of the annotation contract.

The corpus, ``tests/fixtures/contract-corpus.json``, holds the three schema
texts and a list of files, each with the verdict the contract gives it. This
repository's validator (``scripts/validate_user_files.py``) and the Cellucid
web app (``assets/js/app/community-annotations/wire-contract.js``, which keeps
a byte-identical copy at ``tests/fixtures/community-annotation-contract-corpus.json``)
must both give every case its verdict; both test suites pin the corpus by
SHA-256. Every verdict is stated here by hand: it is the contract, not a
recording of either validator.

Usage::

    python scripts/generate_contract_corpus.py            # write the corpus
    python scripts/generate_contract_corpus.py --check    # fail if it is stale
    python scripts/generate_contract_corpus.py --copy PATH [--check]
        # also write (or check) an identical copy, such as the web app's

A case is ``{"name", "kind", "path", "expect", "text" | "base64"}``, plus
``"padToBytes"`` (ASCII spaces appended after the JSON text until the file
has that many bytes) and ``"project"`` (the web app's verdict when it reads
only one dataset of the file: a list of ``{"datasetId", "expect"}``; another
dataset's part of a file never makes it fail there).
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import pathlib
import re
import sys
from typing import Any, Callable

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "contract-corpus.json"
_SPEC = importlib.util.spec_from_file_location(
    "validate_user_files", ROOT / "scripts" / "validate_user_files.py"
)
assert _SPEC is not None and _SPEC.loader is not None
validator = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(validator)

ACCEPT = "accept"
REJECT = "reject"
T = "2026-07-25T01:02:03Z"
USER_PATH = "annotations/users/"
CONFIG_PATH = "annotations/config.json"
MERGES_PATH = "annotations/moderation/merges.json"

cases: list[dict[str, Any]] = []


def _text(document: Any) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def emit(
    kind: str,
    name: str,
    expect: str,
    content: Any,
    *,
    filename: str = "ghid_7.json",
    pad_to: int | None = None,
    project: list[tuple[str, str]] | None = None,
) -> None:
    """Add one case; ``content`` is a JSON value, raw text (str) or raw bytes."""
    path = {"user": USER_PATH + filename, "config": CONFIG_PATH, "merges": MERGES_PATH}[kind]
    case: dict[str, Any] = {"name": f"{kind}/{name}", "kind": kind, "path": path, "expect": expect}
    if isinstance(content, bytes):
        try:
            case["text"] = content.decode("utf-8")
        except UnicodeDecodeError:
            case["base64"] = base64.b64encode(content).decode("ascii")
    elif isinstance(content, str):
        content.encode("utf-8")  # text cases are representable as UTF-8
        case["text"] = content
    else:
        case["text"] = _text(content)
    if pad_to is not None:
        case["padToBytes"] = pad_to
    if project is not None:
        case["project"] = [{"datasetId": dataset, "expect": verdict} for dataset, verdict in project]
    assert case["name"] not in {existing["name"] for existing in cases}, case["name"]
    cases.append(case)


# --------------------------------------------------------------------------
# User files (version 3).


def user(uid: int = 7) -> dict[str, Any]:
    me = f"ghid_{uid}"
    return {
        "version": 3,
        "username": me,
        "githubUserId": uid,
        "updatedAt": "2026-07-25T01:02:03.456Z",
        "datasets": {
            "ds": {
                "fieldsToAnnotate": ["cell_type"],
                "lastAccessedAt": T,
                "suggestions": {
                    "cell_type:Alpha": [
                        {
                            "id": f"{me}_s1",
                            "label": "T cell",
                            "ontologyId": "CL:0000084",
                            "evidence": "x",
                            "markers": ["CD3D", {"gene": "CD4", "logFC": 1.5, "pval": 0.01}],
                            "proposedBy": me,
                            "proposedAt": T,
                            "editedAt": None,
                        }
                    ]
                },
                "votes": {f"{me}_s1": "up", "ghid_8_other": "down"},
                "comments": {
                    f"{me}_s1": [
                        {"id": "c1", "text": "ok", "authorUsername": me, "createdAt": T, "editedAt": None}
                    ]
                },
                "deletedSuggestions": {"cell_type:Alpha": [f"{me}_s0"]},
            }
        },
    }


def S(u: dict[str, Any], dataset: str = "ds") -> dict[str, Any]:
    return u["datasets"][dataset]


def sug(u: dict[str, Any]) -> dict[str, Any]:
    return S(u)["suggestions"]["cell_type:Alpha"][0]


def U(
    name: str,
    expect: str,
    mutate: Callable[[dict[str, Any]], Any],
    *,
    filename: str = "ghid_7.json",
    uid: int = 7,
    project: list[tuple[str, str]] | None = None,
) -> None:
    u = user(uid)
    replaced = mutate(u)
    emit("user", name, expect, u if replaced is None else replaced, filename=filename, project=project)


BASE_USER = _text(user()).encode("utf-8")


def raw_user(name: str, expect: str, old: bytes, new: bytes, *, filename: str = "ghid_7.json") -> None:
    assert BASE_USER.count(old) >= 1, old
    emit("user", name, expect, BASE_USER.replace(old, new), filename=filename)


def rename_bucket(u: dict[str, Any], bucket: str) -> None:
    S(u)["suggestions"] = {bucket: S(u)["suggestions"]["cell_type:Alpha"]}


U("valid", ACCEPT, lambda u: None, project=[("ds", ACCEPT), ("other", ACCEPT)])
U("valid_profile_only", ACCEPT, lambda u: u.update(datasets={}), project=[("ds", ACCEPT)])
U(
    "valid_profile_fields",
    ACCEPT,
    lambda u: u.update(
        login="octo", displayName="Ada L", title="PhD", orcid="0000-0002-1825-0097", linkedin="ada-l"
    ),
)
U("valid_two_datasets_same_ids", ACCEPT, lambda u: u["datasets"].update(ds2=copy.deepcopy(S(u))))

# Versions: only version 3 is a user file.
emit(
    "user",
    "version_2_file",
    REJECT,
    {
        "version": 2,
        "username": "ghid_7",
        "githubUserId": 7,
        "updatedAt": T,
        "datasets": {
            "ds": {
                "fieldsToAnnotate": ["cell_type"],
                "lastAccessedAt": T,
                "suggestions": {
                    "cell_type:Alpha": [{"id": "s1", "label": "T cell", "proposedBy": "ghid_7", "proposedAt": T}]
                },
                "votes": {"s1": "up"},
            }
        },
    },
)
U("version_2_otherwise_v3", REJECT, lambda u: u.update(version=2))
U(
    "version_1_view_shape",
    REJECT,
    lambda u: {"version": 1, "username": "ghid_7", "githubUserId": 7, "updatedAt": T, "suggestions": {}, "votes": {}},
)
U("version_4", REJECT, lambda u: u.update(version=4))
U("version_float_3_0", ACCEPT, lambda u: u.update(version=3.0))
U("version_string", REJECT, lambda u: u.update(version="3"))
U("version_true", REJECT, lambda u: u.update(version=True))
raw_user("version_bigint400", REJECT, b'"version": 3', b'"version": 1' + b"0" * 400)

# Identity.
U("githubUserId_string", REJECT, lambda u: u.update(githubUserId="7"))
U(
    "githubUserId_zero",
    REJECT,
    lambda u: {**u, "githubUserId": 0, "username": "ghid_0", "datasets": {}},
    filename="ghid_0.json",
)
U("githubUserId_negative", REJECT, lambda u: u.update(githubUserId=-7))
U("githubUserId_float_7_0", ACCEPT, lambda u: u.update(githubUserId=7.0))
raw_user("githubUserId_exponent_7e0", ACCEPT, b'"githubUserId": 7', b'"githubUserId": 7e0')
raw_user("githubUserId_fraction_70e-1", ACCEPT, b'"githubUserId": 7', b'"githubUserId": 70e-1')
raw_user("githubUserId_negative_zero", REJECT, b'"githubUserId": 7', b'"githubUserId": -0')
U(
    "githubUserId_max_safe",
    ACCEPT,
    lambda u: {**u, "githubUserId": 9007199254740991, "username": "ghid_9007199254740991", "datasets": {}},
    filename="ghid_9007199254740991.json",
)
U(
    "githubUserId_above_max_safe",
    REJECT,
    lambda u: {**u, "githubUserId": 9007199254740992, "username": "ghid_9007199254740992", "datasets": {}},
    filename="ghid_9007199254740992.json",
)
emit(
    "user",
    "githubUserId_2p53_plus_1",
    REJECT,
    _text({**user(), "datasets": {}})
    .replace('"githubUserId": 7', '"githubUserId": 9007199254740993')
    .replace('"ghid_7"', '"ghid_9007199254740993"'),
    filename="ghid_9007199254740993.json",
)
raw_user("githubUserId_bigint400", REJECT, b'"githubUserId": 7', b'"githubUserId": 1' + b"0" * 400)
raw_user("githubUserId_bigint5000", REJECT, b'"githubUserId": 7', b'"githubUserId": 1' + b"0" * 5000)
U("username_leading_zero", REJECT, lambda u: u.update(username="ghid_07"))
U("username_other", REJECT, lambda u: u.update(username="ghid_8"))
U("filename_mismatch", REJECT, lambda u: None, filename="ghid_8.json")
U("filename_uppercase", REJECT, lambda u: None, filename="GHID_7.json")

# Shape.
U("unknown_top_field", REJECT, lambda u: u.update(extra=1))
U("unknown_section_field", REJECT, lambda u: S(u).update(extra=1))
U("unknown_suggestion_field", REJECT, lambda u: sug(u).update(extra=1))
U("unknown_comment_field", REJECT, lambda u: S(u)["comments"]["ghid_7_s1"][0].update(extra=1))
U("unknown_marker_field", REJECT, lambda u: sug(u).update(markers=[{"gene": "A", "z": 1}]))
U("missing_datasets", REJECT, lambda u: u.pop("datasets"))
U("datasets_array", REJECT, lambda u: u.update(datasets=[]))
U("section_missing_votes", REJECT, lambda u: S(u).pop("votes"))
U("section_missing_suggestions", REJECT, lambda u: S(u).pop("suggestions"))
U("section_null", REJECT, lambda u: u["datasets"].update(ds=None), project=[("ds", REJECT)])

# Profile.
U("orcid_bad_checksum", REJECT, lambda u: u.update(orcid="0000-0002-1825-0098"), project=[("ds", REJECT)])
U("orcid_url", REJECT, lambda u: u.update(orcid="https://orcid.org/0000-0002-1825-0097"))
U("orcid_compact", REJECT, lambda u: u.update(orcid="0000000218250097"))
U("orcid_check_x", ACCEPT, lambda u: u.update(orcid="0000-0002-1694-233X"))
U("linkedin_uppercase", REJECT, lambda u: u.update(linkedin="Ada"))
U("linkedin_2_characters", REJECT, lambda u: u.update(linkedin="ab"))
U("linkedin_3_characters", ACCEPT, lambda u: u.update(linkedin="abc"))
U("linkedin_300_characters", ACCEPT, lambda u: u.update(linkedin="a" * 300))
U("linkedin_at_handle", REJECT, lambda u: u.update(linkedin="@ada"))
U("login_5000_characters", ACCEPT, lambda u: u.update(login="a" * 5000))
U("login_internal_newline", ACCEPT, lambda u: u.update(login="a\nb"))
U("displayName_5000_characters", ACCEPT, lambda u: u.update(displayName="D" * 5000))
U("displayName_zero_width_space_only", ACCEPT, lambda u: u.update(displayName="\u200b"))
U("displayName_edge_nbsp", REJECT, lambda u: u.update(displayName="Ada\u00a0"))
U("title_5000_characters", ACCEPT, lambda u: u.update(title="T" * 5000))

# Dataset sections.
U("dataset_key_5000_characters", ACCEPT, lambda u: u.update(datasets={"d" * 5000: S(u)}))
U(
    "dataset_key_edge_space",
    REJECT,
    lambda u: u.update(datasets={"ds ": S(u)}),
    project=[("ds", ACCEPT)],
)
U("dataset_key_empty", REJECT, lambda u: u.update(datasets={"": S(u)}), project=[("ds", ACCEPT)])
U(
    "other_dataset_section_invalid",
    REJECT,
    lambda u: u["datasets"].update(ds2={**copy.deepcopy(S(u)), "votes": {"ghid_7_s1": "sideways"}}),
    project=[("ds", ACCEPT), ("ds2", REJECT)],
)
U(
    "other_dataset_section_not_object",
    REJECT,
    lambda u: u["datasets"].update(ds2=5),
    project=[("ds", ACCEPT), ("ds2", REJECT)],
)
U(
    "only_another_dataset",
    ACCEPT,
    lambda u: u.update(datasets={"ds2": S(u)}),
    project=[("ds", ACCEPT), ("ds2", ACCEPT)],
)
U("fields_empty", ACCEPT, lambda u: S(u).update(fieldsToAnnotate=[]))
U("fields_duplicate", REJECT, lambda u: S(u).update(fieldsToAnnotate=["a", "a"]))
U("fields_reserved_fk", REJECT, lambda u: S(u).update(fieldsToAnnotate=["fk~a%3Ab"]))
U("fields_fk_with_real_colon", ACCEPT, lambda u: S(u).update(fieldsToAnnotate=["fk~a%3A:b"]))
U("fields_uppercase_fk", ACCEPT, lambda u: S(u).update(fieldsToAnnotate=["FK~a%3Ab"]))
U("field_key_5000_characters", ACCEPT, lambda u: S(u).update(fieldsToAnnotate=["f" * 5000]))
U("field_key_trailing_nel", REJECT, lambda u: S(u).update(fieldsToAnnotate=["cell_type\u0085"]))
U("lastAccessedAt_invalid", REJECT, lambda u: S(u).update(lastAccessedAt="2026-02-30T00:00:00Z"))

# Suggestion text: exact, and as long as the file allows.
U("label_5000_characters", ACCEPT, lambda u: sug(u).update(label="x" * 5000))
U("label_500_astral", ACCEPT, lambda u: sug(u).update(label="\U0001F600" * 500))
U("label_decomposed", ACCEPT, lambda u: sug(u).update(label="e\u0301" * 200))
U("label_empty", REJECT, lambda u: sug(u).update(label=""))
U("label_internal_newline", ACCEPT, lambda u: sug(u).update(label="T\ncell"))
U("ontology_empty", REJECT, lambda u: sug(u).update(ontologyId=""))
U("ontology_null", ACCEPT, lambda u: sug(u).update(ontologyId=None))
U("ontology_5000_characters", ACCEPT, lambda u: sug(u).update(ontologyId="o" * 5000))
U("ontology_edge_space", REJECT, lambda u: sug(u).update(ontologyId="CL:0000084 "))
U("evidence_20000_characters", ACCEPT, lambda u: sug(u).update(evidence="e" * 20000))
U("evidence_edge_space", REJECT, lambda u: sug(u).update(evidence=" x"))
U("evidence_null", ACCEPT, lambda u: sug(u).update(evidence=None))
U("evidence_blank", REJECT, lambda u: sug(u).update(evidence="   "))
U("markers_empty", ACCEPT, lambda u: sug(u).update(markers=[]))
U("markers_null", ACCEPT, lambda u: sug(u).update(markers=None))
U("markers_5000", ACCEPT, lambda u: sug(u).update(markers=[f"G{index}" for index in range(5000)]))
U("markers_logFC_string", REJECT, lambda u: sug(u).update(markers=[{"gene": "A", "logFC": "1"}]))
U("markers_logFC_null", REJECT, lambda u: sug(u).update(markers=[{"gene": "A", "logFC": None}]))
U("markers_number", REJECT, lambda u: sug(u).update(markers=[5]))
U("marker_gene_5000_characters", ACCEPT, lambda u: sug(u).update(markers=["g" * 5000]))
U("marker_object_gene_5000_characters", ACCEPT, lambda u: sug(u).update(markers=[{"gene": "g" * 5000}]))
U("markers_duplicate", ACCEPT, lambda u: sug(u).update(markers=["A", "A"]))
U("marker_gene_edge_space", REJECT, lambda u: sug(u).update(markers=[" CD3D"]))
U("marker_object_gene_edge_space", REJECT, lambda u: sug(u).update(markers=[{"gene": "CD3D\t"}]))
U("logFC_negative_zero", ACCEPT, lambda u: sug(u).update(markers=[{"gene": "A", "logFC": -0.0}]))
U("pval_largest_double", ACCEPT, lambda u: sug(u).update(markers=[{"gene": "A", "pval": 1.7976931348623157e308}]))
raw_user("logFC_1e400", REJECT, b'"logFC": 1.5', b'"logFC": 1e400')
raw_user("logFC_NaN", REJECT, b'"logFC": 1.5', b'"logFC": NaN')
raw_user("logFC_Infinity", REJECT, b'"logFC": 1.5', b'"logFC": Infinity')
raw_user("logFC_bigint400", REJECT, b'"logFC": 1.5', b'"logFC": 1' + b"0" * 400)
raw_user("logFC_bigint5000", REJECT, b'"logFC": 1.5', b'"logFC": 1' + b"0" * 5000)
raw_user("logFC_uppercase_exponent", ACCEPT, b'"logFC": 1.5', b'"logFC": 1.5E+0')
raw_user("logFC_leading_plus", REJECT, b'"logFC": 1.5', b'"logFC": +1.5')
raw_user("logFC_leading_zero", REJECT, b'"logFC": 1.5', b'"logFC": 01.5')
raw_user("logFC_trailing_dot", REJECT, b'"logFC": 1.5', b'"logFC": 1.')

# Whitespace: every member of the class at the edge of text, alone, and at the
# end of a bucket key; characters outside it are text.
WHITESPACE = [
    code
    for code in range(0x110000)
    if not 0xD800 <= code <= 0xDFFF and re.fullmatch(validator.ANNOTATION_WHITESPACE_CLASS, chr(code))
]
for code in WHITESPACE:
    character = chr(code)
    tag = f"u{code:04x}"
    U(f"whitespace_{tag}_label_leading", REJECT, lambda u, c=character: sug(u).update(label=c + "T cell"))
    U(f"whitespace_{tag}_label_only", REJECT, lambda u, c=character: sug(u).update(label=c))
    U(
        f"whitespace_{tag}_bucket_category_trailing",
        REJECT,
        lambda u, c=character: rename_bucket(u, "cell_type:Alpha" + c),
    )
for code in (0x180E, 0x200B, 0x200C, 0x2060, 0x00AD):
    character = chr(code)
    tag = f"u{code:04x}"
    U(f"text_{tag}_label_leading", ACCEPT, lambda u, c=character: sug(u).update(label=c + "T cell"))
    U(f"text_{tag}_bucket_category_trailing", ACCEPT, lambda u, c=character: rename_bucket(u, "cell_type:Alpha" + c))
U("comment_text_leading_nel", REJECT, lambda u: S(u)["comments"]["ghid_7_s1"][0].update(text="\u0085ok"))
U("comment_text_trailing_feff", REJECT, lambda u: S(u)["comments"]["ghid_7_s1"][0].update(text="ok\ufeff"))
U("comment_id_trailing_u001f", REJECT, lambda u: S(u)["comments"]["ghid_7_s1"][0].update(id="c1\u001f"))
U("login_leading_u001c", REJECT, lambda u: u.update(login="\u001cocto"))
U("title_trailing_ideographic_space", REJECT, lambda u: u.update(title="PhD\u3000"))

# Buckets.
U("bucket_empty_list", ACCEPT, lambda u: S(u)["suggestions"].update({"cell_type:Beta": []}))
U("bucket_no_colon", REJECT, lambda u: rename_bucket(u, "cell_type"))
U("bucket_category_with_colon", ACCEPT, lambda u: rename_bucket(u, "cell_type:A:B"))
U("bucket_fk_encoded_field", ACCEPT, lambda u: rename_bucket(u, "fk~a%3Ab:Alpha"))
U("bucket_field_edge_space", REJECT, lambda u: rename_bucket(u, "cell_type :Alpha"))
U("bucket_empty_field", REJECT, lambda u: rename_bucket(u, ":Alpha"))
U("bucket_empty_category", REJECT, lambda u: rename_bucket(u, "cell_type:"))
U("bucket_category_5000_characters", ACCEPT, lambda u: rename_bucket(u, "cell_type:" + "L" * 5000))

# Suggestion ids: ghid_<n>_<rest>, owned by the proposer.
U("id_without_owner", REJECT, lambda u: sug(u).update(id="s1"))
U("id_other_owner", REJECT, lambda u: sug(u).update(id="ghid_8_s1"))
U("id_shorter_owner_prefix", REJECT, lambda u: sug(u).update(id="ghid_1_2_x"), uid=12, filename="ghid_12.json")
U("id_longer_owner_prefix", REJECT, lambda u: sug(u).update(id="ghid_12_x"), uid=1, filename="ghid_1.json")
U("id_rest_empty", REJECT, lambda u: sug(u).update(id="ghid_7_"))
U("id_rest_leading_space", REJECT, lambda u: sug(u).update(id="ghid_7_ x"))
U("id_rest_trailing_nel", REJECT, lambda u: sug(u).update(id="ghid_7_x\u0085"))
U("id_rest_with_colon", REJECT, lambda u: sug(u).update(id="ghid_7_a:b"))
U("id_owner_leading_zero", REJECT, lambda u: sug(u).update(id="ghid_07_x"))
U("id_owner_zero", REJECT, lambda u: sug(u).update(id="ghid_0_x"))
U("id_owner_uppercase", REJECT, lambda u: sug(u).update(id="GHID_7_x"))
U("id_owner_without_separator", REJECT, lambda u: sug(u).update(id="ghid_7x"))
U("id_double_underscore", ACCEPT, lambda u: sug(u).update(id="ghid_7__x"))
U("id_internal_newline", ACCEPT, lambda u: sug(u).update(id="ghid_7_a\nb"))
U("id_5000_characters", ACCEPT, lambda u: sug(u).update(id="ghid_7_" + "i" * 5000))
U("id_percent_encoded_colon", ACCEPT, lambda u: sug(u).update(id="ghid_7_a%3Ab"))
U("id_fullwidth_colon", ACCEPT, lambda u: sug(u).update(id="ghid_7_a\uff1ab"))
U("id_uuid", ACCEPT, lambda u: sug(u).update(id="ghid_7_0f8fad5b-d9cb-469f-a165-70867728950e"))
U("id_duplicate_in_two_buckets", REJECT, lambda u: S(u)["suggestions"].update({"cell_type:Beta": [dict(sug(u))]}))
U("proposedBy_other", REJECT, lambda u: sug(u).update(proposedBy="ghid_8"))
U("proposedBy_other_with_its_id", REJECT, lambda u: sug(u).update(proposedBy="ghid_8", id="ghid_8_s1"))

# Votes, comments and deletion markers.
U("vote_uppercase", REJECT, lambda u: S(u).update(votes={"ghid_7_s1": "UP"}))
U("vote_null", REJECT, lambda u: S(u).update(votes={"ghid_7_s1": None}))
U("vote_key_with_colon", REJECT, lambda u: S(u).update(votes={"ghid_7_a:b": "up"}))
U("vote_key_without_owner", REJECT, lambda u: S(u).update(votes={"s1": "up"}))
U("vote_key_other_owner_unknown", ACCEPT, lambda u: S(u).update(votes={"ghid_99_zzz": "down"}))
U("vote_key_5000_characters", ACCEPT, lambda u: S(u).update(votes={"ghid_8_" + "v" * 5000: "up"}))
U("comment_author_other", REJECT, lambda u: S(u)["comments"]["ghid_7_s1"][0].update(authorUsername="ghid_8"))
U(
    "comment_id_duplicate",
    REJECT,
    lambda u: S(u)["comments"]["ghid_7_s1"].append(dict(S(u)["comments"]["ghid_7_s1"][0])),
)
U("comment_text_5000_characters", ACCEPT, lambda u: S(u)["comments"]["ghid_7_s1"][0].update(text="t" * 5000))
U("comment_id_5000_characters", ACCEPT, lambda u: S(u)["comments"]["ghid_7_s1"][0].update(id="c" * 5000))
U("comment_text_blank", REJECT, lambda u: S(u)["comments"]["ghid_7_s1"][0].update(text=" "))
U("comments_empty_list", ACCEPT, lambda u: S(u).update(comments={"ghid_7_s1": []}))
U("comment_key_without_owner", REJECT, lambda u: S(u).update(comments={"s1": []}))
U("comment_key_other_owner", ACCEPT, lambda u: S(u).update(comments={"ghid_8_s9": []}))
U("comment_createdAt_invalid", REJECT, lambda u: S(u)["comments"]["ghid_7_s1"][0].update(createdAt="2026-07-25"))
U("deleted_duplicate", REJECT, lambda u: S(u).update(deletedSuggestions={"cell_type:Alpha": ["ghid_7_s0", "ghid_7_s0"]}))
U("deleted_other_owner", REJECT, lambda u: S(u).update(deletedSuggestions={"cell_type:Alpha": ["ghid_8_s0"]}))
U("deleted_without_owner", REJECT, lambda u: S(u).update(deletedSuggestions={"cell_type:Alpha": ["s0"]}))
U("deleted_own_5000_characters", ACCEPT, lambda u: S(u).update(deletedSuggestions={"cell_type:Alpha": ["ghid_7_" + "d" * 5000]}))

# Timestamps.
for name, value, verdict in (
    ("date_leap_second", "2026-06-30T23:59:60Z", REJECT),
    ("date_feb29_2023", "2023-02-29T00:00:00Z", REJECT),
    ("date_feb29_2024", "2024-02-29T00:00:00Z", ACCEPT),
    ("date_year_0", "0000-01-01T00:00:00Z", REJECT),
    ("date_year_1", "0001-01-01T00:00:00Z", ACCEPT),
    ("date_milliseconds", "2026-07-25T01:02:03.456Z", ACCEPT),
    ("date_4_fraction_digits", "2026-07-25T01:02:03.4567Z", REJECT),
    ("date_1_fraction_digit", "2026-07-25T01:02:03.4Z", REJECT),
    ("date_lowercase_z", "2026-07-25T01:02:03z", REJECT),
    ("date_offset", "2026-07-25T01:02:03+00:00", REJECT),
    ("date_hour_24", "2026-07-25T24:00:00Z", REJECT),
    ("date_space_separator", "2026-07-25 01:02:03Z", REJECT),
    ("date_trailing_newline", "2026-07-25T01:02:03Z\n", REJECT),
):
    U(name, verdict, lambda u, value=value: u.update(updatedAt=value))
U("suggestion_editedAt_invalid", REJECT, lambda u: sug(u).update(editedAt="2026-13-01T00:00:00Z"))

# Bytes and JSON syntax.
emit("user", "raw_byte_order_mark", REJECT, b"\xef\xbb\xbf" + BASE_USER)
emit("user", "raw_crlf", ACCEPT, BASE_USER.replace(b"\n", b"\r\n"))
raw_user("raw_latin1", REJECT, b'"T cell"', b'"T c\xe9ll"')
raw_user("raw_cesu8_surrogate", REJECT, b'"T cell"', b'"T \xed\xa0\x80"')
raw_user("raw_overlong_utf8", REJECT, b'"T cell"', b'"T \xc0\xaf"')
raw_user("raw_duplicate_key", REJECT, b'"version": 3,', b'"version": 3, "version": 3,')
raw_user("raw_duplicate_key_escaped", REJECT, b'"version": 3,', b'"version": 3, "\\u0076ersion": 3,')
raw_user("raw_duplicate_key_nested", REJECT, b'"votes": {', b'"votes": {"ghid_7_s1": "down",')
raw_user("raw_lone_surrogate_escape", ACCEPT, b'"T cell"', b'"\\ud800T"')
raw_user("raw_escaped_label", ACCEPT, b'"T cell"', b'"\\u0054 cell\\/x"')
raw_user("raw_escaped_nel_label_edge", REJECT, b'"T cell"', b'"\\u0085T cell"')
emit("user", "raw_trailing_garbage", REJECT, BASE_USER + b"x")
emit("user", "raw_trailing_whitespace", ACCEPT, BASE_USER + b"  \n\t\r\n")
emit("user", "raw_leading_whitespace", ACCEPT, b"\n  " + BASE_USER)
emit("user", "raw_trailing_nul", REJECT, BASE_USER + b"\x00")
emit("user", "raw_trailing_form_feed", REJECT, BASE_USER + b"\x0c")
emit("user", "raw_empty", REJECT, b"")
emit("user", "raw_null", REJECT, b"null")
emit("user", "raw_array", REJECT, b"[]")
emit("user", "raw_two_documents", REJECT, BASE_USER + BASE_USER)
raw_user("raw_single_quotes", REJECT, b'"T cell"', b"'T cell'")
raw_user("raw_trailing_comma", REJECT, b'"down"\n', b'"down",\n')
raw_user("raw_form_feed_whitespace", REJECT, b"{\n", b"{\x0c\n")
raw_user("raw_unescaped_tab", REJECT, b'"T cell"', b'"T\tcell"')
raw_user("raw_unescaped_delete", ACCEPT, b'"T cell"', b'"T\x7fcell"')
raw_user("raw_invalid_escape", REJECT, b'"T cell"', b'"T \\x41"')
raw_user("raw_short_unicode_escape", REJECT, b'"T cell"', b'"T \\u004"')
raw_user("raw_unterminated_string", REJECT, b'"T cell"', b'"T cell')
emit("user", "raw_truncated", REJECT, BASE_USER[: len(BASE_USER) // 2])

# Nesting: ANNOTATION_JSON_MAX_DEPTH levels are read, one more is refused
# before decoding. No valid document nests so deep, so every one is rejected.
for depth in (100, 511, 512, 513, 1200, 100000):
    inner = depth - 1  # inside the document's own object
    raw_user(f"nesting_{depth}", REJECT, b'"version": 3,', b'"version": 3, "x": ' + b"[" * inner + b"]" * inner + b",")
for depth in (512, 513):
    emit("user", f"nesting_{depth}_top_level", REJECT, b"[" * depth + b"]" * depth)

# Size: at most 1,000,000 UTF-8 bytes, counted before decoding.
emit("user", "size_1000000_bytes", ACCEPT, BASE_USER, pad_to=1_000_000)
emit("user", "size_1000001_bytes", REJECT, BASE_USER, pad_to=1_000_001)
emit("user", "size_1048576_bytes", REJECT, BASE_USER, pad_to=1_048_576)


# --------------------------------------------------------------------------
# Repository configuration (version 1).


def config() -> dict[str, Any]:
    return {
        "version": 1,
        "supportedDatasets": [
            {
                "datasetId": "ds",
                "name": "Dataset",
                "fieldsToAnnotate": ["cell_type"],
                "annotatableSettings": {"cell_type": {"minAnnotators": 1, "threshold": 0.5}},
                "closedFields": [],
            }
        ],
    }


def E(c: dict[str, Any]) -> dict[str, Any]:
    return c["supportedDatasets"][0]


def ST(c: dict[str, Any]) -> dict[str, Any]:
    return E(c)["annotatableSettings"]["cell_type"]


def C(name: str, expect: str, mutate: Callable[[dict[str, Any]], Any]) -> None:
    c = config()
    replaced = mutate(c)
    emit("config", name, expect, c if replaced is None else replaced)


def rename_field(c: dict[str, Any], field: str) -> None:
    E(c).update(fieldsToAnnotate=[field], annotatableSettings={field: {"minAnnotators": 1, "threshold": 0.5}})


BASE_CONFIG = _text(config()).encode("utf-8")


def raw_config(name: str, expect: str, old: bytes, new: bytes) -> None:
    assert BASE_CONFIG.count(old) == 1, old
    emit("config", name, expect, BASE_CONFIG.replace(old, new))


C("valid", ACCEPT, lambda c: None)
C("version_2", REJECT, lambda c: c.update(version=2))
C("version_float_1_0", ACCEPT, lambda c: c.update(version=1.0))
C("unknown_field", REJECT, lambda c: c.update(extra=True))
for name, value, verdict in (
    ("minAnnotators_0", 0, ACCEPT),
    ("minAnnotators_100", 100, ACCEPT),
    ("minAnnotators_max_safe", 9007199254740991, ACCEPT),
    ("minAnnotators_above_max_safe", 9007199254740992, REJECT),
    ("minAnnotators_2p60", 2**60, REJECT),
    ("minAnnotators_1e20", 1e20, REJECT),
    ("minAnnotators_float_1_0", 1.0, ACCEPT),
    ("minAnnotators_fraction", 1.5, REJECT),
    ("minAnnotators_negative", -1, REJECT),
    ("minAnnotators_string", "1", REJECT),
    ("minAnnotators_null", None, REJECT),
):
    C(name, verdict, lambda c, value=value: ST(c).update(minAnnotators=value))
raw_config("minAnnotators_2p53_plus_1", REJECT, b'"minAnnotators": 1', b'"minAnnotators": 9007199254740993')
raw_config("minAnnotators_bigint400", REJECT, b'"minAnnotators": 1', b'"minAnnotators": 1' + b"0" * 400)
raw_config("minAnnotators_bigint5000", REJECT, b'"minAnnotators": 1', b'"minAnnotators": 1' + b"0" * 5000)
for name, value, verdict in (
    ("threshold_1", 1, ACCEPT),
    ("threshold_minus_1", -1, ACCEPT),
    ("threshold_tiny", 1e-300, ACCEPT),
    ("threshold_above_1", 1.0000001, REJECT),
    ("threshold_string", "0.5", REJECT),
    ("threshold_null", None, REJECT),
):
    C(name, verdict, lambda c, value=value: ST(c).update(threshold=value))
raw_config("threshold_bigint400", REJECT, b'"threshold": 0.5', b'"threshold": 1' + b"0" * 400)
C("field_leading_feff", REJECT, lambda c: rename_field(c, "\ufeffcell_type"))
C("field_trailing_nel", REJECT, lambda c: rename_field(c, "cell_type\u0085"))
C("field_leading_u001c", REJECT, lambda c: rename_field(c, "\u001ccell_type"))
C("field_5000_characters", ACCEPT, lambda c: rename_field(c, "f" * 5000))
C("field_reserved_fk", REJECT, lambda c: rename_field(c, "fk~a%3Ab"))
C("field_with_colon", ACCEPT, lambda c: rename_field(c, "cell:type"))
C("name_trailing_nel", REJECT, lambda c: E(c).update(name="Dataset\u0085"))
C("name_5000_characters", ACCEPT, lambda c: E(c).update(name="n" * 5000))
C("datasetId_5000_characters", ACCEPT, lambda c: E(c).update(datasetId="d" * 5000))
C("datasetId_edge_space", REJECT, lambda c: E(c).update(datasetId=" ds"))
C("closed_not_in_fields", REJECT, lambda c: E(c).update(closedFields=["other"]))
C("closed_duplicate", REJECT, lambda c: E(c).update(closedFields=["cell_type", "cell_type"]))
C("closed_field", ACCEPT, lambda c: E(c).update(closedFields=["cell_type"]))
C("settings_missing", REJECT, lambda c: E(c).update(annotatableSettings={}))
C("settings_extra", REJECT, lambda c: E(c)["annotatableSettings"].update(other={"minAnnotators": 1, "threshold": 0.5}))
C("dataset_duplicate", REJECT, lambda c: c["supportedDatasets"].append(copy.deepcopy(E(c))))
C("datasets_empty", REJECT, lambda c: c.update(supportedDatasets=[]))
C("fields_empty", REJECT, lambda c: E(c).update(fieldsToAnnotate=[], annotatableSettings={}))


def many_fields(c: dict[str, Any]) -> None:
    for index in range(300):
        E(c)["fieldsToAnnotate"].append(f"field_{index}")
        E(c)["annotatableSettings"][f"field_{index}"] = {"minAnnotators": 1, "threshold": 0.5}


C("many_fields", ACCEPT, many_fields)
emit("config", "raw_byte_order_mark", REJECT, b"\xef\xbb\xbf" + BASE_CONFIG)


# --------------------------------------------------------------------------
# Moderation merges (version 3).


def merges() -> dict[str, Any]:
    return {
        "version": 3,
        "updatedAt": T,
        "merges": [
            {
                "datasetId": "ds",
                "bucket": "cell_type:Alpha",
                "fromSuggestionId": "ghid_7_a",
                "intoSuggestionId": "ghid_8_b",
                "by": "ghid_9",
                "at": T,
                "note": None,
                "editedAt": None,
            }
        ],
    }


def M0(m: dict[str, Any]) -> dict[str, Any]:
    return m["merges"][0]


def M(
    name: str,
    expect: str,
    mutate: Callable[[dict[str, Any]], Any],
    *,
    project: list[tuple[str, str]] | None = None,
) -> None:
    m = merges()
    replaced = mutate(m)
    emit("merges", name, expect, m if replaced is None else replaced, project=project)


M("valid", ACCEPT, lambda m: None, project=[("ds", ACCEPT), ("other", ACCEPT)])
M("empty", ACCEPT, lambda m: m.update(merges=[]), project=[("ds", ACCEPT)])
M(
    "version_2_file",
    REJECT,
    lambda m: {
        "version": 2,
        "updatedAt": T,
        "merges": [
            {"datasetId": "ds", "bucket": "cell_type:Alpha", "fromSuggestionId": "a", "intoSuggestionId": "b", "by": "ghid_7", "at": T}
        ],
    },
    project=[("ds", REJECT)],
)
M("version_2_otherwise_v3", REJECT, lambda m: m.update(version=2))
M("version_1", REJECT, lambda m: m.update(version=1))
M("missing_datasetId", REJECT, lambda m: M0(m).pop("datasetId"))
M("unknown_field", REJECT, lambda m: M0(m).update(extra=1))
M("from_equals_into", REJECT, lambda m: M0(m).update(intoSuggestionId="ghid_7_a"))
M("duplicate_from_same_dataset", REJECT, lambda m: m["merges"].append({**M0(m), "intoSuggestionId": "ghid_8_c"}))
M("duplicate_from_other_dataset", ACCEPT, lambda m: m["merges"].append({**M0(m), "datasetId": "ds2", "intoSuggestionId": "ghid_8_c"}))
M("cycle", REJECT, lambda m: m["merges"].append({**M0(m), "fromSuggestionId": "ghid_8_b", "intoSuggestionId": "ghid_7_a"}))
M(
    "reverse_in_other_dataset",
    ACCEPT,
    lambda m: m["merges"].append({**M0(m), "datasetId": "ds2", "fromSuggestionId": "ghid_8_b", "intoSuggestionId": "ghid_7_a"}),
)
M(
    "cycle_of_3",
    REJECT,
    lambda m: m["merges"].extend(
        [
            {**M0(m), "fromSuggestionId": "ghid_8_b", "intoSuggestionId": "ghid_9_c"},
            {**M0(m), "fromSuggestionId": "ghid_9_c", "intoSuggestionId": "ghid_7_a"},
        ]
    ),
)
M("note_empty", REJECT, lambda m: M0(m).update(note=""))
M("note_5000_characters", ACCEPT, lambda m: M0(m).update(note="n" * 5000))
M("note_trailing_u2028", REJECT, lambda m: M0(m).update(note="same\u2028"))
M("by_ghid_0", REJECT, lambda m: M0(m).update(by="ghid_0"))
M("datasetId_trailing_nel", REJECT, lambda m: M0(m).update(datasetId="ds\u0085"), project=[("ds", ACCEPT)])
M("datasetId_5000_characters", ACCEPT, lambda m: M0(m).update(datasetId="d" * 5000))
M("datasetId_number", REJECT, lambda m: M0(m).update(datasetId=5), project=[("ds", ACCEPT)])
M("bucket_leading_feff", REJECT, lambda m: M0(m).update(bucket="\ufeffcell_type:Alpha"))
M("from_without_owner", REJECT, lambda m: M0(m).update(fromSuggestionId="a"))
M("into_without_owner", REJECT, lambda m: M0(m).update(intoSuggestionId="b"))
M("from_with_colon", REJECT, lambda m: M0(m).update(fromSuggestionId="ghid_7_a:b"))
M("into_rest_trailing_space", REJECT, lambda m: M0(m).update(intoSuggestionId="ghid_8_b "))
M("ids_5000_characters", ACCEPT, lambda m: M0(m).update(fromSuggestionId="ghid_7_" + "f" * 5000))
M(
    "other_dataset_invalid",
    REJECT,
    lambda m: m["merges"].append({**M0(m), "datasetId": "ds2", "intoSuggestionId": "ghid_7_a"}),
    project=[("ds", ACCEPT), ("ds2", REJECT)],
)
M(
    "open_dataset_invalid",
    REJECT,
    lambda m: m["merges"].append({**M0(m), "fromSuggestionId": "ghid_8_c", "note": " x"}),
    project=[("ds", REJECT), ("ds2", ACCEPT)],
)
M("entry_not_object", REJECT, lambda m: m["merges"].append(5), project=[("ds", ACCEPT)])
M("merges_not_array", REJECT, lambda m: m.update(merges={}), project=[("ds", REJECT)])
M("updatedAt_invalid", REJECT, lambda m: m.update(updatedAt="yesterday"), project=[("ds", REJECT)])


# --------------------------------------------------------------------------


def build() -> bytes:
    schemas = {}
    for kind, (_, schema_path) in validator.VALIDATORS.items():
        relative = schema_path.relative_to(ROOT).as_posix()
        raw = schema_path.read_bytes()
        schemas[kind] = {
            "path": relative,
            "blobOid": validator.git_blob_oid(raw),
            "text": raw.decode("utf-8"),
        }
    document = {
        "description": (
            "Shared accept/reject corpus of the Cellucid community-annotation "
            "contract. Generated by cellucid-annotation/scripts/generate_contract_corpus.py; "
            "do not edit. The repository validator and the Cellucid web app must both "
            "give every case its expected verdict."
        ),
        "fileMaxUtf8Bytes": validator.ANNOTATION_FILE_MAX_UTF8_BYTES,
        "jsonMaxDepth": validator.ANNOTATION_JSON_MAX_DEPTH,
        "whitespaceClass": validator.ANNOTATION_WHITESPACE_CLASS,
        "whitespaceCodePoints": WHITESPACE,
        "schemas": schemas,
        "cases": cases,
    }
    return (json.dumps(document, indent=1, ensure_ascii=True) + "\n").encode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail instead of writing when a copy is stale")
    parser.add_argument("--copy", type=pathlib.Path, action="append", default=[], help="another copy to write or check")
    arguments = parser.parse_args()
    content = build()
    stale = []
    for target in [FIXTURE, *arguments.copy]:
        if arguments.check:
            if not target.is_file() or target.read_bytes() != content:
                stale.append(target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    if stale:
        for target in stale:
            print(f"{target}: stale; run python scripts/generate_contract_corpus.py", file=sys.stderr)
        return 1
    print(f"{len(cases)} cases, sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
