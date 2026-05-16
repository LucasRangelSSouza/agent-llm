import bcrypt


def hash_password(raw_password: str) -> str:
    encoded = raw_password.encode("utf-8")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(raw_password: str, password_hash: str) -> bool:
    if not raw_password or not password_hash:
        return False
    return bcrypt.checkpw(raw_password.encode("utf-8"), password_hash.encode("utf-8"))
