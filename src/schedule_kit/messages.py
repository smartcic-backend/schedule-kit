"""Coded, multi-language execution messages.

A task describes its outcome as ``ExecutionMessage(code, msgid, params)``. When the
record is completed, the msgid is rendered once per ``settings.LANGUAGES`` entry
(``message_i18n``) and once in English (``message``), so readers can show the
viewer's language without shipping this project's translation catalog.

Define messages with ``gettext_noop`` so ``makemessages`` collects the msgid::

    from django.utils.translation import gettext_noop
    from schedule_kit.messages import ExecutionMessage

    DELIVERY_FAILED = ExecutionMessage(
        "messagecenter.dashboard.delivery_failed",
        gettext_noop("Dashboard report delivery failed for %(recipient_count)d recipients"),
    )
    return instance, False, DELIVERY_FAILED.with_params(recipient_count=5)

Params are stored in the shared main table: only put values that are safe to show.
"""

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import lru_cache
from types import MappingProxyType

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils import translation
from django.utils.translation import gettext_noop
from django.utils.translation.trans_real import DjangoTranslation

logger = logging.getLogger(__name__)

# `message` always stores this language so filters and fallbacks do not depend on
# the worker's LANGUAGE_CODE. Matches the main project's BASE_LANGUAGE.
BASE_LANGUAGE = "en"
MESSAGE_MAX_LENGTH = 4000

# "<project or package>.<name>", 1-100 chars of letters, digits, `.`, `_`, `-`.
_CODE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\.[A-Za-z0-9_.-]+")
_SCALARS = (str, int, float, bool, type(None))


def _normalize_language(language) -> str:
    return str(language or "").lower().replace("_", "-")


class _MessageTranslation(DjangoTranslation):
    # Django's catalog loader preserves app/LOCALE_PATHS precedence and locale
    # variants. Override only its default-language fallback, so a missing msgid
    # stays English. Do not mutate Django's shared translation objects.
    def _add_fallback(self, localedirs=None):
        pass


@lru_cache(maxsize=128)
def _message_translation(language):
    return _MessageTranslation(language)


@receiver(setting_changed)
def _clear_message_translations(*, setting, **kwargs):
    if setting in {"LANGUAGE_CODE", "LOCALE_PATHS", "INSTALLED_APPS", "USE_I18N"}:
        _message_translation.cache_clear()


@dataclass(frozen=True)
class ExecutionMessage:
    code: str
    msgid: str
    # Excluded from hash: a mapping is unhashable. Equal messages still hash equal.
    params: Mapping | None = field(default=None, hash=False)

    def __post_init__(self):
        if (
            not isinstance(self.code, str)
            or len(self.code) > 100
            or not _CODE_PATTERN.fullmatch(self.code)
        ):
            raise ImproperlyConfigured(
                f"Invalid execution message code {self.code!r}: use 1-100 letters, digits, "
                "'.', '_' or '-', prefixed with the project or package name "
                "(e.g. 'messagecenter.delivery_failed')."
            )
        if not isinstance(self.msgid, str) or not self.msgid:
            raise ImproperlyConfigured(
                f"Execution message {self.code!r} needs a non-empty English msgid."
            )
        if isinstance(self.params, Mapping):
            # Freeze a copy: later changes to the caller's dict must not leak in.
            object.__setattr__(self, "params", MappingProxyType(dict(self.params)))

    def __reduce__(self):
        # MappingProxyType cannot be pickled/deep-copied: rebuild from a plain dict.
        params = dict(self.params) if isinstance(self.params, Mapping) else self.params
        return (type(self), (self.code, self.msgid, params))

    def with_params(self, **params) -> "ExecutionMessage":
        return replace(self, params=params)

    def json_params(self) -> dict | None:
        """Params as a plain JSON object, or raise ValueError if unsafe/unserializable."""
        if self.params is None:
            return None
        if not isinstance(self.params, Mapping):
            raise ValueError("params must be a JSON object")
        params = dict(self.params)
        if not all(isinstance(key, str) for key in params) or not all(
            isinstance(value, _SCALARS) for value in params.values()
        ):
            raise ValueError("params values must be str, number, bool or null")
        json.dumps(params, allow_nan=False)  # NaN/Infinity are rejected by jsonb.
        return params

    def render(self, language: str) -> str:
        """Render in `language`; a formatting error falls back to the raw msgid."""
        text = self.msgid
        if settings.USE_I18N:
            text = _message_translation(_normalize_language(language)).gettext(self.msgid)
        if self.params is None:
            return text
        try:
            return text % dict(self.params)
        except (KeyError, TypeError, ValueError, OverflowError):
            return self.msgid


# Built-in messages. Translations live in schedule_kit/locale.
TASK_RAISED = ExecutionMessage(
    "schedule_kit.task_raised", gettext_noop("Task raised %(exception)s")
)
INVALID_RETURN = ExecutionMessage(
    "schedule_kit.invalid_return",
    gettext_noop("Task must return (instance, success, message)"),
)
INVALID_SUCCESS = ExecutionMessage(
    "schedule_kit.invalid_success", gettext_noop("Task success must be bool or None")
)
PENDING_TIMEOUT = ExecutionMessage(
    "schedule_kit.pending_timeout",
    # Same English text as 0.2.0 so existing message filters keep matching.
    gettext_noop("timeout: %(status)s exceeded configured limit"),
)
INVALID_MESSAGE = ExecutionMessage(
    "schedule_kit.invalid_message",
    gettext_noop("Task returned an invalid execution message"),
)


def _safe(message: ExecutionMessage) -> tuple[ExecutionMessage, dict | None]:
    try:
        return message, message.json_params()
    except (TypeError, ValueError):
        # Log the code only: param values may be sensitive.
        logger.warning("Invalid execution message params for code %s", message.code)
        return INVALID_MESSAGE, None


def render_all_languages(message: ExecutionMessage) -> dict[str, str]:
    """Render `message` in every settings.LANGUAGES entry (keys normalized, e.g. zh-hant)."""
    message, _params = _safe(message)
    return {
        _normalize_language(code): message.render(code)[:MESSAGE_MAX_LENGTH]
        for code, _name in settings.LANGUAGES
    }


def message_fields(message) -> dict:
    """ExecutionRecord column values for an ExecutionMessage or legacy plain text."""
    if isinstance(message, ExecutionMessage):
        message, params = _safe(message)
        return {
            "message": message.render(BASE_LANGUAGE)[:MESSAGE_MAX_LENGTH],
            "message_code": message.code,
            "message_params": params,
            "message_i18n": render_all_languages(message),
        }
    return {
        "message": str(message or "")[:MESSAGE_MAX_LENGTH],
        "message_code": None,
        "message_params": None,
        "message_i18n": None,
    }


def resolve_message(record, language=None) -> str:
    """Pick message_i18n for `language`: exact → primary → en → message (as the main project)."""
    fallback = record.message or ""
    i18n = record.message_i18n
    if not isinstance(i18n, dict) or not i18n:
        return fallback
    texts = {
        _normalize_language(key): value
        for key, value in i18n.items()
        if isinstance(value, str) and value
    }
    lang = _normalize_language(language or translation.get_language())
    for candidate in (lang, lang.split("-")[0], BASE_LANGUAGE):
        if candidate and candidate in texts:
            return texts[candidate]
    return fallback
