import logging
import uuid
from fastapi import HTTPException
from app.config import settings

logger = logging.getLogger(__name__)

_supabase_client = None


def get_supabase():
    global _supabase_client
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY in .env"
        )
    if _supabase_client is None:
        from supabase import create_client
        _supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _supabase_client


async def upload_file(file_bytes: bytes, original_filename: str, content_type: str) -> str:
    import asyncio
    ext = original_filename.rsplit(".", 1)[-1] if "." in original_filename else "bin"
    path = f"{uuid.uuid4()}.{ext}"
    try:
        sb = get_supabase()
        await asyncio.to_thread(
            sb.storage.from_(settings.SUPABASE_BUCKET).upload,
            path, file_bytes, {"content-type": content_type},
        )
        return path
    except Exception as exc:
        logger.error("Storage upload failed for %s: %s", original_filename, exc)
        raise HTTPException(status_code=503, detail=f"File upload failed: {exc}")


def get_public_url(path: str) -> str:
    if not path:
        return ""
    try:
        sb = get_supabase()
        return sb.storage.from_(settings.SUPABASE_BUCKET).get_public_url(path)
    except Exception:
        return ""


async def delete_file(path: str) -> None:
    if not path:
        return
    try:
        sb = get_supabase()
        sb.storage.from_(settings.SUPABASE_BUCKET).remove([path])
    except Exception:
        pass
