from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import time
from pathlib import Path

import requests

from app.config import settings


MAX_MEDIA_BYTES = 25 * 1024 * 1024  # 25 MB


class StorageError(RuntimeError):
    pass


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _storage_mode() -> str:
    return (_env("MEDIA_STORAGE") or "local").lower()


def _cloudinary_config() -> tuple[str, str, str]:
    return (
        _env("CLOUDINARY_CLOUD_NAME"),
        _env("CLOUDINARY_API_KEY"),
        _env("CLOUDINARY_API_SECRET"),
    )


def cloudinary_configured() -> bool:
    cloud_name, api_key, api_secret = _cloudinary_config()
    return bool(cloud_name and api_key and api_secret)


def storage_description() -> str:
    mode = _storage_mode()
    if mode == "cloudinary":
        return "cloudinary" if cloudinary_configured() else "cloudinary (configuration incomplete)"
    return "local filesystem"


def _safe_filename(filename: str) -> str:
    filename = Path(filename or "media").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    return cleaned or "media"


def _ensure_extension(filename: str, content_type: str | None) -> str:
    safe = _safe_filename(filename)
    if Path(safe).suffix:
        return safe

    mime = (content_type or "").split(";")[0].strip().lower()
    extension = mimetypes.guess_extension(mime) if mime else None
    return f"{safe}{extension or ''}"


def _cloudinary_signature(params: dict[str, str], api_secret: str) -> str:
    to_sign = "&".join(
        f"{key}={params[key]}"
        for key in sorted(params)
        if params[key] not in ("", None)
    )
    return hashlib.sha1(f"{to_sign}{api_secret}".encode("utf-8")).hexdigest()


def _store_cloudinary(
    data: bytes,
    filename: str,
    content_type: str | None,
    folder: str,
) -> str:
    cloud_name, api_key, api_secret = _cloudinary_config()

    if not cloud_name or not api_key or not api_secret:
        raise StorageError(
            "Cloudinary configuration incomplete. "
            "Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET."
        )

    timestamp = str(int(time.time()))
    params = {
        "folder": folder,
        "timestamp": timestamp,
    }

    signature = _cloudinary_signature(params, api_secret)

    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/auto/upload"
    files = {
        "file": (
            _ensure_extension(filename, content_type),
            data,
            content_type or "application/octet-stream",
        )
    }
    form = {
        **params,
        "api_key": api_key,
        "signature": signature,
    }

    try:
        response = requests.post(
            url,
            data=form,
            files=files,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise StorageError(f"Cloudinary connection failed: {exc}") from exc

    if response.status_code not in (200, 201):
        detail = response.text[:500]
        raise StorageError(
            f"Cloudinary returned HTTP {response.status_code}: {detail}"
        )

    payload = response.json()
    secure_url = payload.get("secure_url")

    if not secure_url:
        raise StorageError("Cloudinary response did not contain secure_url")

    return secure_url


def _store_local(
    data: bytes,
    filename: str,
    content_type: str | None,
) -> str:
    uploads_dir = settings.uploads_dir
    uploads_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _ensure_extension(filename, content_type)
    unique_name = f"{int(time.time() * 1000)}_{safe_name}"
    destination = uploads_dir / unique_name
    destination.write_bytes(data)

    return f"/uploads/{unique_name}"


def store_media_bytes(
    *,
    data: bytes,
    filename: str,
    content_type: str | None = None,
    folder: str = "artigianai/media",
) -> str:
    if not data:
        raise StorageError("Cannot store an empty file")

    if len(data) > MAX_MEDIA_BYTES:
        raise StorageError(
            f"File too large ({len(data)} bytes). Maximum is {MAX_MEDIA_BYTES} bytes."
        )

    mode = _storage_mode()

    if mode == "cloudinary":
        return _store_cloudinary(
            data=data,
            filename=filename,
            content_type=content_type,
            folder=folder,
        )

    if mode != "local":
        raise StorageError(
            f"Unsupported MEDIA_STORAGE={mode!r}. Use 'local' or 'cloudinary'."
        )

    return _store_local(
        data=data,
        filename=filename,
        content_type=content_type,
    )
