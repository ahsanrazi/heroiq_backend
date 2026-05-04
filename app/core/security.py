import hashlib


def hash_api_key(api_key: str) -> str:
    """Hash an API key with SHA-256 for storage/comparison."""
    return hashlib.sha256(api_key.encode()).hexdigest()
