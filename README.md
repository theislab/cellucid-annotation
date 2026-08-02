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

This repository stores annotation records only. Keep embeddings, expression
matrices, and prepared Cellucid payloads in a separate dataset source. See the
[complete community annotation guide](https://cellucid.readthedocs.io/en/latest/user_guide/web_app/j_community_annotation/index.html)
for the author walkthrough, annotator walkthrough, UI reference, screenshots,
and troubleshooting.

## Contract and layout

- `annotations/schema.json` - exact JSON schema for user vote files
- `annotations/config.schema.json` - exact JSON schema for repository configuration
- `annotations/config.json` - Dataset binding + author-controlled annotatable fields + per-field consensus settings
- `annotations/users/*.json` - Per-user suggestions & votes (conflict-free collaboration)
- `annotations/moderation/merges.schema.json` - exact JSON schema for moderation merges
- `annotations/moderation/merges.json` - Optional author-only merges (maintainers/admins)
- `scripts/validate_user_files.py` - Validation script (run by CI and usable locally)
- `.github/workflows/validate.yml` - GitHub Actions workflow (validation)

Only files declared by this layout belong in the annotation contract. A
compiled consensus file is deliberately not committed: it is a view derived
from the validated user files, configuration, and moderation merges.

Beside the contract, this repository's root also carries the governance files
the Cellucid repositories carry — `LICENSE`, `CONTRIBUTING.md`,
`SECURITY.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md`, `CITATION.cff` — plus
`.gitignore` and `.gitattributes`. They govern this repository; they are not
part of the layout, and an annotation repository built from it does not need
them. Copy the contract files listed above and give your own repository its own
licence and policies.

The three schemas declare fixed current identities:

- `https://cellucid.com/contracts/community-annotation/user-v1.schema.json`
- `https://cellucid.com/contracts/community-annotation/config-v1.schema.json`
- `https://cellucid.com/contracts/community-annotation/merges-v1.schema.json`

These `$id` values are **identifiers, not links**. They are compared as exact
strings by `scripts/validate_user_files.py` and by the viewer
(`cellucid/assets/js/app/community-annotations/wire-contract.js`); nothing
fetches them, and they are not required to resolve. They deliberately use the
bare apex `cellucid.com`, while every URL meant to be opened in a browser — the
[live application](https://www.cellucid.com) included — uses the canonical
`www.cellucid.com` host. Do not "normalise" one form into the other: changing a
published `$id` breaks every repository already validated against it. A genuine
contract change gets a new `-v2` identity instead.

## How collaboration works

This template is designed for many annotators to collaborate safely:

- Each person contributes only `annotations/users/ghid_<id>.json`.
- Authors with `maintain` or `admin` repository permission can optionally
  curate `annotations/moderation/merges.json`.
- In Cellucid, **Pull** downloads the raw files under `annotations/users/` and
  `annotations/moderation/` (SHA-based: downloads only what changed) and
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
one category within that field. That combination is a **bucket**. Users propose
labels inside a bucket and cast `up` or `down` votes on those suggestions.

For each bucket, Cellucid counts unique users who cast any vote, computes the
leading suggestion's net votes (`up - down`), and reports
`confidence = net votes / unique voters`.

- **Pending**: fewer unique voters than the field's `minAnnotators`
- **Consensus**: the leader is not tied and its confidence meets or exceeds the
  field's `threshold`
- **Disputed**: every other result, including a tie

The exact settings are owned per field in `annotations/config.json`.
`minAnnotators` is an integer from 0 through 50, and `threshold` is a number
from -1 through 1. Choose these values before recruiting annotators and record
them when exporting a result; changing them can change the derived status
without changing anyone's votes.

## Set up an annotation round

1. Create a new GitHub repository and copy the contract files listed above —
   `annotations/`, `scripts/`, and `.github/workflows/validate.yml` — into its
   root. Leave this repository's own licence and policy files behind and give
   yours its own.
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
   - Contract strings are exact, nonblank, bounded, and cannot have leading or
     trailing whitespace.
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
   other route.
6. Pull once before annotating. Each collaborator then works through Cellucid;
   the app publishes only that collaborator's `ghid_<id>.json`.

The loaded dataset's exact id must occur in `supportedDatasets`. A mismatch is
blocked rather than attached to a similarly named dataset. Authors may add the
current dataset through the UI and Publish the resulting configuration;
annotators cannot bypass the binding.

## CI / GitHub Actions

This template includes one workflow:

### 1) Validate inputs (`validate.yml`)

File: `.github/workflows/validate.yml`

- Runs on pushes and pull requests that touch any checked contract, workflow,
  validator, or test surface, or any file at the repository root — the README
  and the governance files beside it are swept by the suite, so changing one
  has to run it.
- Validates human/client-authored inputs:
  - `annotations/config.json`
  - `annotations/users/*.json`
  - `annotations/moderation/merges.json` (optional)
- Executes both checks, in order:
  - `python -m unittest discover -s tests -v`
  - `python scripts/validate_user_files.py`

If this fails, fix the JSON files in `annotations/` (do not edit any derived/exported outputs).

## Local development / debugging

You can run the same checks locally (Python 3.10+ is required; CI uses Python
3.10, 3.12, and 3.14):

```bash
# Run the contract regression suite
python -m unittest discover -s tests -v

# Validate every input (what humans/clients write)
python scripts/validate_user_files.py
```

The validator reads the checked-in schemas directly, rejects unknown fields,
wrong JSON types, duplicate JSON keys, and malformed JSON, and inspects every
array item. A user document is accepted only when its filename is exactly
`ghid_<githubUserId>.json` and its `username` is the same `ghid_<githubUserId>`
identity. Suggestion ids cannot contain `:` because Cellucid reserves that
character as the delimiter between a bucket key and a suggestion id.

Validation never coerces, truncates, migrates, skips, or repairs input. The
browser applies the same rule before caching or compiling a Pull, so one invalid
document fails the operation without producing a partial merged view.

Files must be UTF-8 JSON without a byte-order mark. User JSON files must be
direct children of `annotations/users/`; case variants and nested JSON paths are
invalid. The only non-JSON entry permitted there is the checked-in `.gitkeep`,
whose complete content is one LF byte so an empty user inventory remains
representable in Git. Suggestion ids must remain unambiguous across the
repository: one id cannot identify suggestions owned by different users or
stored in different buckets, and `:` is not permitted in an id.

Every active `annotations/config.json`, `annotations/users/ghid_<id>.json`, and
optional `annotations/moderation/merges.json` file must be at most **1,000,000
UTF-8 bytes**. The validator rejects a larger file before JSON parsing, matching
the boundary for the GitHub
[repository Contents API](https://docs.github.com/en/rest/repos/contents)
complete JSON/base64 contract. Archive historical material outside
`annotations/` and keep each active document complete; files are never
truncated.

Cellucid also rejects alternate Git blob encodings and truncated Git tree
responses. Its raw-file cache requires IndexedDB and localStorage; an
unavailable, corrupt, or failed storage boundary is reported as an error instead
of being replaced with an in-memory cache.

## Author-only merges (optional)

If you maintain the repo and want to "merge" suggestions (e.g. two different labels that should be treated as the same), you can add `annotations/moderation/merges.json`.

- This file is optional and typically restricted to maintainers/admins.
- Merges create a mapping from `fromSuggestionId` → `intoSuggestionId` within the same bucket.
- Bucket key format: `<fieldKey>:<categoryLabel>`. If `fieldKey` contains `:`, Cellucid encodes it as `fk~<urlencoded>` (example: `fk~celltype%3Acoarse:...`).
- Category labels may contain `:`; suggestion ids may not, so the complete
  bucket/id identity remains unambiguous.
- Cellucid applies this mapping at runtime when computing bundle vote totals and consensus.
- In the Cellucid UI, authors can add merges by dragging a suggestion card onto another.
  - The merge dialog includes an optional note.
  - You can later edit or delete the merge note from the bundle’s **View merged** modal (the merge mapping stays the same).
  - When a merge note is edited, the merge record may include `editedAt` (timestamp of the note edit) in addition to `at` (timestamp of the merge creation).

## Profile fields

User files include identity metadata that Cellucid stores in each `annotations/users/*.json`:

- `githubUserId` (stable GitHub numeric id; file identity is `ghid_<id>`)
- `login` (GitHub username; informational only)
- `displayName`, `title`, `orcid`, `linkedin` (optional; ORCID uses the exact
  checksum-valid `0000-0000-0000-0000` representation — the final character is
  a check digit and is an uppercase `X` when that digit is ten, as in
  `0000-0000-0000-001X` — and LinkedIn uses an exact lowercase handle without
  `@` or a URL)
- `datasets` (optional): informational record of dataset ids and annotatable fields the user has accessed

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
- Review `displayName`, `title`, `orcid`, and `linkedin` before publishing;
  these optional fields become part of the user's GitHub file.
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

After that, Pull uses GitHub `sha` values to download only the user/merge files that changed.

### “How do I force a clean re-download?”

In the Cellucid sidebar:

- Use **Remove downloaded files** to clear the raw-file cache for the current cache scope:
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

The route is selected before any write. If it fails, Cellucid reports that
failure instead of silently attempting the other route. Merge the pull request,
then ask collaborators to Pull again.

## Documentation and ecosystem

- [Community annotation guide](https://cellucid.readthedocs.io/en/latest/user_guide/web_app/j_community_annotation/index.html)
- [Live Cellucid application](https://www.cellucid.com)
- [Web viewer source](https://github.com/theislab/cellucid)
- [Python package](https://github.com/theislab/cellucid-python)
- [R package](https://github.com/theislab/cellucid-r)
- [Official public demo datasets](https://github.com/theislab/cellucid-datasets)
- [Custom dataset repository examples](https://github.com/theislab/cellucid-demo-custom-datasets)
