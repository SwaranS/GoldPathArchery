"""Encrypted MFA secrets with an independently configured, rotatable key ring."""
from allauth.mfa.adapter import DefaultMFAAdapter
from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class EncryptedMFAAdapter(DefaultMFAAdapter):
    def cipher(self):
        keys = settings.MFA_ENCRYPTION_KEYS
        if not keys:
            raise ImproperlyConfigured("Configure MFA_ENCRYPTION_KEYS before enrolling MFA.")
        try:
            return MultiFernet([Fernet(key.encode("ascii")) for key in keys])
        except (ValueError, UnicodeError):
            raise ImproperlyConfigured("Invalid MFA encryption key configuration.") from None

    def encrypt(self, text):
        return self.cipher().encrypt(text.encode("utf-8")).decode("ascii")

    def decrypt(self, encrypted_text):
        return self.cipher().decrypt(encrypted_text.encode("ascii")).decode("utf-8")
