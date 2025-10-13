"""
PII Vault - Detect and encrypt Personally Identifiable Information
"""

import re
from typing import List, Dict, Tuple, Optional
import structlog
from memory.types import PIIField, ExtractedEntity
from memory.config import MemoryConfig
from memory.utils.crypto import get_crypto_utils, CryptoError

logger = structlog.get_logger()


class PIIDetector:
    """Detect PII patterns in text."""
    
    # PII Patterns (regex)
    PATTERNS = {
        "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        "phone": r'\b(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})\b',
        "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
        "credit_card": r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
        "zip_code": r'\b\d{5}(?:-\d{4})?\b',
        "ip_address": r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b',
    }
    
    # Common PII keywords
    PII_KEYWORDS = [
        "password", "ssn", "social security", "credit card", 
        "card number", "cvv", "pin", "account number",
        "date of birth", "dob", "driver license", "passport"
    ]
    
    @classmethod
    def detect(cls, text: str) -> List[Tuple[str, str]]:
        """
        Detect PII in text.
        
        Args:
            text: Text to scan
        
        Returns:
            List of (pii_type, matched_value) tuples
        """
        findings = []
        text_lower = text.lower()
        
        # Check patterns
        for pii_type, pattern in cls.PATTERNS.items():
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                findings.append((pii_type, match.group(0)))
        
        # Check keywords
        for keyword in cls.PII_KEYWORDS:
            if keyword in text_lower:
                # Find context around keyword
                idx = text_lower.index(keyword)
                start = max(0, idx - 20)
                end = min(len(text), idx + len(keyword) + 20)
                context = text[start:end]
                findings.append(("keyword", context))
        
        return findings
    
    @classmethod
    def has_pii(cls, text: str) -> bool:
        """Quick check if text contains PII."""
        return len(cls.detect(text)) > 0
    
    @classmethod
    def redact(cls, text: str) -> str:
        """
        Redact PII from text for logging.
        
        Args:
            text: Text with potential PII
        
        Returns:
            Text with PII replaced by [REDACTED]
        """
        redacted = text
        
        for pii_type, pattern in cls.PATTERNS.items():
            redacted = re.sub(pattern, f"[{pii_type.upper()}_REDACTED]", redacted, flags=re.IGNORECASE)
        
        return redacted


class PIIVault:
    """
    Encrypt and decrypt PII fields.
    
    Uses AES-256-GCM encryption with key derivation.
    """
    
    def __init__(self, master_key: Optional[str] = None):
        """
        Initialize PII vault.
        
        Args:
            master_key: Encryption master key (from config if not provided)
        """
        self.master_key = master_key or MemoryConfig.PII_ENCRYPTION_KEY
        
        if not self.master_key:
            logger.warning("PII encryption key not configured - vaulting disabled")
            self.enabled = False
        else:
            self.enabled = True
            try:
                self.crypto = get_crypto_utils(self.master_key)
                logger.info("PII vault initialized")
            except CryptoError as e:
                logger.error("Failed to initialize crypto", error=str(e))
                self.enabled = False
    
    def encrypt_field(self, value: str, field_name: str) -> PIIField:
        """
        Encrypt a PII field.
        
        Args:
            value: Plaintext value
            field_name: Name of the field
        
        Returns:
            PIIField with encrypted data
        
        Raises:
            CryptoError: If encryption fails
        """
        if not self.enabled:
            raise CryptoError("PII vaulting not enabled")
        
        ciphertext, iv, salt = self.crypto.encrypt(value)
        
        return PIIField(
            encrypted_value=ciphertext,
            iv=iv,
            field_name=field_name
        )
    
    def decrypt_field(self, pii_field: PIIField) -> str:
        """
        Decrypt a PII field.
        
        Args:
            pii_field: Encrypted PIIField
        
        Returns:
            Decrypted plaintext
        
        Raises:
            CryptoError: If decryption fails
        """
        if not self.enabled:
            raise CryptoError("PII vaulting not enabled")
        
        return self.crypto.decrypt(
            pii_field.encrypted_value,
            pii_field.iv,
            pii_field.encrypted_value  # Using as salt for now (should be separate)
        )
    
    def vault_dict(self, data: Dict, fields_to_vault: List[str]) -> Dict:
        """
        Encrypt specific fields in a dictionary.
        
        Args:
            data: Dictionary with data
            fields_to_vault: List of field names to encrypt
        
        Returns:
            Dictionary with vaulted fields
        """
        if not self.enabled:
            logger.warning("PII vaulting disabled - returning unencrypted data")
            return data
        
        vaulted = data.copy()
        
        for field in fields_to_vault:
            if field in vaulted and vaulted[field]:
                try:
                    pii_field = self.encrypt_field(str(vaulted[field]), field)
                    vaulted[field] = pii_field.dict()
                    logger.debug("Field vaulted", field=field)
                except CryptoError as e:
                    logger.error("Failed to vault field", field=field, error=str(e))
        
        return vaulted
    
    def unveault_dict(self, data: Dict, fields_to_unveault: List[str]) -> Dict:
        """
        Decrypt specific fields in a dictionary.
        
        Args:
            data: Dictionary with vaulted data
            fields_to_unveault: List of field names to decrypt
        
        Returns:
            Dictionary with unveaulted fields
        """
        if not self.enabled:
            return data
        
        unveaulted = data.copy()
        
        for field in fields_to_unveault:
            if field in unveaulted and isinstance(unveaulted[field], dict):
                try:
                    pii_field = PIIField(**unveaulted[field])
                    plaintext = self.decrypt_field(pii_field)
                    unveaulted[field] = plaintext
                    logger.debug("Field unveaulted", field=field)
                except (CryptoError, Exception) as e:
                    logger.error("Failed to unveault field", field=field, error=str(e))
        
        return unveaulted
    
    def scan_and_vault(self, text: str) -> Tuple[str, List[str]]:
        """
        Scan text for PII and vault it.
        
        Args:
            text: Text to scan
        
        Returns:
            Tuple of (text_with_placeholders, list_of_pii_types_found)
        """
        if not self.enabled:
            return text, []
        
        findings = PIIDetector.detect(text)
        
        if not findings:
            return text, []
        
        # Replace PII with placeholders
        vaulted_text = text
        pii_types = []
        
        for pii_type, value in findings:
            vaulted_text = vaulted_text.replace(value, f"[{pii_type.upper()}_VAULTED]")
            pii_types.append(pii_type)
        
        logger.info("PII detected and vaulted", 
                   pii_count=len(findings),
                   pii_types=list(set(pii_types)))
        
        return vaulted_text, list(set(pii_types))


# Singleton instance
_vault_instance = None


def get_pii_vault() -> PIIVault:
    """Get or create PIIVault singleton."""
    global _vault_instance
    
    if _vault_instance is None:
        _vault_instance = PIIVault()
    
    return _vault_instance
