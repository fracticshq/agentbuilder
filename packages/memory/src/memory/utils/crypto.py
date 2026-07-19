"""
Cryptography Utilities - AES-256-GCM encryption for PII vaulting
"""

import base64
import os
from typing import Dict, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import structlog

logger = structlog.get_logger()


class CryptoError(Exception):
    """Base exception for crypto operations."""
    pass


class CryptoUtils:
    """
    Cryptographic utilities for PII vaulting.
    
    Uses AES-256-GCM (authenticated encryption) for PII protection.
    """
    
    KEY_SIZE = 32  # 256 bits
    IV_SIZE = 12   # 96 bits (recommended for GCM)
    SALT_SIZE = 16  # 128 bits
    ALGORITHM = "AES-256-GCM"
    KDF = "PBKDF2-HMAC-SHA256"
    KDF_ITERATIONS = 100000
    ENCRYPTION_VERSION = 1

    def __init__(self, master_key: str, key_id: str = "default", key_version: int = 1):
        """
        Initialize crypto utils with master key.
        
        Args:
            master_key: Base64-encoded master key (32 bytes)
        
        Raises:
            CryptoError: If master key is invalid
        """
        try:
            self.master_key = base64.b64decode(master_key, validate=True)
            if len(self.master_key) != self.KEY_SIZE:
                raise CryptoError(f"Master key must be {self.KEY_SIZE} bytes")
            if not key_id:
                raise CryptoError("Key ID must not be empty")
            if key_version < 1:
                raise CryptoError("Key version must be at least 1")
            self.key_id = key_id
            self.key_version = key_version
        except Exception as e:
            raise CryptoError(f"Invalid master key: {e}")
    
    @staticmethod
    def generate_key() -> str:
        """
        Generate a new random master key.
        
        Returns:
            Base64-encoded 256-bit key
        """
        key = os.urandom(CryptoUtils.KEY_SIZE)
        return base64.b64encode(key).decode('utf-8')
    
    def _derive_key(self, salt: bytes, iterations: int | None = None) -> bytes:
        """
        Derive an encryption key from master key using PBKDF2.
        
        Args:
            salt: Salt for key derivation
        
        Returns:
            Derived key (32 bytes)
        """
        iterations = iterations if iterations is not None else self.KDF_ITERATIONS
        if iterations < 1:
            raise CryptoError("PBKDF2 iteration count must be at least 1")

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.KEY_SIZE,
            salt=salt,
            iterations=iterations,
            backend=default_backend()
        )
        return kdf.derive(self.master_key)
    
    def encrypt(self, plaintext: str) -> Tuple[str, str, str]:
        """
        Encrypt plaintext using AES-256-GCM.
        
        Args:
            plaintext: Text to encrypt
        
        Returns:
            Tuple of (ciphertext_b64, iv_b64, salt_b64)
        
        Raises:
            CryptoError: If encryption fails
        """
        try:
            # Generate random salt and IV
            salt = os.urandom(self.SALT_SIZE)
            iv = os.urandom(self.IV_SIZE)
            
            # Derive encryption key
            key = self._derive_key(salt)
            
            # Encrypt with AES-GCM
            aesgcm = AESGCM(key)
            plaintext_bytes = plaintext.encode('utf-8')
            ciphertext = aesgcm.encrypt(iv, plaintext_bytes, None)
            
            # Base64 encode for storage
            ciphertext_b64 = base64.b64encode(ciphertext).decode('utf-8')
            iv_b64 = base64.b64encode(iv).decode('utf-8')
            salt_b64 = base64.b64encode(salt).decode('utf-8')
            
            logger.debug("PII encrypted", 
                        plaintext_length=len(plaintext),
                        ciphertext_length=len(ciphertext_b64))
            
            return ciphertext_b64, iv_b64, salt_b64
            
        except Exception as e:
            logger.error("Encryption failed", error=str(e))
            raise CryptoError(f"Encryption failed: {e}")
    
    def decrypt(
        self,
        ciphertext_b64: str,
        iv_b64: str,
        salt_b64: str,
        *,
        kdf_iterations: int | None = None,
    ) -> str:
        """
        Decrypt ciphertext using AES-256-GCM.
        
        Args:
            ciphertext_b64: Base64-encoded ciphertext
            iv_b64: Base64-encoded initialization vector
            salt_b64: Base64-encoded salt
        
        Returns:
            Decrypted plaintext
        
        Raises:
            CryptoError: If decryption fails or authentication fails
        """
        try:
            # Decode from base64
            ciphertext = base64.b64decode(ciphertext_b64)
            iv = base64.b64decode(iv_b64)
            salt = base64.b64decode(salt_b64)
            
            # Derive decryption key (same process as encryption)
            key = self._derive_key(salt, kdf_iterations)
            
            # Decrypt with AES-GCM
            aesgcm = AESGCM(key)
            plaintext_bytes = aesgcm.decrypt(iv, ciphertext, None)
            plaintext = plaintext_bytes.decode('utf-8')
            
            logger.debug("PII decrypted", plaintext_length=len(plaintext))
            
            return plaintext
            
        except Exception as e:
            logger.error("Decryption failed", error=str(e))
            raise CryptoError(f"Decryption failed (possibly wrong key or corrupted data): {e}")
    
    def encrypt_dict(self, data: dict, fields_to_encrypt: list) -> dict:
        """
        Encrypt specific fields in a dictionary.
        
        Args:
            data: Dictionary with data
            fields_to_encrypt: List of field names to encrypt
        
        Returns:
            Dictionary with encrypted fields
        """
        encrypted = data.copy()
        
        for field in fields_to_encrypt:
            if field in encrypted and encrypted[field]:
                ciphertext, iv, salt = self.encrypt(str(encrypted[field]))
                encrypted[field] = {
                    "encrypted": True,
                    "ciphertext": ciphertext,
                    "iv": iv,
                    "salt": salt
                }
        
        return encrypted
    
    def decrypt_dict(self, data: dict, fields_to_decrypt: list) -> dict:
        """
        Decrypt specific fields in a dictionary.
        
        Args:
            data: Dictionary with encrypted data
            fields_to_decrypt: List of field names to decrypt
        
        Returns:
            Dictionary with decrypted fields
        """
        decrypted = data.copy()
        
        for field in fields_to_decrypt:
            if field in decrypted and isinstance(decrypted[field], dict):
                if decrypted[field].get("encrypted"):
                    plaintext = self.decrypt(
                        decrypted[field]["ciphertext"],
                        decrypted[field]["iv"],
                        decrypted[field]["salt"]
                    )
                    decrypted[field] = plaintext
        
        return decrypted


# Cache by key identity so separate vaults never accidentally reuse an
# unrelated master key or key version in the same process.
_crypto_instances: Dict[tuple[str, str, int], CryptoUtils] = {}


def get_crypto_utils(
    master_key: str = None,
    key_id: str = "default",
    key_version: int = 1,
) -> CryptoUtils:
    """
    Get or create CryptoUtils singleton.
    
    Args:
        master_key: Master key (required on first call)
    
    Returns:
        CryptoUtils instance
    """
    if master_key is None:
        raise CryptoError("Master key is required")

    cache_key = (master_key, key_id, key_version)
    if cache_key not in _crypto_instances:
        _crypto_instances[cache_key] = CryptoUtils(master_key, key_id, key_version)

    return _crypto_instances[cache_key]
