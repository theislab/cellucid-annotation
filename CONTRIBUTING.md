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
| `cellucid-r` | R package exporter | are changing `cellucid_prepare()` |
| `cellucid-annotation` (this repo) | Reference annotation layout | are changing a schema, the validator, or the workflow |
| `cellucid-datasets` | The published demo catalog | are correcting a published generation or its catalog entry |
| `cellucid-demo-custom-datasets` | Worked example of publishing your own datasets | are changing that guide or its synthetic examples |

The annotation contract has two implementations that have to agree: the
validator here, and the viewer's wire contract in
`cellucid/assets/js/app/community-annotations/wire-contract.js`. A rule that
changes in one has to change in the other, in the same pass, or a repository
this validator accepts is one the browser rejects.

---

## What is a contract change, and what is not

The three `$id` values in `annotations/*.schema.json` are published
identifiers. They are compared as exact strings by the validator and by the
viewer, and every repository already validated against them keeps working only
while they stay byte-identical. Tightening a rule under an existing `$id`
breaks documents that were valid yesterday. A genuine contract change takes a
new `-v2` identity instead of editing a published one.

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
python scripts/validate_user_files.py
```

These are the same commands `.github/workflows/validate.yml` runs, so a green
local run is the same check CI applies. The validator takes no arguments and
writes nothing: it reads the checked-in schemas and every input document beside
them.

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
