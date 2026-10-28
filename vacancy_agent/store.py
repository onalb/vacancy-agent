"""Saved fits. One JSON blob per building."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def slug(property_name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", property_name.lower()).strip("-")
    return cleaned or "building"


def without_group_probability(record: dict) -> dict:
    """Drop a stored groups[].probability. Counts and coefficients stay.

    Older fit files still have that field. Load returns the record without it
    and does not rewrite the file. Save writes the record without it.
    """
    groups = record.get("groups")
    if not isinstance(groups, list):
        return record
    if not any(isinstance(group, dict) and "probability" in group for group in groups):
        return record
    updated = dict(record)
    updated["groups"] = [
        {key: value for key, value in group.items() if key != "probability"}
        if isinstance(group, dict)
        else group
        for group in groups
    ]
    return updated


def _read_json_text(raw: str) -> dict | None:
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def display_name(record: dict | None, stem: str) -> str:
    """Saved property string, or the file slug when that field is missing."""
    if isinstance(record, dict):
        saved = str(record.get("property") or "").strip()
        if saved:
            return saved
    return (stem or "").strip()


def _name_matches(record: dict, property_name: str, filename_stem: str = "") -> bool:
    needle = (property_name or "").strip()
    if not needle:
        return False
    saved = str(record.get("property") or "").strip()
    wanted = needle.casefold()
    if saved and (saved.casefold() == wanted or slug(saved) == slug(needle)):
        return True
    return bool(filename_stem) and filename_stem.casefold() == wanted


class FitStore:
    def save(self, record: dict) -> dict:
        raise NotImplementedError

    def load(self, property_name: str) -> dict | None:
        raise NotImplementedError

    def names(self) -> list[dict]:
        raise NotImplementedError

    def property_names(self) -> list[str]:
        """Property field when present, otherwise the file slug."""
        raise NotImplementedError

    def delete(self, property_name: str) -> dict:
        """Delete one `{slug}.json`. Missing file is not_found, not an exception."""
        raise NotImplementedError

    def delete_all(self) -> dict:
        """Delete every fit JSON. Returns how many were removed."""
        raise NotImplementedError


class DirectoryFitStore(FitStore):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, record: dict) -> dict:
        record = without_group_probability(record)
        path = self.root / f"{slug(record['property'])}.json"
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return {"property": record["property"], "as_of": record["as_of"], "saved": True}

    def load(self, property_name: str) -> dict | None:
        path = self.root / f"{slug(property_name)}.json"
        if not path.is_file():
            return None
        return without_group_probability(json.loads(path.read_text(encoding="utf-8")))

    def names(self) -> list[dict]:
        found = []
        for path in sorted(self.root.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            found.append({"property": record["property"], "as_of": record["as_of"]})
        return found

    def property_names(self) -> list[str]:
        found: list[str] = []
        for path in sorted(self.root.glob("*.json")):
            if not path.is_file():
                continue
            record = _read_json_text(path.read_text(encoding="utf-8"))
            label = display_name(record, path.stem)
            if label:
                found.append(label)
        return sorted(found, key=str.casefold)

    def locate(self, property_name: str) -> tuple[Path, dict] | None:
        needle = (property_name or "").strip()
        if not needle:
            return None
        direct = self.root / f"{slug(needle)}.json"
        if direct.is_file():
            record = _read_json_text(direct.read_text(encoding="utf-8"))
            if record is not None:
                return direct, record
        for path in sorted(self.root.glob("*.json")):
            record = _read_json_text(path.read_text(encoding="utf-8"))
            if record is not None and _name_matches(record, needle, path.stem):
                return path, record
        return None

    def delete(self, property_name: str) -> dict:
        found = self.locate(property_name)
        if found is None:
            return {
                "deleted": False,
                "error": "not_found",
                "property": (property_name or "").strip(),
            }
        path, record = found
        saved = str(record.get("property") or property_name).strip()
        path.unlink(missing_ok=True)
        return {"deleted": True, "property": saved}

    def delete_all(self) -> dict:
        count = 0
        for path in list(self.root.glob("*.json")):
            if not path.is_file():
                continue
            path.unlink(missing_ok=True)
            count += 1
        return {"deleted": True, "count": count}


class BlobFitStore(FitStore):
    def __init__(self, account: str, container: str) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        service = BlobServiceClient(
            account_url=f"https://{account}.blob.core.windows.net",
            credential=DefaultAzureCredential(),
        )
        self.container = service.get_container_client(container)

    def save(self, record: dict) -> dict:
        record = without_group_probability(record)
        name = f"{slug(record['property'])}.json"
        self.container.upload_blob(name, json.dumps(record), overwrite=True)
        return {"property": record["property"], "as_of": record["as_of"], "saved": True}

    def load(self, property_name: str) -> dict | None:
        name = f"{slug(property_name)}.json"
        blob = self.container.get_blob_client(name)
        if not blob.exists():
            return None
        return without_group_probability(json.loads(blob.download_blob().readall()))

    def names(self) -> list[dict]:
        found = []
        for blob in self.container.list_blobs():
            if not blob.name.endswith(".json"):
                continue
            record = json.loads(self.container.download_blob(blob.name).readall())
            found.append({"property": record["property"], "as_of": record["as_of"]})
        return found

    def property_names(self) -> list[str]:
        found: list[str] = []
        for blob in self.container.list_blobs():
            name = str(getattr(blob, "name", "") or "")
            if not name.endswith(".json"):
                continue
            stem = name[: -len(".json")].rsplit("/", 1)[-1]
            label = display_name(self._record(name), stem)
            if label:
                found.append(label)
        return sorted(found, key=str.casefold)

    def _record(self, name: str) -> dict | None:
        blob = self.container.get_blob_client(name)
        if not blob.exists():
            return None
        payload = blob.download_blob().readall()
        if isinstance(payload, bytes):
            try:
                text = payload.decode("utf-8")
            except UnicodeError:
                return None
        else:
            text = str(payload)
        return _read_json_text(text)

    def locate(self, property_name: str) -> tuple[str, dict] | None:
        needle = (property_name or "").strip()
        if not needle:
            return None
        direct = f"{slug(needle)}.json"
        record = self._record(direct)
        if record is not None:
            return direct, record
        for blob in self.container.list_blobs():
            name = str(getattr(blob, "name", "") or "")
            if not name.endswith(".json"):
                continue
            record = self._record(name)
            if record is not None and _name_matches(record, needle, name[: -len(".json")]):
                return name, record
        return None

    def delete(self, property_name: str) -> dict:
        found = self.locate(property_name)
        if found is None:
            return {
                "deleted": False,
                "error": "not_found",
                "property": (property_name or "").strip(),
            }
        name, record = found
        blob = self.container.get_blob_client(name)
        if not blob.exists():
            return {
                "deleted": False,
                "error": "not_found",
                "property": (property_name or "").strip(),
            }
        blob.delete_blob()
        saved = str(record.get("property") or property_name).strip()
        return {"deleted": True, "property": saved}

    def delete_all(self) -> dict:
        names = [
            str(getattr(blob, "name", "") or "")
            for blob in self.container.list_blobs()
            if str(getattr(blob, "name", "") or "").endswith(".json")
        ]
        count = 0
        for name in names:
            blob = self.container.get_blob_client(name)
            if not blob.exists():
                continue
            blob.delete_blob()
            count += 1
        return {"deleted": True, "count": count}


def _storage_token_ok() -> bool:
    from azure.identity import DefaultAzureCredential

    try:
        DefaultAzureCredential(exclude_interactive_browser_credential=True).get_token(
            "https://storage.azure.com/.default"
        )
        return True
    except Exception:
        return False


def open_store() -> FitStore:
    account = os.environ.get("AZURE_STORAGE_ACCOUNT", "").strip()
    root = os.environ.get("VACANCY_FIT_DIR", "data/fits")
    disk = DirectoryFitStore(root)
    if not account:
        return disk
    if not _storage_token_ok():
        return disk
    container = os.environ.get("AZURE_STORAGE_CONTAINER", "fits").strip() or "fits"
    return BlobFitStore(account, container)
