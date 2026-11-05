# Contributing to the Cellucid annotation layout

Contributions are welcome — schema corrections, validator rules, tests, and
issues about a repository Cellucid refuses to connect to.

This file focuses on `cellucid-annotation`, the reference layout for a
GitHub-backed community annotation repository. It describes contributing **to
this layout**. If you are running an annotation round, you do not contribute
here: you work in your own repository through the Cellucid UI, and the README
is your guide.

By participating, you agree to follow the project’s Code of Conduct:
- `CODE_OF_CONDUCT.md`

If you’re reporting a security issue, please follow:
- `SECURITY.md`

---

## Which repo should I contribute to?

Cellucid is split by responsibility:

| Repo | What it is | Contribute here when you… |
|---|---|---|
| `cellucid` | Web app (UI + state + WebGL rendering) | are changing sign-in, Pull, consensus compilation, or Publish |
| `cellucid-python` | Python package + CLI + Sphinx docs | are fixing `prepare`/`serve`, or any documentation page for any repository |
| `cellucid-r` | R package writing the same Cellucid-ready AnnData from R | are changing `cellucid_prepare()` |
| `cellucid-annotation` (this repo) | Reference annotation layout | are changing a schema, the validator, or the workflow |
| `cellucid-datasets` | The published demo catalog | are correcting a published generation or its catalog entry |
| `cellucid-demo-custom-datasets` | Worked example of publishing your own datasets | are changing that guide or its synthetic examples |

The annotation contract has two implementations that have to agree: the
validator here, and the viewer's wire contract in
`cellucid/assets/js/app/community-annotations/wire-contract.js`. A rule that
changes in one has to change in the other, in the same pass, or a repository
this validator accepts is one the browser rejects. One accept/reject corpus,
`tests/fixtures/contract-corpus.json` (written by
`scripts/generate_contract_corpus.py`, with a byte-identical copy and the same
SHA-256 pin in the web app's test suite), holds both to the same verdict on
every case: a rule change adds its cases there and regenerates it.

---

## What is a contract change, and what is not

The three schema files are published by content: the validator and the
viewer accept a repository only when its schemas are exactly these files (the
same Git blob ids, pinned in both), so any edit to a schema — a rule, a
description, a line ending — is a contract change that every annotation
repository has to copy. Tightening a rule breaks documents that were valid
yesterday, so a genuine contract change also takes a new versioned identity
(the next `-vN` of its `$id`) and file version.

Everything the README says about those reservations — the `fk~` field-key
shape, the `:` delimiter in suggestion ids, the 1,000,000-byte document
ceiling, the exact timestamp grammar — is asserted by
`tests/test_validate_user_files.py` against the README text itself. Changing a
rule therefore means changing the schema, the validator, the tests, and the
README together.

---

## Testing & validation

Python 3.10 or newer is required (CI runs 3.10, 3.12 and 3.14 on Linux, macOS
and Windows). From the repository root:

```bash
python -m unittest discover -s tests -v
python scripts/generate_contract_corpus.py --check
python scripts/validate_user_files.py
```

These are the same commands `.github/workflows/tests.yml` runs, so a green
local run is the same check CI applies; `.github/workflows/validate.yml`, the
workflow annotation repositories copy, runs only the last one. The validator
takes no arguments and writes nothing: it reads the checked-in schemas and
every input document beside them.

A new rule needs a test that fails without it. The suite is written as exact
contracts rather than examples — it asserts the precise message and the precise
boundary — so a rule added without one is a rule nothing holds in place.

---

## PR guidelines

- Keep PRs small and focused (one rule, or one schema).
- Include what changed, why, and the document that motivated it.
- Never attach a real annotation repository's user files: they carry GitHub
  identities and profile metadata. Write a minimal synthetic document instead.
- If you changed a rule a user can trip, update `README.md` in the same change.
