# Cellucid Community Annotations (Template)

This folder is a starter template for a **GitHub annotation repository** that works with Cellucid's community annotation UI.

The core idea: each annotator writes their own file (no shared edits / no merge conflicts), and Cellucid compiles the merged consensus view **in the browser** on Pull.

## Layout

- `annotations/schema.json` - JSON schema reference for user vote files
- `annotations/config.json` - Dataset binding + author-controlled annotatable fields + per-field consensus settings
- `annotations/users/*.json` - Per-user suggestions & votes (conflict-free collaboration)
- `annotations/moderation/merges.json` - Optional author-only merges (maintainers/admins)
- `scripts/validate_user_files.py` - Validation script (run by CI and usable locally)
- `.github/workflows/validate.yml` - GitHub Actions workflow (validation)

## How collaboration works

This template is designed for many annotators to collaborate safely:

- Each person contributes only `annotations/users/ghid_<id>.json`.
- Authors (maintain/admin) can optionally curate `annotations/moderation/merges.json`.
- In Cellucid, **Pull** downloads the raw files under `annotations/users/` and `annotations/moderation/` (SHA-based: downloads only what changed) and compiles a merged view locally.
  - The browser cache is scoped by **datasetId + repo + branch + GitHub user.id** (multi-user + multi-project safe).
- Cellucid can export a locally-built `consensus.json` snapshot from the sidebar (useful for downstream tooling); it is not committed back to the repo.

## Usage (quick start)

1. Create a new GitHub repo from this template folder contents.
2. Configure `annotations/config.json` to match your dataset id(s) and annotatable field(s).
   - `supportedDatasets[]` may include multiple dataset ids.
   - Authors can also update `fieldsToAnnotate`, `annotatableSettings` (`minAnnotators`, `threshold`), and `closedFields` via the Cellucid UI (Publish writes back to `annotations/config.json`).
3. Each collaborator writes only their own file under `annotations/users/`.
4. In Cellucid, connect via **GitHub App sign-in** (no token paste). Users with write access publish directly; others publish via fork + Pull Request.

## CI / GitHub Actions

This template includes one workflow:

### 1) Validate inputs (`validate.yml`)

File: `.github/workflows/validate.yml`

- Runs on pushes and pull requests that touch `annotations/**` or `scripts/**`.
- Validates human/client-authored inputs:
  - `annotations/config.json`
  - `annotations/users/*.json`
  - `annotations/moderation/merges.json` (optional)
- Executes: `python scripts/validate_user_files.py`

If this fails, fix the JSON files in `annotations/` (do not edit any derived/exported outputs).

## Local development / debugging

You can run the same checks locally (Python 3.10+ recommended; CI uses Python 3.11):

```bash
# Validate inputs (what humans/clients write)
python scripts/validate_user_files.py
```

## Author-only merges (optional)

If you maintain the repo and want to "merge" suggestions (e.g. two different labels that should be treated as the same), you can add `annotations/moderation/merges.json`.

- This file is optional and typically restricted to maintainers/admins.
- Merges create a mapping from `fromSuggestionId` → `intoSuggestionId` within the same bucket.
- Bucket key format: `<fieldKey>:<categoryLabel>`. If `fieldKey` contains `:`, Cellucid encodes it as `fk~<urlencoded>` (example: `fk~celltype%3Acoarse:...`).
- Cellucid applies this mapping at runtime when computing bundle vote totals and consensus.
- In the Cellucid UI, authors can add merges by dragging a suggestion card onto another.
  - The merge dialog includes an optional note.
  - You can later edit or delete the merge note from the bundle’s **View merged** modal (the merge mapping stays the same).
  - When a merge note is edited, the merge record may include `editedAt` (timestamp of the note edit) in addition to `at` (timestamp of the merge creation).

## Profile fields

User files include identity metadata that Cellucid stores in each `annotations/users/*.json`:

- `githubUserId` (stable GitHub numeric id; file identity is `ghid_<id>`)
- `login` (GitHub username; informational only)
- `displayName`, `title`, `orcid`, `linkedin`, `email` (optional; LinkedIn is handle-only)
- `datasets` (optional): informational record of dataset ids and annotatable fields the user has accessed

## Timestamps

- Suggestions may include `editedAt` when the proposer edits a suggestion (e.g. label/evidence/ontology id/markers).
- Comments include `editedAt` when a comment is edited.

## FAQ / troubleshooting

### “Why is there no `annotations/consensus/merged.json`?”

This template does not commit a merged consensus artifact. Instead:

- Cellucid pulls the raw per-user files (`annotations/users/*.json`) and optional merges file (`annotations/moderation/merges.json`)
- Cellucid compiles the merged view locally in the browser on Pull
- You can download a compiled `consensus.json` snapshot from the sidebar when needed

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
