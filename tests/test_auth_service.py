import io
import os
import sys
import tempfile
import unittest
from urllib.error import HTTPError


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from auth_service import (
    AuthVerificationError,
    SupabaseAuthService,
    load_or_create_session_secret,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class SupabaseAuthServiceTests(unittest.TestCase):
    def test_verifies_user_through_supabase_auth_endpoint(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return FakeResponse(
                b'{"id":"12345678-1234-5678-1234-567812345678",'
                b'"email":"teacher@example.com"}',
            )

        service = SupabaseAuthService(
            "https://example.supabase.co/",
            "sb_publishable_test",
            timeout=4,
            opener=opener,
        )

        user = service.verify_access_token("access-token")

        self.assertEqual(user["email"], "teacher@example.com")
        request, timeout = requests[0]
        self.assertEqual(timeout, 4)
        self.assertEqual(
            request.full_url,
            "https://example.supabase.co/auth/v1/user",
        )
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer access-token",
        )
        self.assertEqual(request.get_header("Apikey"), "sb_publishable_test")

    def test_rejects_provider_errors_and_invalid_users(self):
        def rejected_opener(request, timeout):
            raise HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                {},
                io.BytesIO(b"{}"),
            )

        service = SupabaseAuthService(
            "https://example.supabase.co",
            "sb_publishable_test",
            opener=rejected_opener,
        )
        with self.assertRaises(AuthVerificationError):
            service.verify_access_token("bad-token")

        invalid_service = SupabaseAuthService(
            "https://example.supabase.co",
            "sb_publishable_test",
            opener=lambda *_args, **_kwargs: FakeResponse(b'{"id":"bad"}'),
        )
        with self.assertRaises(AuthVerificationError):
            invalid_service.verify_access_token("access-token")

    def test_session_secret_is_persisted_and_reused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_path = os.path.join(temp_dir, "session-secret")

            first = load_or_create_session_secret("", secret_path)
            second = load_or_create_session_secret("", secret_path)

            self.assertGreaterEqual(len(first), 32)
            self.assertEqual(second, first)

    def test_configured_session_secret_must_be_long_enough(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_path = os.path.join(temp_dir, "unused")
            with self.assertRaises(ValueError):
                load_or_create_session_secret("too-short", secret_path)


if __name__ == "__main__":
    unittest.main()
