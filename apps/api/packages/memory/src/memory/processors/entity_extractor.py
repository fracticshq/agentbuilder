"""
Entity Extractor - Extract facts and preferences from conversation text

Uses rule-based patterns and confidence scoring to identify user facts.
"""

import re
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timezone
import structlog

from memory.types import ExtractedEntity, EpisodicFact
from memory.config import MemoryConfig
from memory.processors.pii_vault import PIIDetector

logger = structlog.get_logger()


class EntityExtractor:
    """
    Extract entities and facts from conversation text.
    
    Uses pattern matching and confidence scoring to identify:
    - User preferences
    - Personal context
    - Behavioral patterns
    """
    
    # Preference patterns
    PREFERENCE_PATTERNS = {
        "likes": r'\b(?:I (?:like|love|prefer|enjoy|want)|my favorite)\b',
        "dislikes": r'\b(?:I (?:don\'t like|hate|dislike|avoid)|I\'m not a fan of)\b',
        "needs": r'\b(?:I need|I require|I must have)\b',
        "interested_in": r'\b(?:I\'m interested in|I\'m looking for|I want to)\b',
    }
    
    # Context patterns
    CONTEXT_PATTERNS = {
        "location": r'\b(?:I live in|I\'m from|I\'m based in|my location is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b',
        "occupation": r'\b(?:I\'m a|I work as|my job is|I\'m employed as)\s+(\w+(?:\s+\w+)*)\b',
        "name": r'\b(?:my name is|I\'m|call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b',
        "age": r'\b(?:I\'m|I am)\s+(\d{1,3})\s+(?:years old|years|yrs)\b',
    }
    
    # Behavioral patterns
    BEHAVIOR_PATTERNS = {
        "frequency": r'\b(?:I (?:always|usually|often|sometimes|rarely|never))\s+(\w+(?:\s+\w+)*)\b',
        "habit": r'\b(?:I (?:tend to|typically|generally))\s+(\w+(?:\s+\w+)*)\b',
    }
    
    @classmethod
    def extract_entities(cls, text: str, conversation_id: str) -> List[ExtractedEntity]:
        """
        Extract entities from text.
        
        Args:
            text: Text to analyze
            conversation_id: Source conversation
        
        Returns:
            List of ExtractedEntity objects
        """
        entities = []
        text_lower = text.lower()
        
        # Extract preferences
        for pref_type, pattern in cls.PREFERENCE_PATTERNS.items():
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                # Extract the phrase after the pattern
                start_pos = match.end()
                end_pos = min(start_pos + 100, len(text))
                value = text[start_pos:end_pos].strip()
                
                # Get first sentence
                sentence_end = value.find('.')
                if sentence_end > 0:
                    value = value[:sentence_end]
                
                if value and len(value) > 3:
                    entity = ExtractedEntity(
                        entity_type=f"preference_{pref_type}",
                        value=value.strip(),
                        confidence=0.75,  # High confidence for explicit preferences
                        is_pii=PIIDetector.has_pii(value),
                        context=text[max(0, match.start()-20):min(len(text), match.end()+20)]
                    )
                    entities.append(entity)
        
        # Extract context (location, occupation, etc.)
        for context_type, pattern in cls.CONTEXT_PATTERNS.items():
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                if match.groups():
                    value = match.group(1).strip()
                    
                    # Check if it's PII
                    is_pii = context_type in ["name", "location", "age"]
                    
                    entity = ExtractedEntity(
                        entity_type=f"context_{context_type}",
                        value=value,
                        confidence=0.85,  # Very high confidence for explicit statements
                        is_pii=is_pii or PIIDetector.has_pii(value),
                        context=match.group(0)
                    )
                    entities.append(entity)
        
        # Extract behavioral patterns
        for behavior_type, pattern in cls.BEHAVIOR_PATTERNS.items():
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                if match.groups():
                    value = match.group(1).strip()
                    
                    if value and len(value) > 3:
                        entity = ExtractedEntity(
                            entity_type=f"behavior_{behavior_type}",
                            value=value,
                            confidence=0.70,  # Meets minimum threshold
                            is_pii=PIIDetector.has_pii(value),
                            context=match.group(0)
                        )
                        entities.append(entity)
        
        logger.debug("Entities extracted",
                    conversation_id=conversation_id,
                    entity_count=len(entities))
        
        return entities
    
    @classmethod
    def extract_facts(
        cls,
        text: str,
        user_id: str,
        conversation_id: str
    ) -> List[EpisodicFact]:
        """
        Extract episodic facts from text.
        
        Args:
            text: Text to analyze
            user_id: User identifier
            conversation_id: Conversation identifier
        
        Returns:
            List of EpisodicFact objects (only high-confidence ≥0.70)
        """
        entities = cls.extract_entities(text, conversation_id)
        facts = []
        
        for entity in entities:
            # Only store facts above confidence threshold
            if entity.confidence >= MemoryConfig.CONFIDENCE_THRESHOLD:
                # Calculate expiration (90 days from now)
                from datetime import timedelta
                expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=MemoryConfig.EPISODIC_TTL
                )
                
                fact = EpisodicFact(
                    id=f"{user_id}_{conversation_id}_{entity.entity_type}_{len(facts)}",
                    user_id=user_id,
                    conversation_id=conversation_id,
                    fact_type=entity.entity_type,
                    fact=f"{entity.entity_type}: {entity.value}",
                    confidence=entity.confidence,
                    pii_encrypted=entity.is_pii,
                    expires_at=expires_at,
                    metadata={
                        "context": entity.context,
                        "extracted_at": datetime.now(timezone.utc).isoformat()
                    }
                )
                facts.append(fact)
        
        logger.info("Facts extracted",
                   user_id=user_id,
                   conversation_id=conversation_id,
                   fact_count=len(facts),
                   high_confidence=sum(1 for f in facts if f.confidence >= 0.80))
        
        return facts
    
    @classmethod
    def merge_similar_facts(cls, facts: List[EpisodicFact]) -> List[EpisodicFact]:
        """
        Merge similar facts to avoid duplication.
        
        Args:
            facts: List of facts
        
        Returns:
            Deduplicated list
        """
        # Simple deduplication by fact type + value similarity
        seen = {}
        merged = []
        
        for fact in facts:
            key = f"{fact.fact_type}:{fact.fact[:50]}"
            
            if key not in seen:
                seen[key] = fact
                merged.append(fact)
            else:
                # Keep the one with higher confidence
                existing = seen[key]
                if fact.confidence > existing.confidence:
                    merged.remove(existing)
                    merged.append(fact)
                    seen[key] = fact
        
        return merged


class ConfidenceScorer:
    """
    Score confidence of extracted facts.
    
    Factors:
    - Explicit statements (0.85)
    - Implied preferences (0.75)
    - Behavioral patterns (0.70)
    - Uncertain language (-0.10)
    - Multiple mentions (+0.05 per mention)
    """
    
    EXPLICIT_MARKERS = ["I am", "my name is", "I live in", "I work as"]
    PREFERENCE_MARKERS = ["I like", "I prefer", "I love", "I want"]
    UNCERTAIN_MARKERS = ["maybe", "perhaps", "might", "possibly", "I think"]
    
    @classmethod
    def score(cls, text: str, entity: ExtractedEntity) -> float:
        """
        Calculate confidence score for an entity.
        
        Args:
            text: Full conversation text
            entity: Extracted entity
        
        Returns:
            Confidence score (0.0-1.0)
        """
        confidence = entity.confidence
        text_lower = text.lower()
        entity_lower = entity.value.lower()
        
        # Check for explicit markers
        for marker in cls.EXPLICIT_MARKERS:
            if marker.lower() in entity.context.lower():
                confidence = min(0.95, confidence + 0.10)
        
        # Check for uncertain language
        for marker in cls.UNCERTAIN_MARKERS:
            if marker in text_lower:
                confidence = max(0.50, confidence - 0.10)
        
        # Check for multiple mentions
        mention_count = text_lower.count(entity_lower)
        if mention_count > 1:
            confidence = min(0.95, confidence + (0.05 * (mention_count - 1)))
        
        return round(confidence, 2)
