"""
portal/services/code_draft.py
=============================
Domain service for managing candidate code drafts.
Ensures:
- Independent draft persistence per (attempt, question, language)
- Version-checked optimistic concurrency (out-of-order autosaves ignored)
- Protection of drafts across language switching and question reloads
"""

import logging
import random
import time
from typing import Dict, List, Optional, Tuple

from django.db import IntegrityError, OperationalError, transaction

from portal.models import Attempt, CodeDraft, CodingQuestion
from portal.services.language_registry import LanguageRegistry
from portal.services.starter_code import StarterCodeService

logger = logging.getLogger(__name__)


class CodeDraftService:
    """Service handling candidate draft persistence and resolution."""

    @classmethod
    def save_draft(
        cls,
        attempt: Attempt,
        question: CodingQuestion,
        language: str,
        code: str,
        version: int = 1,
    ) -> Tuple[Optional[CodeDraft], Optional[str]]:
        """
        Saves or updates a candidate draft for (attempt, question, language).
        Guarantees that delayed, out-of-order autosave requests with older versions
        never overwrite newer code.

        Returns: (draft, error_message)
        """
        lang = (language or "python").strip().lower()
        if not LanguageRegistry.is_supported(lang):
            return None, f"Unsupported language '{language}'."

        incoming_version = max(1, int(version or 1))

        for attempt_i in range(5):
            try:
                with transaction.atomic():
                    draft, created = (
                        CodeDraft.objects.select_for_update()
                        .get_or_create(
                            attempt=attempt,
                            question=question,
                            language=lang,
                            defaults={
                                "code": code,
                                "version": incoming_version,
                            },
                        )
                    )

                    if not created:
                        # Only update if the incoming version is greater than or equal to current version
                        if incoming_version >= draft.version:
                            draft.code = code
                            draft.version = incoming_version
                            draft.save(update_fields=["code", "version", "updated_at"])
                        else:
                            logger.info(
                                "Ignored outdated draft version %s for attempt %s, Q%s, %s (current: %s)",
                                incoming_version,
                                attempt.id,
                                question.id,
                                lang,
                                draft.version,
                            )

                return draft, None

            except IntegrityError:
                # Concurrent insert race: retry select_for_update on next iteration
                continue
            except OperationalError:
                time.sleep(0.02 * (1.5 ** attempt_i) + random.uniform(0.005, 0.015))

        return None, "Database busy. Unable to persist draft."

    @classmethod
    def get_draft(
        cls, attempt: Attempt, question: CodingQuestion, language: str
    ) -> Optional[CodeDraft]:
        """Retrieves a single draft for (attempt, question, language)."""
        lang = (language or "python").strip().lower()
        return CodeDraft.objects.filter(
            attempt=attempt, question=question, language=lang
        ).first()

    @classmethod
    def get_all_drafts_map(
        cls, attempt: Attempt, questions: List[CodingQuestion]
    ) -> Dict[int, Dict[str, Dict]]:
        """
        Returns a nested dictionary mapping question_id -> {language: {"code": ..., "version": ...}}.
        """
        drafts = CodeDraft.objects.filter(
            attempt=attempt, question__in=questions
        ).order_by("updated_at")

        drafts_map: Dict[int, Dict[str, Dict]] = {q.id: {} for q in questions}
        for d in drafts:
            drafts_map[d.question_id][d.language] = {
                "code": d.code,
                "version": d.version,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }

        return drafts_map

    @classmethod
    def resolve_question_state(
        cls,
        attempt: Attempt,
        question: CodingQuestion,
        supported_languages: Optional[List[str]] = None,
    ) -> Dict:
        """
        Builds the complete state for a question:
        - All starter codes per supported language
        - All saved drafts per supported language
        - Active language (most recently updated draft, or 'python')
        - Active code (saved draft or starter code)
        """
        if supported_languages is None:
            supported_languages = LanguageRegistry.get_supported_language_ids()

        starter_codes = StarterCodeService.get_all_starter_codes_for_question(
            question, supported_languages
        )

        existing_drafts = list(
            CodeDraft.objects.filter(
                attempt=attempt, question=question, language__in=supported_languages
            ).order_by("-updated_at")
        )

        drafts_dict = {
            d.language: {"code": d.code, "version": d.version}
            for d in existing_drafts
        }

        # Determine active language: latest updated draft if any, else default to python (or first supported)
        if existing_drafts:
            active_lang = existing_drafts[0].language
            active_code = existing_drafts[0].code
            active_version = existing_drafts[0].version
        else:
            active_lang = "python" if "python" in supported_languages else supported_languages[0]
            active_code = starter_codes.get(active_lang, "")
            active_version = 1

        return {
            "id": question.id,
            "title": question.title,
            "statement": question.statement,
            "input_format": question.input_format,
            "output_format": question.output_format,
            "constraints": question.constraints,
            "sample_input": question.sample_input,
            "sample_output": question.sample_output,
            "marks": question.marks,
            "starter_codes": starter_codes,
            "drafts": drafts_dict,
            "active_language": active_lang,
            "code": active_code,
            "version": active_version,
        }

