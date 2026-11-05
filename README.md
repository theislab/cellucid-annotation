# Cellucid community annotation repository

This repository is the validated reference layout for a
**GitHub annotation repository** used by
[Cellucid](https://github.com/theislab/cellucid). It gives a research group one
shared place for label suggestions, votes, discussion, consensus settings, and
optional moderation—without putting multiple annotators into the same file.

The core idea is simple: Cellucid writes one file per GitHub user, so ordinary
annotation work does not create shared-file merge conflicts. On **Pull**,
Cellucid validates the repository and compiles the merged consensus view in the
browser.

This repository stores annotation records only. Keep the dataset itself (the
AnnData file or Zarr store Cellucid opens, with its embeddings and expression
matrix) in a separate dataset source. See the
[complete community annotation guide](https://docs.cellucid.com/en/latest/user_guide/web_app/j_community_annotation/index.html)
for the author walkthrough, annotator walkthrough, UI reference, screenshots,
and troubleshooting.

## Contract and layout

The annotation layout — what an annotation repository holds:

- `annotations/schema.json` - exact JSON schema for user files
- `annotations/config.schema.json` - exact JSON schema for repository configuration
- `annotations/config.json` - Dataset binding + author-controlled annotatable fields + per-field consensus settings
- `annotations/users/*.json` - Per-user suggestions & votes, kept per dataset (conflict-free collaboration)
- `annotations/users/.gitkeep` - Keeps the empty user inventory in Git (one LF byte)
- `annotations/moderation/merges.schema.json` - exact JSON schema for moderation merges
- `annotations/moderation/merges.json` - Optional author-only merges (maintainers/admins)
- `scripts/validate_user_files.py` - Validation script (run by CI and usable locally)
- `.github/workflows/validate.yml` - GitHub Actions workflow that runs the validator
- `.gitattributes` - Checks every file out with LF line endings, on every platform

Only files declared by this layout belong in the annotation contract. A
compiled consensus file is deliberately not committed: it is a view derived
from the validated user files, configuration, and moderation merges.

This repository also tests the layout itself, and none of that is copied:
`tests/` (the contract test suite), `scripts/generate_contract_corpus.py` (it
writes `tests/fixtures/contract-corpus.json`, the accept/reject corpus this
validator and the Cellucid web app must agree on), and
`.github/workflows/tests.yml` (runs that suite). Beside them, the root carries
the governance files the Cellucid repositories carry — `LICENSE`,
`CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md`,
`CITATION.cff` — plus `.gitignore`. They govern this repository; an annotation
repository built from it does not need them. Copy the layout files listed above
and give your own repository its own licence and policies.

The three schemas declare these identities:

- `https://cellucid.com/contracts/community-annotation/user-v3.schema.json`
- `https://cellucid.com/contracts/community-annotation/config-v1.schema.json`
- `https://cellucid.com/contracts/community-annotation/merges-v3.schema.json`

These `$id` values are **identifiers, not links**: nothing fetches them, and
they are not required to resolve. They deliberately use the bare apex
`cellucid.com`, while every URL meant to be opened in a browser — the
[live application](https://www.cellucid.com) included — uses the canonical
`www.cellucid.com` host. A genuine contract change gets a new versioned
identity (the next `-vN`).

Cellucid and the validator identify the schemas by their **content**: a
repository is accepted only when its three schema files are exactly the ones
published here, byte for byte (the same Git blob). Cellucid reads their blob ids
from the repository's Git tree, so it never downloads them; when one differs, it
names the file and asks you to copy it from this repository. Do not edit the
schemas, and do not "normalise" their text: copy them unchanged.

## How collaboration works

This template is designed for many annotators to collaborate safely:

- Each person contributes only `annotations/users/ghid_<id>.json`.
- Authors with `maintain` or `admin` repository permission can optionally
  curate `annotations/moderation/merges.json`.
- In Cellucid, **Pull** downloads the raw files under `annotations/users/` and
  `annotations/moderation/` (by Git blob id: it downloads only what changed) and
  compiles a merged view locally.
  - The browser cache is scoped by **datasetId + repo + branch + GitHub user.id** (multi-user + multi-project safe).
- Cellucid can export a locally-built `cellucid-consensus.json` snapshot from
  the sidebar (useful for downstream tooling); it is not committed back to the
  repo.

Local edits are saved in the browser first. **Publish** sends the current
user's file to GitHub and, for an author changing round settings, also updates
`annotations/config.json`. Other collaborators see published work after their
next Pull. GitHub remains the shared source of truth; browser state is a local
working copy.

### Consensus model

Annotation is scoped to one dataset id, one categorical observation field, and
one category within that field. That combination is a **bucket**. No file here
names a cell, so the same files serve every way the dataset is opened: all of
its cells or a subsample of them, and a file stored in any cell order (files
Cellucid writes store their cells in priority order). Users propose
labels inside a bucket and cast `up` or `down` votes on those suggestions.

For each bucket, Cellucid counts unique users who cast any vote, computes the
leading suggestion's net votes (`up - down`), and reports
`confidence = net votes / unique voters`.

- **Pending**: fewer unique voters than the field's `minAnnotators`
- **Consensus**: the leader is not tied and its confidence meets or exceeds the
  field's `threshold`
- **Disputed**: every other result, including a tie

The exact settings are owned per field in `annotations/config.json`.
`minAnnotators` is a whole number of at least 0 (up to
9,007,199,254,740,991, the largest integer a browser holds exactly), and
`threshold` is a number from -1 through 1. Choose these values before
recruiting annotators and record them when exporting a result; changing them
can change the derived status without changing anyone's votes.

## Set up an annotation round

1. Create a new GitHub repository and copy the layout files listed above —
   `annotations/` (with `annotations/users/.gitkeep`),
   `scripts/validate_user_files.py`, `.github/workflows/validate.yml` and
   `.gitattributes` — into its root, at the same paths. Copy the schemas
   unchanged. Leave this repository's tests, licence and policy files behind
   and give yours its own.
2. Configure `annotations/config.json` to match your dataset id(s) and annotatable field(s).
   - The checked-in `example-dataset-id` / `cell_type` / `batch` entry is a
     valid worked example; replace it with the exact identifiers in your
     dataset.
   - `supportedDatasets[]` may include multiple dataset ids.
   - Every dataset entry requires `datasetId`, `name`, `fieldsToAnnotate`, `annotatableSettings`, and `closedFields`.
   - Every field in `fieldsToAnnotate` has exactly one `annotatableSettings` entry with both `minAnnotators` and `threshold`; missing and extra settings are invalid.
   - `fieldsToAnnotate` must contain at least one field. `closedFields` may be
     empty, but every listed closed field must also appear in
     `fieldsToAnnotate`.
   - Contract strings are exact and nonblank: they cannot have leading or
     trailing whitespace. No string has a length limit.
   - Cellucid reserves one colon-free field-key shape for bucket encoding: a
     key that starts with exact lowercase `fk~` and contains `%3A` or `%3a` is
     invalid. Keys such as `fk~foo`, `plain%3Afoo`, and `fk~foo%253Abar`
     remain valid, as do field keys that actually contain `:`. This narrow
     reservation keeps colon-bearing field keys distinct from their encoded
     bucket representation.
   - Authors can update these fields via the Cellucid UI (Publish writes back to `annotations/config.json`).
3. Run the local validator before connecting the repository:
   `python scripts/validate_user_files.py`.
4. Install the Cellucid GitHub App for the repository owner and grant it access
   to this repository.
5. Load the matching dataset in Cellucid, open **Community Annotation**, and
   connect via **GitHub App sign-in** (no token paste). Cellucid
   selects one route before mutation: `direct` for a user with source write
   permission, or `fork-pull-request` for a contributor when the source permits
   forking. A failed selected route is terminal and is never changed into the
   other route. The app needs Contents read/write, Pull requests read/write and
   Metadata read; no Administration, as Cellucid never creates a fork.
6. Pull once before annotating. Each collaborator then works through Cellucid;
   a Publish writes that collaborator's `ghid_<id>.json`, and an author's
   Publish also writes `annotations/config.json` and
   `annotations/moderation/merges.json` when their settings or merges changed.
   An agent's (or a notebook's) vote or suggestion writes only the
   collaborator's file, with that one change.

The loaded dataset's exact id must occur in `supportedDatasets`. A mismatch is
blocked rather than attached to a similarly named dataset. Authors may add the
current dataset through the UI and Publish the resulting configuration;
annotators cannot bypass the binding.

## CI / GitHub Actions

### Validate inputs (`validate.yml`)

File: `.github/workflows/validate.yml` — the workflow an annotation repository
copies.

- Runs on every push and pull request, on Ubuntu, with read-only access to the
  repository (`permissions: contents: read`).
- Runs one command, `python scripts/validate_user_files.py`, which needs
  nothing but the layout files. It checks:
  - the three schemas are the canonical ones, byte for byte;
  - `annotations/config.json`;
  - every entry under `annotations/users/`: only `ghid_<id>.json` user files
    and the `.gitkeep` sentinel may be there (no other file, directory or
    link);
  - `annotations/moderation/merges.json` (optional);
  - that no path is a case variant of a layout path (such as
    `annotations/Users/`), which Cellucid never reads.

If this fails, fix the JSON files in `annotations/` (do not edit any derived/exported outputs).

CI is a gate for pull requests and a report for everything else: a
collaborator with write access publishes directly, before CI runs. Cellucid
therefore never trusts the repository to be valid (see below).

### Template tests (`tests.yml`)

File: `.github/workflows/tests.yml` — this repository's own test suite. It is
not part of the layout and is not copied. It runs the contract tests, checks
that the shared corpus is current, and runs the validator on Python 3.10, 3.12
and 3.14 on Linux, macOS and Windows.

## Local development / debugging

You can run the same checks locally (Python 3.10+ is required):

```bash
# Validate every input (what humans/clients write)
python scripts/validate_user_files.py

# In this repository only: the contract test suite and the corpus check
python -m unittest discover -s tests -v
python scripts/generate_contract_corpus.py --check
```

The validator reads the checked-in schemas directly, rejects unknown fields,
wrong JSON types, duplicate JSON keys, and malformed JSON, and inspects every
array item. Any input is reported as an error, never as a crash: a file over
the size bound, invalid UTF-8, a byte-order mark, JSON nested deeper than 512
levels (Python's recursion limit, 1000 by default, decides how deep its JSON
reader can go; no valid file nests deeper than 7) and integers of any size
included. A user document is accepted only when its filename is exactly
`ghid_<githubUserId>.json` and its `username` is the same `ghid_<githubUserId>`
identity.

Validation never coerces, truncates, migrates, skips, or repairs input. The
Cellucid web app applies the same rules — one shared accept/reject corpus,
`tests/fixtures/contract-corpus.json`, holds this validator and the app to the
same verdict on every case — but it reads a repository file by file:

- A file that fails is **quarantined**: Cellucid leaves it out of the
  consensus, keeps the reason, says how many files it left out (with each
  file and its reason on demand), and goes on with the rest. One broken file
  never stops a Pull, and the result is never silently wrong.
- For the open dataset, Cellucid reads a user file's profile and that
  dataset's section only. A broken section of another dataset does not make
  the file fail for this one.
- Anything under `annotations/users/` that is not a `ghid_<id>.json` file, and
  any case variant of a layout path, is ignored and listed, never read.

The validator is stricter by design: it rejects all of these, so CI keeps the
repository clean.

### Text and whitespace

Every text field — labels, evidence, ontology ids, marker genes, comments,
merge notes, profile fields, dataset ids and names, field keys, bucket keys,
suggestion and comment ids — is **exact**: its first and last characters are
not whitespace, and it is never trimmed. Whitespace is one class everywhere
(the schemas, the validator and the app): the union of JavaScript's `\s` and
Python's `str.isspace()`,
`[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]`.
Whitespace inside text is kept as written.

No text and no count has a length limit. The only size bound is the file:
every active `annotations/config.json`, `annotations/users/ghid_<id>.json`, and
optional `annotations/moderation/merges.json` file must be at most **1,000,000
UTF-8 bytes**. The validator rejects a larger file before JSON parsing,
matching the boundary for the GitHub
[repository Contents API](https://docs.github.com/en/rest/repos/contents),
which returns a file's content as JSON only up to 1 MB. Archive historical
material outside `annotations/` and keep each active document complete; files
are never truncated. Every integer is at most 9,007,199,254,740,991, the
largest integer a browser holds exactly.

### Suggestion identifiers

Every suggestion id names its owner: it is `ghid_<id>_<rest>`, the proposer's
GitHub identity, `_`, then exact text without `:` (Cellucid writes
`ghid_<id>_<random UUID>`). A suggestion's id must start with its own
`proposedBy` followed by `_`, and the digits of `ghid_<id>` end at that `_`, so
`ghid_1_` never prefixes `ghid_12_...`. No contributor can therefore write an
id that collides with, or claims to be, another contributor's suggestion.
Votes, comments and merges may name anyone's suggestion; `deletedSuggestions`
names only the file owner's own. Within one dataset of a file, suggestion ids
are unique; two datasets may use the same id. Suggestion ids cannot contain `:`
because Cellucid reserves that character as the delimiter between a bucket key
and a suggestion id.

### Paths

Files must be UTF-8 JSON without a byte-order mark. User files must be direct
children of `annotations/users/`, named exactly `ghid_<id>.json`; case variants
and nested paths are invalid. The only other entry permitted there is the
checked-in `.gitkeep`, whose complete content is one LF byte so an empty user
inventory remains representable in Git (`.gitattributes` keeps it so on every
platform).

Cellucid also rejects alternate Git blob encodings and truncated Git tree
responses. Its raw-file cache requires IndexedDB; an unavailable, corrupt, or
failed storage boundary is reported as an error instead of being replaced with
an in-memory cache.

## Author-only merges (optional)

If you maintain the repo and want to "merge" suggestions (e.g. two different labels that should be treated as the same), you can add `annotations/moderation/merges.json`.

- This file is optional and typically restricted to maintainers/admins.
- Merges create a mapping from `fromSuggestionId` → `intoSuggestionId` within the same bucket of the same dataset; every merge names its `datasetId`, so the same bucket name in another dataset is never affected.
- Bucket key format: `<fieldKey>:<categoryLabel>`. If `fieldKey` contains `:`, Cellucid encodes it as `fk~<urlencoded>` (example: `fk~celltype%3Acoarse:...`).
- Category labels may contain `:`; suggestion ids may not, so the complete
  bucket/id identity remains unambiguous.
- Cellucid applies this mapping at runtime when computing bundle vote totals and consensus.
- In the Cellucid UI, authors can add merges by dragging a suggestion card onto another.
  - The merge dialog includes an optional note.
  - You can later edit or delete the merge note from the bundle’s **View merged** modal (the merge mapping stays the same).
  - When a merge note is edited, the merge record may include `editedAt` (timestamp of the note edit) in addition to `at` (timestamp of the merge creation).

A merges file looks like this (version 3):

```json
{
  "version": 3,
  "updatedAt": "2026-07-25T01:02:03Z",
  "merges": [
    {
      "datasetId": "example-dataset-id",
      "bucket": "cell_type:0",
      "fromSuggestionId": "ghid_7_6f1c2c0e-3d1b-4e37-9a83-2f0b54c7d1a9",
      "intoSuggestionId": "ghid_8_0b9e4a51-7c2d-4f8e-b3a6-5d1e9c2f7a40",
      "by": "ghid_42",
      "at": "2026-07-25T01:02:03Z",
      "note": "Same population"
    }
  ]
}
```

## Profile fields

User files include identity metadata that Cellucid stores in each `annotations/users/*.json`:

- `githubUserId` (stable GitHub numeric id; file identity is `ghid_<id>`)
- `login` (GitHub username; informational only)
- `displayName`, `title`, `orcid`, `linkedin` (optional; ORCID uses the exact
  checksum-valid `0000-0000-0000-0000` representation — the final character is
  a check digit and is an uppercase `X` when that digit is ten, as in
  `0000-0000-0000-001X` — and LinkedIn uses an exact lowercase handle of at
  least 3 letters, digits or hyphens, without `@` or a URL)
- `datasets`: one section per dataset id. Each holds that dataset's access
  record (`fieldsToAnnotate`, `lastAccessedAt`) and the contributor's
  `suggestions`, `votes`, and optional `comments` and `deletedSuggestions` for
  it. Two datasets in one repository can share a field and a category label,
  so nothing a contributor writes for one dataset is ever read for another.

## Privacy and repository hygiene

An annotation repository can contain scientific discussion and user profile
metadata. Treat its GitHub visibility as the visibility of that content:
anything in a public repository is public.

- Do not store expression matrices, embeddings, clinical identifiers, source
  data, access tokens, private keys, or other secrets here.
- Use stable GitHub numeric identities (`ghid_<id>`) for ownership; `login` is
  informational because a GitHub username can change.
- Keep evidence useful but non-identifying. Link to public references when
  appropriate instead of copying sensitive source material into a suggestion.
- Review `login`, `displayName`, `title`, `orcid`, and `linkedin` before
  publishing; these fields become part of the user's GitHub file.
- Keep generated consensus downloads outside the repository unless a separate
  downstream workflow intentionally versions a frozen result.

Cellucid's OAuth token is not part of this file format. The web app keeps it in
`sessionStorage` (cleared when the tab closes) and never asks users to paste a
personal access token into the repository.

## Timestamps

- Every timestamp is UTC and must use exactly
  `YYYY-MM-DDTHH:MM:SSZ` or `YYYY-MM-DDTHH:MM:SS.sssZ`. Calendar dates
  and clock values must be real; offsets, lowercase `z`, and other fractional
  precision are rejected.
- Suggestions may include `editedAt` when the proposer edits a suggestion (e.g. label/evidence/ontology id/markers).
- Comments include `editedAt` when a comment is edited.

## FAQ / troubleshooting

### “Why is there no `annotations/consensus/merged.json`?”

This template does not commit a merged consensus artifact. Instead:

- Cellucid pulls the raw per-user files (`annotations/users/*.json`) and optional merges file (`annotations/moderation/merges.json`)
- Cellucid compiles the merged view locally in the browser on Pull
- You can download a compiled `cellucid-consensus.json` snapshot from the
  sidebar when needed

### “Why did Pull download lots of files the first time?”

The first Pull has to populate the local raw-file cache.

After that, Pull uses the Git blob id of each file to download only the
user/merge files that changed.

### “How do I force a clean re-download?”

In the Cellucid sidebar:

- Use **Clear downloads** to clear the raw-file cache for the current cache scope:
  - `datasetId`
  - `owner/repo@branch`
  - `user.id`
  then Pull again.

### “Why can’t I Pull when the dataset id doesn’t match?”

If the currently loaded dataset id is not listed in `annotations/config.json` for the connected repo:

- Annotators are blocked (no Pull / no viewing annotations).
- Authors can connect anyway and Publish updated settings; this adds/updates the matching `supportedDatasets[]` entry in `annotations/config.json`.

### “Why does Publish create a pull request?”

The selected publishing route depends on repository permission:

- A user with source write permission publishes directly.
- A contributor uses a fork and pull request when the source permits forking.
  Cellucid never creates the fork: the contributor first forks this
  repository on GitHub (`https://github.com/<owner>/<repo>/fork`) and installs
  the Cellucid GitHub App on their own account with access to that fork (*All
  repositories*, or *Only select repositories* with the fork selected). Without
  a fork, Publish says so and links to GitHub's fork page.

The route is selected before any write. If it fails, Cellucid reports that
failure instead of silently attempting the other route. Merge the pull request,
then ask collaborators to Pull again.

### “Why does Cellucid say my repository's schema is not the canonical one?”

One of `annotations/schema.json`, `annotations/config.schema.json` or
`annotations/moderation/merges.schema.json` differs from the file published in
this repository (an older version, an edit, or changed line endings). Copy the
named file again, unchanged, from
[theislab/cellucid-annotation](https://github.com/theislab/cellucid-annotation),
together with `scripts/validate_user_files.py`, and commit it.

## Citation

<!-- BEGIN cellucid-citation (generated by cellucid-private/scripts/sync_citation.py from CITATION.cff; do not edit) source-sha256=2486463f2b7c8cc656ae41e2df0261c1eb79780c4d635be147215f409b89aa2a body-sha256=5186fc40b9eddfb904fab52bee5362bf27a8d6c3713f9b67b1defa1c68c54d3f -->
> **Placeholder citation.** The Cellucid preprint is in preparation for bioRxiv and has no DOI yet; the reference below is a placeholder and will be replaced when the preprint is published.

If you use Cellucid, please cite:

Inecik, K. PLACEHOLDER: Cellucid preprint, title to be announced (forthcoming on bioRxiv). *bioRxiv* (in preparation).

BibTeX and other formats: [Citing Cellucid](https://docs.cellucid.com/en/latest/citing.html).
<!-- END cellucid-citation -->

## Documentation and ecosystem

- [Community annotation guide](https://docs.cellucid.com/en/latest/user_guide/web_app/j_community_annotation/index.html)
- [Live Cellucid application](https://www.cellucid.com)
- [Web viewer source](https://github.com/theislab/cellucid)
- [Python package](https://github.com/theislab/cellucid-python)
- [R package](https://github.com/theislab/cellucid-r)
- [Official public demo datasets](https://github.com/theislab/cellucid-datasets)
- [Custom dataset repository examples](https://github.com/theislab/cellucid-demo-custom-datasets)
