from __future__ import annotations

import json
import os
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID


class AuthVerificationError(Exception):
    pass


class SupabaseAuthService:
    def __init__(self, project_url, publishable_key, timeout=10, opener=None):
        self.user_url = f"{project_url.rstrip('/')}/auth/v1/user"
        self.publishable_key = publishable_key
        self.timeout = timeout
        self.opener = opener or urlopen

    def verify_access_token(self, access_token):
        token = str(access_token or "").strip()
        if not token or len(token) > 8192:
            raise AuthVerificationError("Invalid access token")

        auth_request = Request(
            self.user_url,
            headers={
                "apikey": self.publishable_key,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with self.opener(auth_request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            error.close()
            raise AuthVerificationError("Supabase rejected the access token") from error
        except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AuthVerificationError("Supabase rejected the access token") from error

        if not isinstance(payload, dict):
            raise AuthVerificationError("Supabase returned an invalid user")

        user_id = payload.get("id")
        try:
            normalized_id = str(UUID(str(user_id)))
        except (TypeError, ValueError, AttributeError) as error:
            raise AuthVerificationError("Supabase returned an invalid user") from error

        email = payload.get("email")
        if email is not None and not isinstance(email, str):
            raise AuthVerificationError("Supabase returned an invalid user")

        return {
            "id": normalized_id,
            "email": (email or "").strip(),
        }


def load_or_create_session_secret(configured_secret, secret_path):
    configured = str(configured_secret or "").strip()
    if configured:
        if len(configured) < 32:
            raise ValueError("CLASSMOOD_SESSION_SECRET must be at least 32 characters")
        return configured

    try:
        with open(secret_path, "r", encoding="ascii") as secret_file:
            persisted = secret_file.read().strip()
    except FileNotFoundError:
        persisted = ""

    if persisted:
        if len(persisted) < 32:
            raise ValueError("Persisted session secret is invalid")
        return persisted

    os.makedirs(os.path.dirname(secret_path), exist_ok=True)
    generated = secrets.token_urlsafe(48)
    try:
        descriptor = os.open(
            secret_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        with open(secret_path, "r", encoding="ascii") as secret_file:
            persisted = secret_file.read().strip()
        if len(persisted) < 32:
            raise ValueError("Persisted session secret is invalid")
        return persisted

    with os.fdopen(descriptor, "w", encoding="ascii") as secret_file:
        secret_file.write(generated)
    return generated
