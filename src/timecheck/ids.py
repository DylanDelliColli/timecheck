"""Opaque identifiers with 50 random bits."""
import base64
import secrets


def new_id(kind: str) -> str:
    prefix = {'claim': 'clm-', 'evidence': 'ev-'}[kind]
    return prefix + base64.b32encode(secrets.token_bytes(7)).decode('ascii')[:10].lower()
