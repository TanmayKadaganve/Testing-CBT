"""
portal/services/starter_code.py
===============================
Domain service for managing and resolving language-aware starter code scaffolds.
Enforces the precedence:
1. Question-specific configured starter code
2. Generic language scaffold from LanguageRegistry
"""

from typing import Dict, List, Optional
from portal.models import CodingQuestion, CodingQuestionStarterCode
from portal.services.language_registry import LanguageRegistry


class StarterCodeService:
    """Service handling starter code resolution and persistence."""

    @classmethod
    def get_starter_code(cls, question: CodingQuestion, language: str) -> str:
        """
        Resolves starter code for a question and language.
        Precedence:
        1. Custom override in CodingQuestionStarterCode
        2. Generic scaffold from LanguageRegistry
        """
        lang = (language or "python").strip().lower()
        override = CodingQuestionStarterCode.objects.filter(
            coding_question=question, language=lang
        ).first()

        if override and override.code and override.code.strip():
            return override.code

        return LanguageRegistry.get_default_starter_code(lang)

    @classmethod
    def get_all_starter_codes_for_question(
        cls, question: CodingQuestion, language_ids: Optional[List[str]] = None
    ) -> Dict[str, str]:
        """
        Returns a mapping of {lang_id: starter_code} for all requested (or supported) languages.
        """
        if language_ids is None:
            language_ids = LanguageRegistry.get_supported_language_ids()

        overrides = {
            s.language: s.code
            for s in CodingQuestionStarterCode.objects.filter(
                coding_question=question, language__in=language_ids
            )
        }

        result = {}
        for lang_id in language_ids:
            if lang_id in overrides and overrides[lang_id].strip():
                result[lang_id] = overrides[lang_id]
            else:
                result[lang_id] = LanguageRegistry.get_default_starter_code(lang_id)

        return result

    @classmethod
    def set_starter_code(
        cls, question: CodingQuestion, language: str, code: str
    ) -> CodingQuestionStarterCode:
        """Creates or updates a custom starter code template for a question."""
        lang = language.strip().lower()
        starter, _ = CodingQuestionStarterCode.objects.update_or_create(
            coding_question=question,
            language=lang,
            defaults={"code": code},
        )
        return starter

