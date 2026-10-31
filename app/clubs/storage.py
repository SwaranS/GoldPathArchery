"""Private, opaque evidence objects. No public URL or caller-controlled path."""
import io
import re
import uuid
import warnings
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from PIL import Image, ImageOps


def normalize_upload(upload):
    limit = getattr(settings, "CLUB_EVIDENCE_MAX_BYTES", 5 * 1024 * 1024)
    if upload.size > limit or upload.content_type not in ("image/jpeg", "image/png"):
        raise ValidationError("Upload a JPEG or PNG image of at most 5 MB.")
    raw = upload.read(limit + 1)
    if len(raw) > limit:
        raise ValidationError("Evidence exceeds the upload limit.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as check:
                if check.format not in ("JPEG", "PNG") or check.width * check.height > 12_000_000:
                    raise ValueError
                check.verify()
            with Image.open(io.BytesIO(raw)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((2400, 2400))
                output = io.BytesIO()
                image.save(output, "JPEG", quality=88)
                return output.getvalue()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValidationError("Invalid evidence image.") from None


class PrivateEvidenceStore:
    def __init__(self):
        self.backend = getattr(settings, "CLUB_EVIDENCE_BACKEND", "disabled")
        if self.backend == "local":
            root = getattr(settings, "CLUB_EVIDENCE_ROOT", "")
            if not root or not Path(root).is_absolute():
                raise ImproperlyConfigured("An absolute private evidence root is required.")
            self.root = Path(root)
            from django.contrib.staticfiles.finders import get_finders
            served_roots = [getattr(settings, "STATIC_ROOT", ""), getattr(settings, "MEDIA_ROOT", ""),
                            settings.BASE_DIR / "staticfiles", settings.BASE_DIR / "static"]
            served_roots.extend(storage.location for finder in get_finders() for storage in getattr(finder, "storages", {}).values())
            for served in served_roots:
                if served and self.root.resolve().is_relative_to(Path(served).resolve()):
                    raise ImproperlyConfigured("Evidence storage must be outside served directories.")
        elif self.backend == "azure":
            from azure.storage.blob import BlobServiceClient
            self.container = BlobServiceClient.from_connection_string(
                settings.CLUB_EVIDENCE_AZURE_CONNECTION_STRING
            ).get_container_client(settings.CLUB_EVIDENCE_AZURE_CONTAINER)
            if self.container.get_container_properties().public_access:
                raise ImproperlyConfigured("Evidence container must be private.")
            if not self.container.url.startswith("https://"):
                raise ImproperlyConfigured("Private evidence requires Azure HTTPS transport.")
        else:
            raise ImproperlyConfigured("Private club evidence storage is disabled.")

    def validate_key(self, key):
        if not re.fullmatch(r"[a-f0-9]{32}\.jpg", key):
            raise ValidationError("Invalid evidence identifier.")

    def put(self, content, key=None):
        key = key or uuid.uuid4().hex + ".jpg"
        self.validate_key(key)
        if self.backend == "local":
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            with (self.root / key).open("xb") as output:
                output.write(content)
        else:
            self.container.upload_blob(key, content, overwrite=False)
        return key

    def get(self, key):
        self.validate_key(key)
        if self.backend == "local":
            if (self.root / key).is_symlink():
                raise ValidationError("Evidence symlinks are not allowed.")
            return (self.root / key).read_bytes()
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return self.container.download_blob(key).readall()
        except ResourceNotFoundError:
            raise FileNotFoundError from None

    def delete(self, key):
        self.validate_key(key)
        if self.backend == "local":
            (self.root / key).unlink(missing_ok=True)
        else:
            from azure.core.exceptions import ResourceNotFoundError
            try:
                self.container.delete_blob(key)
            except ResourceNotFoundError:
                pass  # Cleanup retries are idempotent.
