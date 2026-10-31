"""Private storage: no public URL, signed URL or caller-provided path."""
import io
import os
import re
import uuid
import warnings
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from PIL import Image, ImageOps

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000


def normalize_image(upload):
    if upload.size > MAX_BYTES or upload.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise ValidationError("Upload a JPEG, PNG or WebP image of at most 8 MB (receipts may be photographed).")
    raw = upload.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValidationError("Image exceeds 8 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as check:
                if check.width * check.height > MAX_PIXELS or check.format not in ("JPEG", "PNG", "WEBP") or check.get_format_mimetype() != upload.content_type:
                    raise ValueError
                check.verify()
            with Image.open(io.BytesIO(raw)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((2400, 2400))
                # Re-encoding strips metadata and appended payloads; no SVG/PDF/active content.
                output = io.BytesIO(); image.save(output, "JPEG", quality=88)
                return output.getvalue()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValidationError("Invalid or unsupported image.") from None


class PrivateMediaStore:
    def __init__(self):
        self.backend = os.environ.get("EQUIPMENT_MEDIA_BACKEND", "local" if settings.DEBUG else "disabled")
        self.root = Path(os.environ.get("EQUIPMENT_MEDIA_ROOT", str(settings.BASE_DIR / "private-equipment")))
        if self.backend == "azure":
            from azure.storage.blob import BlobServiceClient
            connection = os.environ.get("EQUIPMENT_AZURE_CONNECTION_STRING")
            container = os.environ.get("EQUIPMENT_AZURE_CONTAINER")
            if not connection or not container:
                raise ImproperlyConfigured("Configure private equipment storage credentials.")
            self.container = BlobServiceClient.from_connection_string(connection).get_container_client(container)
            if self.container.get_container_properties().public_access:
                raise ImproperlyConfigured("Equipment container must be private.")
        elif self.backend != "local":
            raise ImproperlyConfigured("Private equipment media storage is not configured.")

    def validate_key(self, key):
        if not re.fullmatch(r"[a-f0-9]{32}\.jpg", key):
            raise ValidationError("Invalid media identifier.")

    def put(self, content):
        key = uuid.uuid4().hex + ".jpg"
        if self.backend == "azure":
            from azure.storage.blob import ContentSettings
            self.container.upload_blob(key, content, overwrite=False, content_settings=ContentSettings(content_type="image/jpeg"))
        else:
            self.root.mkdir(parents=True, exist_ok=True)
            with (self.root / key).open("xb") as output:
                output.write(content)
        return key

    def get(self, key):
        self.validate_key(key)
        if self.backend == "azure":
            return self.container.download_blob(key).readall()
        return (self.root / key).read_bytes()

    def delete(self, key):
        self.validate_key(key)
        if self.backend == "azure":
            self.container.delete_blob(key)
        else:
            (self.root / key).unlink(missing_ok=True)
