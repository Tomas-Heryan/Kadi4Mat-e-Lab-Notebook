"""Thin, typed client over kadi-apy's ``KadiManager`` for the Kadi4Mat HTTP API v1.

Only relative endpoints (``/records/…``) are used, so every request goes to the
configured host. Uploads implement the official protocol including the
``Kadi-MD5-Checksum`` header, and every uploaded file is verified afterwards against
the checksum the server stores.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Iterator

from .config import Config
from .errors import ApiError, ConfigError

UPLOAD_CHUNKED_BOUNDARY = 50 * 1024 * 1024
RETRYABLE_METHODS = {"get", "head"}


def _niquests():
    try:
        import niquests  # noqa: WPS433 (kadi-apy dependency)
    except ImportError:  # pragma: no cover - niquests is always installed with kadi-apy
        return None
    return niquests


class KadiClient:
    def __init__(self, config: Config, verbose: bool = False):
        if not config.token:
            raise ConfigError("A personal access token is required for this command (KADI_TOKEN).")
        try:
            from kadi_apy import KadiManager
        except ImportError as exc:
            raise ConfigError("kadi-apy is not installed: python -m pip install -r requirements.txt") from exc
        self.config = config
        self.verbose = verbose
        # verify=True is fixed; an internal CA is supplied as a bundle path, never disabled.
        self.manager = KadiManager(host=config.host, pat=config.token, verify=True,
                                   ca_bundle=config.ca_bundle, timeout=config.timeout)
        self._session_calls = 0

    # ------------------------------------------------------------------ low level
    def close(self) -> None:
        self.manager._session.close()  # noqa: SLF001 (no public close in kadi-apy)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def request(self, method: str, endpoint: str, ok: tuple[int, ...] = (200,), retries: int = 3, **kwargs):
        """Perform a request; raise :class:`ApiError` unless the status is in ``ok``."""
        attempt = 0
        niq = _niquests()
        while True:
            attempt += 1
            try:
                response = self.manager.make_request(endpoint, method=method, **kwargs)
            except Exception as exc:  # noqa: BLE001 - network layer errors
                is_net = niq is not None and isinstance(exc, niq.exceptions.RequestException)
                if is_net and method in RETRYABLE_METHODS and attempt < retries:
                    time.sleep(0.5 * attempt)
                    continue
                raise ApiError(method, endpoint, 0, f"network error: {exc}") from exc
            self._session_calls += 1
            if response.status_code in ok:
                return response
            if response.status_code in (502, 503, 504) and method in RETRYABLE_METHODS and attempt < retries:
                time.sleep(0.5 * attempt)
                continue
            try:
                body = response.json()
            except Exception:  # noqa: BLE001
                body = (response.text or "")[:500]
            raise ApiError(method, endpoint, response.status_code, body)

    def get_json(self, endpoint: str, **params) -> Any:
        return self.request("get", endpoint, params=params or None).json()

    def paginate(self, endpoint: str, per_page: int = 100, **params) -> Iterator[dict]:
        page = 1
        while True:
            data = self.request("get", endpoint, params={**params, "page": page, "per_page": per_page}).json()
            for item in data.get("items", []):
                yield item
            pagination = data.get("_pagination", {})
            if page >= int(pagination.get("total_pages", 1) or 1):
                return
            page += 1

    # ------------------------------------------------------------------ instance
    def info(self) -> dict:
        return self.get_json("/info")

    def me(self) -> dict:
        return self.get_json("/users/me")

    # ------------------------------------------------------------------ resources
    def get_by_identifier(self, kind: str, identifier: str) -> dict | None:
        response = self.request("get", f"/{kind}/identifier/{identifier}", ok=(200, 404))
        if response.status_code == 404:
            return None
        data = response.json()
        if data.get("identifier") != identifier:
            raise ApiError("get", f"/{kind}/identifier/{identifier}", 200,
                           f"server returned identifier {data.get('identifier')!r}")
        return data

    def get(self, kind: str, resource_id: int) -> dict:
        return self.get_json(f"/{kind}/{resource_id}")

    def create(self, kind: str, payload: dict) -> dict:
        return self.request("post", f"/{kind}", ok=(201,), json=payload).json()

    def patch(self, kind: str, resource_id: int, payload: dict) -> dict:
        return self.request("patch", f"/{kind}/{resource_id}", ok=(200,), json=payload).json()

    def delete(self, kind: str, resource_id: int) -> None:
        self.request("delete", f"/{kind}/{resource_id}", ok=(204, 200, 404))

    def purge(self, kind: str, resource_id: int) -> None:
        self.request("post", f"/{kind}/{resource_id}/purge", ok=(202, 204, 200, 404))

    # ------------------------------------------------------------------ relations
    def record_links(self, record_id: int, direction: str = "out") -> list[dict]:
        return list(self.paginate(f"/records/{record_id}/records", direction=direction))

    def link_records(self, from_id: int, to_id: int, name: str, term: str | None) -> dict:
        payload = {"record_to": {"id": to_id}, "name": name, "term": term}
        return self.request("post", f"/records/{from_id}/records", ok=(201,), json=payload).json()

    def update_link(self, from_id: int, link_id: int, **fields) -> dict:
        return self.request("patch", f"/records/{from_id}/records/{link_id}", ok=(200,), json=fields).json()

    def record_collections(self, record_id: int) -> list[dict]:
        return list(self.paginate(f"/records/{record_id}/collections"))

    def add_record_to_collection(self, collection_id: int, record_id: int) -> bool:
        """Returns True if added, False if it was already a member (409)."""
        response = self.request("post", f"/collections/{collection_id}/records", ok=(201, 409),
                                json={"id": record_id})
        return response.status_code == 201

    def child_collections(self, collection_id: int) -> list[dict]:
        return list(self.paginate(f"/collections/{collection_id}/collections"))

    def add_child_collection(self, parent_id: int, child_id: int) -> bool:
        response = self.request("post", f"/collections/{parent_id}/collections", ok=(201, 409),
                                json={"id": child_id})
        return response.status_code == 201

    # ------------------------------------------------------------------ roles
    def group_by_identifier(self, identifier: str) -> dict | None:
        return self.get_by_identifier("groups", identifier)

    def group_roles(self, kind: str, resource_id: int) -> list[dict]:
        return list(self.paginate(f"/{kind}/{resource_id}/roles/groups"))

    def add_group_role(self, kind: str, resource_id: int, group_id: int, role: str) -> bool:
        response = self.request("post", f"/{kind}/{resource_id}/roles/groups", ok=(201, 409),
                                json={"role": {"name": role}, "group": {"id": group_id}})
        return response.status_code == 201

    def change_group_role(self, kind: str, resource_id: int, group_id: int, role: str) -> None:
        self.request("patch", f"/{kind}/{resource_id}/roles/groups/{group_id}", ok=(200, 204),
                     json={"name": role})

    def user_roles(self, kind: str, resource_id: int) -> list[dict]:
        return list(self.paginate(f"/{kind}/{resource_id}/roles/users"))

    def add_user_role(self, kind: str, resource_id: int, user_id: int, role: str) -> bool:
        response = self.request("post", f"/{kind}/{resource_id}/roles/users", ok=(201, 409),
                                json={"role": {"name": role}, "user": {"id": user_id}})
        return response.status_code == 201

    # ------------------------------------------------------------------ files
    def files(self, record_id: int) -> list[dict]:
        return list(self.paginate(f"/records/{record_id}/files"))

    def file_by_name(self, record_id: int, name: str) -> dict | None:
        response = self.request("get", f"/records/{record_id}/files/name/{name}", ok=(200, 404))
        return None if response.status_code == 404 else response.json()

    def download_file(self, record_id: int, file_id: str, dest: Path) -> Path:
        response = self.request("get", f"/records/{record_id}/files/{file_id}/download", ok=(200,), stream=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 20):
                if chunk:
                    fh.write(chunk)
        return dest

    def upload_file(self, record_id: int, path: Path, name: str, description: str = "",
                    mimetype: str | None = None, replace: bool = False,
                    progress: Callable[[int, int], None] | None = None) -> dict:
        """Upload ``path`` as ``name`` and verify size and checksum afterwards."""
        size = path.stat().st_size
        meta: dict[str, Any] = {"name": name, "size": size}
        if description:
            meta["description"] = description
        if mimetype:
            meta["mimetype"] = mimetype
        response = self.request("post", f"/records/{record_id}/uploads", ok=(201, 409), json=meta)
        if response.status_code == 409:
            if not replace:
                raise ApiError("post", f"/records/{record_id}/uploads", 409,
                               f"file '{name}' already exists (use replace to overwrite)")
            existing = self.file_by_name(record_id, name)
            if existing is None:
                raise ApiError("post", f"/records/{record_id}/uploads", 409, response.json())
            edit_meta = {k: v for k, v in meta.items() if k != "name"}
            response = self.request("put", f"/records/{record_id}/files/{existing['id']}", ok=(201,),
                                    json=edit_meta)
        upload = response.json()
        upload_id = upload["id"]
        endpoint = f"/records/{record_id}/uploads/{upload_id}"
        headers_base = {"Content-Type": "application/octet-stream"}

        if upload.get("upload_type") == "direct":
            data = path.read_bytes()
            md5 = hashlib.md5(data).hexdigest()
            response = self.request("put", endpoint, ok=(201,), data=data,
                                    headers={**headers_base, "Kadi-MD5-Checksum": md5})
            file_meta = response.json()
            expected = md5
        else:
            chunk_size = int(upload["_meta"]["chunk_size"])
            chunk_count = int(upload["chunk_count"])
            digests: list[str] = []
            sent = 0
            with path.open("rb") as fh:
                for index in range(chunk_count):
                    chunk = fh.read(chunk_size)
                    md5 = hashlib.md5(chunk).hexdigest()
                    digests.append(md5)
                    self.request("put", endpoint, ok=(200,), data=chunk,
                                 headers={**headers_base, "Kadi-Chunk-Index": str(index),
                                          "Kadi-Chunk-Size": str(len(chunk)), "Kadi-MD5-Checksum": md5})
                    sent += len(chunk)
                    if progress:
                        progress(sent, size)
            self.request("post", endpoint, ok=(202,))
            expected = hashlib.md5(bytes.fromhex("".join(digests))).hexdigest() + f"-{chunk_count}"
            file_meta = self._wait_for_upload(endpoint)

        if int(file_meta.get("size", -1)) != size:
            raise ApiError("put", endpoint, 0, f"size mismatch after upload of '{name}': "
                                               f"local {size}, server {file_meta.get('size')}")
        if file_meta.get("checksum") and file_meta["checksum"] != expected:
            raise ApiError("put", endpoint, 0, f"checksum mismatch after upload of '{name}': "
                                               f"local {expected}, server {file_meta['checksum']}")
        return file_meta

    def _wait_for_upload(self, endpoint: str, timeout: float = 600.0) -> dict:
        delay, waited = 0.5, 0.0
        while waited < timeout:
            time.sleep(delay)
            waited += delay
            data = self.request("get", endpoint, ok=(200, 404)).json()
            task = (data.get("_meta") or {}).get("task") or {}
            if "file" in task:
                return task["file"]
            if "error" in task:
                raise ApiError("get", endpoint, 0, f"upload processing failed: {task['error']}")
            delay = min(delay + 0.5, 5.0)
        raise ApiError("get", endpoint, 0, "upload processing did not finish in time")

    # ------------------------------------------------------------------ exports
    def export(self, kind: str, resource_id: int, export_type: str, dest: Path,
               export_filter: dict | None = None) -> Path:
        params = {"filter": json.dumps(export_filter)} if export_filter else None
        response = self.request("get", f"/{kind}/{resource_id}/export/{export_type}", ok=(200,),
                                params=params, stream=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 20):
                if chunk:
                    fh.write(chunk)
        return dest

    def export_json(self, kind: str, resource_id: int, export_filter: dict | None = None) -> dict:
        params = {"filter": json.dumps(export_filter)} if export_filter else None
        return self.request("get", f"/{kind}/{resource_id}/export/json", ok=(200,), params=params).json()
