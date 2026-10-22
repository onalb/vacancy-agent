"""Saved fits. One JSON blob per building."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def slug(property_name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", property_name.lower()).strip("-")
    return cleaned or "building"


class FitStore:
    def save(self, record: dict) -> dict:
        raise NotImplementedError

    def load(self, property_name: str) -> dict | None:
        raise NotImplementedError

    def names(self) -> list[dict]:
        raise NotImplementedError


class DirectoryFitStore(FitStore):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, record: dict) -> dict:
        path = self.root / f"{slug(record['property'])}.json"
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return {"property": record["property"], "as_of": record["as_of"], "saved": True}

    def load(self, property_name: str) -> dict | None:
        path = self.root / f"{slug(property_name)}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def names(self) -> list[dict]:
        found = []
        for path in sorted(self.root.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            found.append({"property": record["property"], "as_of": record["as_of"]})
        return found


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
        name = f"{slug(record['property'])}.json"
        self.container.upload_blob(name, json.dumps(record), overwrite=True)
        return {"property": record["property"], "as_of": record["as_of"], "saved": True}

    def load(self, property_name: str) -> dict | None:
        name = f"{slug(property_name)}.json"
        blob = self.container.get_blob_client(name)
        if not blob.exists():
            return None
        return json.loads(blob.download_blob().readall())

    def names(self) -> list[dict]:
        found = []
        for blob in self.container.list_blobs():
            if not blob.name.endswith(".json"):
                continue
            record = json.loads(self.container.download_blob(blob.name).readall())
            found.append({"property": record["property"], "as_of": record["as_of"]})
        return found


def open_store() -> FitStore:
    account = os.environ.get("AZURE_STORAGE_ACCOUNT", "").strip()
    if account:
        container = os.environ.get("AZURE_STORAGE_CONTAINER", "fits").strip() or "fits"
        return BlobFitStore(account, container)
    root = os.environ.get("VACANCY_FIT_DIR", "data/fits")
    return DirectoryFitStore(root)
