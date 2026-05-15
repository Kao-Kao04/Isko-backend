"""File upload validation using magic byte inspection.

Checks the actual file content rather than the client-supplied Content-Type
header, which can be spoofed. No external dependencies — pure Python.
"""

from app.exceptions import ValidationError

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

_MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\x25\x50\x44\x46", "application/pdf"),   # %PDF
    (b"\xff\xd8\xff",      "image/jpeg"),         # JPEG SOI
    (b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a", "image/png"),  # PNG
]

ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png"}


def _detect_mime(header: bytes) -> str | None:
    for signature, mime in _MAGIC_SIGNATURES:
        if header[: len(signature)] == signature:
            return mime
    return None


def validate_file_bytes(contents: bytes, filename: str = "") -> None:
    """Raise ValidationError if the file is too large or not an allowed type."""
    if len(contents) > MAX_FILE_SIZE:
        raise ValidationError("File exceeds the 5 MB size limit.")

    detected = _detect_mime(contents[:16])
    if detected not in ALLOWED_MIME:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
        raise ValidationError(
            f"File type not allowed (detected: {detected or ext!r}). "
            "Only PDF, JPEG, and PNG files are accepted."
        )
