"""
Run once to create and configure the Supabase storage bucket.
Usage: python scripts/setup_supabase_bucket.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import settings
from app.utils.storage import get_supabase

def main():
    print("Connecting to Supabase...")
    sb = get_supabase()

    bucket_name = settings.SUPABASE_BUCKET
    print(f"Setting up bucket: '{bucket_name}'")

    # Check if bucket already exists
    buckets = sb.storage.list_buckets()
    existing = [b.name for b in buckets]

    if bucket_name in existing:
        print(f"  Bucket '{bucket_name}' already exists.")
    else:
        sb.storage.create_bucket(bucket_name, options={"public": True})
        print(f"  Bucket '{bucket_name}' created (public).")

    # Test upload
    test_bytes = b"iskomo-test"
    test_path  = "_setup_test.txt"
    sb.storage.from_(bucket_name).upload(test_path, test_bytes, {"content-type": "text/plain"})
    url = sb.storage.from_(bucket_name).get_public_url(test_path)
    sb.storage.from_(bucket_name).remove([test_path])
    print(f"  Upload test passed. Public URL base: {url.split('_setup')[0]}")
    print("\nSupabase storage is ready.")

if __name__ == "__main__":
    main()
