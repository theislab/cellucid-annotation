#!/usr/bin/env python3
"""
Validate annotation repository inputs for the Cellucid community annotation UI.

This script is meant to be run in CI (see `.github/workflows/validate.yml`) and
locally. It validates only the *inputs* written by humans/clients:

- `annotations/config.json`
- `annotations/users/*.json`
- `annotations/moderation/merges.json` (optional, author-only)

It intentionally validates only the *inputs* under `annotations/` that humans/clients
write directly. Derived consensus outputs are compiled inside the Cellucid UI and
are not committed to this repo in this template.

The validations below are practical (not academically exhaustive): they aim to
catch malformed JSON, missing required fields, and common user mistakes early.
"""

import glob
import json
import pathlib
import sys
from typing import Any, Dict, List, Tuple


ROOT = pathlib.Path(__file__).resolve().parents[1]
USERS_DIR = ROOT / "annotations" / "users"
CONFIG_FILE = ROOT / "annotations" / "config.json"
MERGES_FILE = ROOT / "annotations" / "moderation" / "merges.json"

MAX_LABEL_LEN = 120
MAX_ONTOLOGY_LEN = 64
MAX_EVIDENCE_LEN = 2000
MAX_USERNAME_LEN = 64
MAX_COMMENT_LEN = 500
MAX_MARKER_GENE_LEN = 64


def read_json(path: pathlib.Path) -> Any:
  """Read and parse UTF-8 JSON."""
  with path.open("r", encoding="utf-8") as f:
    return json.load(f)


def ensure_str(v: Any) -> str:
  """Coerce to string and trim whitespace (treat `None` as empty)."""
  if v is None:
    return ""
  return str(v).strip()


def fail(errors: List[str]) -> int:
  """Print errors to stderr and return a non-zero exit code."""
  for e in errors:
    print(e, file=sys.stderr)
  return 1


def validate_config(doc: Any, path: pathlib.Path) -> List[str]:
  """Validate `annotations/config.json`."""
  errs: List[str] = []
  if not isinstance(doc, dict):
    return [f"{path}: config must be an object"]
  if doc.get("version") != 1:
    errs.append(f"{path}: version must be 1")
  sds = doc.get("supportedDatasets")
  if not isinstance(sds, list) or not sds:
    errs.append(f"{path}: supportedDatasets must be a non-empty array")
    return errs
  seen_ids = set()
  for i, entry in enumerate(sds):
    if not isinstance(entry, dict):
      errs.append(f"{path}: supportedDatasets[{i}] must be an object")
      continue
    did = ensure_str(entry.get("datasetId"))
    if not did:
      errs.append(f"{path}: supportedDatasets[{i}].datasetId is required")
    elif did in seen_ids:
      errs.append(f"{path}: supportedDatasets[{i}].datasetId is duplicated ('{did}')")
    else:
      seen_ids.add(did)
    fta = entry.get("fieldsToAnnotate")
    fields: List[str] = []
    if fta is not None:
      if not isinstance(fta, list):
        errs.append(f"{path}: supportedDatasets[{i}].fieldsToAnnotate must be an array if present")
      else:
        for j, raw in enumerate(fta[:500]):
          fk = ensure_str(raw)
          if not fk:
            errs.append(f"{path}: supportedDatasets[{i}].fieldsToAnnotate[{j}] must be a non-empty string")
            continue
          fields.append(fk)
    field_set = set(fields)

    closed = entry.get("closedFields")
    if closed is not None:
      if not isinstance(closed, list):
        errs.append(f"{path}: supportedDatasets[{i}].closedFields must be an array if present")
      else:
        for j, raw in enumerate(closed[:500]):
          fk = ensure_str(raw)
          if not fk:
            errs.append(f"{path}: supportedDatasets[{i}].closedFields[{j}] must be a non-empty string")
            continue
          if fields and fk not in field_set:
            errs.append(f"{path}: supportedDatasets[{i}].closedFields[{j}] must be in fieldsToAnnotate")

    settings = entry.get("annotatableSettings")
    if settings is not None:
      if not isinstance(settings, dict):
        errs.append(f"{path}: supportedDatasets[{i}].annotatableSettings must be an object if present")
      else:
        for field_key, raw in list(settings.items())[:1000]:
          fk = ensure_str(field_key)
          if not fk:
            errs.append(f"{path}: supportedDatasets[{i}].annotatableSettings key must be non-empty string")
            continue
          if fields and fk not in field_set:
            errs.append(f"{path}: supportedDatasets[{i}].annotatableSettings['{fk}'] must be in fieldsToAnnotate")
          if not isinstance(raw, dict):
            errs.append(f"{path}: supportedDatasets[{i}].annotatableSettings['{fk}'] must be an object")
            continue
          ma = raw.get("minAnnotators")
          th = raw.get("threshold")
          if ma is not None:
            if not isinstance(ma, int):
              errs.append(f"{path}: supportedDatasets[{i}].annotatableSettings['{fk}'].minAnnotators must be an integer")
            elif ma < 0 or ma > 50:
              errs.append(f"{path}: supportedDatasets[{i}].annotatableSettings['{fk}'].minAnnotators must be 0-50")
          if th is not None:
            if not isinstance(th, (int, float)):
              errs.append(f"{path}: supportedDatasets[{i}].annotatableSettings['{fk}'].threshold must be a number")
            elif th < -1 or th > 1:
              errs.append(f"{path}: supportedDatasets[{i}].annotatableSettings['{fk}'].threshold must be -1..1")
  return errs


def validate_suggestion(s: Any, path: pathlib.Path, bucket: str, idx: int) -> List[str]:
  """Validate one suggestion object within a bucket list."""
  errs: List[str] = []
  if not isinstance(s, dict):
    return [f"{path}: suggestions[{bucket}][{idx}] must be an object"]
  for req in ("id", "label", "proposedBy", "proposedAt"):
    if not ensure_str(s.get(req)):
      errs.append(f"{path}: suggestions[{bucket}][{idx}].{req} is required")
  label = ensure_str(s.get("label"))
  if label and len(label) > MAX_LABEL_LEN:
    errs.append(f"{path}: suggestions[{bucket}][{idx}].label must be <= {MAX_LABEL_LEN} chars")
  proposed_by = ensure_str(s.get("proposedBy"))
  if proposed_by and len(proposed_by) > MAX_USERNAME_LEN:
    errs.append(f"{path}: suggestions[{bucket}][{idx}].proposedBy must be <= {MAX_USERNAME_LEN} chars")
  if "ontologyId" in s and s["ontologyId"] is not None and not isinstance(s["ontologyId"], str):
    errs.append(f"{path}: suggestions[{bucket}][{idx}].ontologyId must be string|null")
  if isinstance(s.get("ontologyId"), str) and len(ensure_str(s.get("ontologyId"))) > MAX_ONTOLOGY_LEN:
    errs.append(f"{path}: suggestions[{bucket}][{idx}].ontologyId must be <= {MAX_ONTOLOGY_LEN} chars")
  if "evidence" in s and s["evidence"] is not None and not isinstance(s["evidence"], str):
    errs.append(f"{path}: suggestions[{bucket}][{idx}].evidence must be string|null")
  if isinstance(s.get("evidence"), str) and len(ensure_str(s.get("evidence"))) > MAX_EVIDENCE_LEN:
    errs.append(f"{path}: suggestions[{bucket}][{idx}].evidence must be <= {MAX_EVIDENCE_LEN} chars")
  if "editedAt" in s and s["editedAt"] is not None and not isinstance(s["editedAt"], str):
    errs.append(f"{path}: suggestions[{bucket}][{idx}].editedAt must be string|null")
  if "markers" in s and s["markers"] is not None:
    if not isinstance(s["markers"], list):
      errs.append(f"{path}: suggestions[{bucket}][{idx}].markers must be array|null")
    else:
      for j, m in enumerate(s["markers"][:200]):
        if isinstance(m, str):
          if len(ensure_str(m)) > MAX_MARKER_GENE_LEN:
            errs.append(f"{path}: suggestions[{bucket}][{idx}].markers[{j}] must be <= {MAX_MARKER_GENE_LEN} chars")
          continue
        if isinstance(m, dict):
          gene = ensure_str(m.get("gene"))
          if not gene:
            errs.append(f"{path}: suggestions[{bucket}][{idx}].markers[{j}].gene is required")
          elif len(gene) > MAX_MARKER_GENE_LEN:
            errs.append(f"{path}: suggestions[{bucket}][{idx}].markers[{j}].gene must be <= {MAX_MARKER_GENE_LEN} chars")
          continue
        errs.append(f"{path}: suggestions[{bucket}][{idx}].markers[{j}] must be string or object")
  return errs


def validate_comment(c: Any, path: pathlib.Path, sid: str, idx: int) -> List[str]:
  """Validate one comment object for a specific suggestion id."""
  errs: List[str] = []
  if not isinstance(c, dict):
    return [f"{path}: comments[{sid}][{idx}] must be an object"]
  for req in ("id", "text", "authorUsername", "createdAt"):
    if not ensure_str(c.get(req)):
      errs.append(f"{path}: comments[{sid}][{idx}].{req} is required")
  text = ensure_str(c.get("text"))
  if text and len(text) > MAX_COMMENT_LEN:
    errs.append(f"{path}: comments[{sid}][{idx}].text must be <= {MAX_COMMENT_LEN} chars")
  author = ensure_str(c.get("authorUsername"))
  if author and len(author) > MAX_USERNAME_LEN:
    errs.append(f"{path}: comments[{sid}][{idx}].authorUsername must be <= {MAX_USERNAME_LEN} chars")
  if "editedAt" in c and c["editedAt"] is not None and not isinstance(c["editedAt"], str):
    errs.append(f"{path}: comments[{sid}][{idx}].editedAt must be string|null")
  return errs


def validate_user_file(doc: Any, path: pathlib.Path) -> List[str]:
  """Validate one `annotations/users/*.json` file."""
  errs: List[str] = []
  if not isinstance(doc, dict):
    return [f"{path}: user file must be an object"]
  if doc.get("version") != 1:
    errs.append(f"{path}: version must be 1")
  username = ensure_str(doc.get("username"))
  if not username:
    errs.append(f"{path}: username is required")
  if not ensure_str(doc.get("updatedAt")):
    errs.append(f"{path}: updatedAt is required")

  gid = doc.get("githubUserId")
  if not isinstance(gid, int) or gid <= 0:
    errs.append(f"{path}: githubUserId is required and must be a positive integer")
  else:
    # We intentionally require `username` to match the file identity `ghid_<id>`.
    # This prevents accidental overwrites and simplifies deterministic aggregation.
    expected = f"ghid_{gid}"
    if username and username != expected:
      errs.append(f"{path}: username must match githubUserId (expected '{expected}')")

  if "login" in doc and doc["login"] is not None and not isinstance(doc["login"], str):
    errs.append(f"{path}: login must be string|null")

  if "email" in doc:
    if doc["email"] is None:
      errs.append(f"{path}: email must be a valid email address if present")
    elif not isinstance(doc["email"], str):
      errs.append(f"{path}: email must be a valid email address if present")
    else:
      email = ensure_str(doc["email"])
      if email:
        if " " in email or "@" not in email or "." not in email.split("@", 1)[-1]:
          errs.append(f"{path}: email must be a valid email address if present")

  if "linkedin" in doc and doc["linkedin"] is not None:
    if not isinstance(doc["linkedin"], str):
      errs.append(f"{path}: linkedin must be string|null")
    else:
      li = ensure_str(doc["linkedin"])
      if li and not all(c.islower() or c.isdigit() or c == "-" for c in li):
        errs.append(f"{path}: linkedin must be a lowercase handle (a-z0-9-) if present")
      if li and (len(li) < 3 or len(li) > 120):
        errs.append(f"{path}: linkedin must be 3-120 chars if present")
  if "orcid" in doc and doc["orcid"] is not None and not isinstance(doc["orcid"], str):
    errs.append(f"{path}: orcid must be string|null")

  suggestions = doc.get("suggestions")
  if not isinstance(suggestions, dict):
    errs.append(f"{path}: suggestions must be an object")
    suggestions = {}

  # Hard caps prevent pathological files from making CI slow/expensive. The UI is
  # expected to stay well below these limits.
  for bucket, lst in list(suggestions.items())[:5000]:
    b = ensure_str(bucket)
    if not b:
      errs.append(f"{path}: suggestions bucket key must be non-empty string")
      continue
    if not isinstance(lst, list):
      errs.append(f"{path}: suggestions[{b}] must be an array")
      continue
    for i, s in enumerate(lst[:500]):
      errs.extend(validate_suggestion(s, path, b, i))

  votes = doc.get("votes")
  if not isinstance(votes, dict):
    errs.append(f"{path}: votes must be an object")
    votes = {}
  # Votes keys are suggestion IDs; values must be "up" or "down".
  for sid, direction in list(votes.items())[:50000]:
    if not ensure_str(sid):
      errs.append(f"{path}: votes key must be non-empty string")
    if direction not in ("up", "down"):
      errs.append(f"{path}: votes[{sid}] must be 'up' or 'down'")

  comments = doc.get("comments")
  if comments is not None:
    if not isinstance(comments, dict):
      errs.append(f"{path}: comments must be an object if present")
    else:
      for sid, lst in list(comments.items())[:10000]:
        if not ensure_str(sid):
          errs.append(f"{path}: comments key must be non-empty string")
          continue
        if not isinstance(lst, list):
          errs.append(f"{path}: comments[{sid}] must be an array")
          continue
        for i, c in enumerate(lst[:100]):
          errs.extend(validate_comment(c, path, sid, i))

  deleted = doc.get("deletedSuggestions")
  if deleted is not None:
    if not isinstance(deleted, dict):
      errs.append(f"{path}: deletedSuggestions must be an object if present")
    else:
      for bucket, ids in list(deleted.items())[:10000]:
        b = ensure_str(bucket)
        if not b:
          errs.append(f"{path}: deletedSuggestions bucket key must be non-empty string")
          continue
        if not isinstance(ids, list):
          errs.append(f"{path}: deletedSuggestions[{b}] must be an array")
          continue
        for j, sid in enumerate(ids[:5000]):
          if not ensure_str(sid):
            errs.append(f"{path}: deletedSuggestions[{b}][{j}] must be a non-empty string")

  datasets = doc.get("datasets")
  if datasets is not None:
    if not isinstance(datasets, dict):
      errs.append(f"{path}: datasets must be an object if present")
    else:
      for did, meta in list(datasets.items())[:1000]:
        d = ensure_str(did)
        if not d:
          errs.append(f"{path}: datasets key must be a non-empty string")
          continue
        if not isinstance(meta, dict):
          errs.append(f"{path}: datasets[{d}] must be an object")
          continue
        if not ensure_str(meta.get("lastAccessedAt")):
          errs.append(f"{path}: datasets[{d}].lastAccessedAt is required")
        fta = meta.get("fieldsToAnnotate")
        if fta is None:
          errs.append(f"{path}: datasets[{d}].fieldsToAnnotate is required")
        elif not isinstance(fta, list):
          errs.append(f"{path}: datasets[{d}].fieldsToAnnotate must be an array")

  return errs


def validate_merges(doc: Any, path: pathlib.Path) -> List[str]:
  """Validate optional author-only merges (`annotations/moderation/merges.json`)."""
  errs: List[str] = []
  if not isinstance(doc, dict):
    return [f"{path}: merges file must be an object"]
  if doc.get("version") != 1:
    errs.append(f"{path}: version must be 1")
  merges = doc.get("merges")
  if merges is None:
    return errs
  if not isinstance(merges, list):
    errs.append(f"{path}: merges must be an array")
    return errs
  for i, m in enumerate(merges[:10000]):
    if not isinstance(m, dict):
      errs.append(f"{path}: merges[{i}] must be an object")
      continue
    for req in ("bucket", "fromSuggestionId", "intoSuggestionId", "by", "at"):
      if not ensure_str(m.get(req)):
        errs.append(f"{path}: merges[{i}].{req} is required")
    if "editedAt" in m and m["editedAt"] is not None and not isinstance(m["editedAt"], str):
      errs.append(f"{path}: merges[{i}].editedAt must be string|null")
    if ensure_str(m.get("fromSuggestionId")) == ensure_str(m.get("intoSuggestionId")):
      errs.append(f"{path}: merges[{i}] fromSuggestionId cannot equal intoSuggestionId")
  return errs


def main() -> int:
  """CLI entry point (used by CI)."""
  errors: List[str] = []

  # Config validation
  try:
    cfg = read_json(CONFIG_FILE)
    errors.extend(validate_config(cfg, CONFIG_FILE))
  except FileNotFoundError:
    errors.append(f"{CONFIG_FILE}: missing (required)")
  except Exception as e:
    errors.append(f"{CONFIG_FILE}: failed to parse ({e})")

  # User file validation
  for p in sorted([pathlib.Path(x) for x in glob.glob(str(USERS_DIR / "*.json"))]):
    try:
      doc = read_json(p)
    except Exception as e:
      errors.append(f"{p}: failed to parse ({e})")
      continue
    errors.extend(validate_user_file(doc, p))

  # Optional merges validation (author-only)
  try:
    merges_doc = read_json(MERGES_FILE)
    errors.extend(validate_merges(merges_doc, MERGES_FILE))
  except FileNotFoundError:
    pass
  except Exception as e:
    errors.append(f"{MERGES_FILE}: failed to parse ({e})")

  if errors:
    return fail(errors)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
