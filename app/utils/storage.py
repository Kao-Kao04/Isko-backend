import uuid
from supabase import create_client, Client
from app.config import settings

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _client


async def upload_file(file_bytes: bytes, original_filename: str, content_type: str) -> str:
    ext = original_filename.rsplit(".", 1)[-1]
    path = f"{uuid.uuid4()}.{ext}"
    sb = get_supabase()
    sb.storage.from_(settings.SUPABASE_BUCKET).upload(
        path, file_bytes, {"content-type": content_type}
    )
    return path


def get_public_url(path: str) -> str:
    sb = get_supabase()
    return sb.storage.from_(settings.SUPABASE_BUCKET).get_public_url(path)


async def delete_file(path: str) -> None:
    sb = get_supabase()
    sb.storage.from_(settings.SUPABASE_BUCKET).remove([path])
