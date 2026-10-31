from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import translation
from django.utils.translation import gettext_noop

from schedule_kit import messages
from schedule_kit.messages import (
    ExecutionMessage,
    message_fields,
    render_all_languages,
    resolve_message,
)

BUILTINS = {
    messages.TASK_RAISED: {"exception": "ValueError"},
    messages.INVALID_RETURN: None,
    messages.INVALID_SUCCESS: None,
    messages.PENDING_TIMEOUT: {"status": "pending"},
    messages.INVALID_MESSAGE: None,
}


@pytest.mark.parametrize(
    "code",
    ["messagecenter.dashboard.delivery_failed", "schedule_kit.task_raised", "a-b.c_d"],
)
def test_valid_code(code):
    message = ExecutionMessage(code, "Delivery failed", {"recipient_count": 5})
    assert message.code == code
    assert message.msgid == "Delivery failed"
    assert dict(message.params) == {"recipient_count": 5}


@pytest.mark.parametrize(
    "code", ["has space.x", "no_prefix", "x." + "a" * 99, "", ".leading", None]
)
def test_invalid_code_is_configuration_error(code):
    with pytest.raises(ImproperlyConfigured, match="code"):
        ExecutionMessage(code, "Delivery failed")


def test_message_is_immutable_and_copies_params():
    params = {"count": 1}
    message = ExecutionMessage("app.x", "%(count)d", params)
    params["count"] = 2
    assert message.params["count"] == 1
    with pytest.raises(Exception):
        message.code = "app.y"
    with pytest.raises(TypeError):
        message.params["count"] = 3


def test_renders_every_language():
    assert render_all_languages(messages.TASK_RAISED.with_params(exception="KeyError")) == {
        "en": "Task raised KeyError",
        "zh-hant": "任務發生例外：KeyError",
    }


@pytest.mark.parametrize("builtin", list(BUILTINS), ids=lambda m: m.code)
def test_builtin_messages_render_in_both_languages(builtin):
    message = builtin.with_params(**BUILTINS[builtin]) if BUILTINS[builtin] else builtin
    assert builtin.code.startswith("schedule_kit.")
    rendered = render_all_languages(message)
    assert rendered["en"] == message.render("en")
    assert rendered["zh-hant"] != rendered["en"]
    assert "%(" not in rendered["en"] + rendered["zh-hant"]


def test_missing_translation_uses_english_msgid():
    message = ExecutionMessage("app.untranslated", gettext_noop("Nothing translated %(n)s"), {"n": 1})
    assert render_all_languages(message) == {
        "en": "Nothing translated 1",
        "zh-hant": "Nothing translated 1",
    }


def test_missing_param_falls_back_to_raw_msgid():
    fields = message_fields(ExecutionMessage("app.count", "%(count)d items", {}))
    assert fields["message"] == "%(count)d items"
    assert fields["message_i18n"]["zh-hant"] == "%(count)d items"
    assert fields["message_code"] == "app.count"


@pytest.mark.parametrize(
    "params", [{"value": object()}, {"nested": {"a": 1}}, ["list"], {"nan": float("nan")}]
)
def test_unserializable_params_become_invalid_message(params, caplog):
    fields = message_fields(ExecutionMessage("app.secret", "x %(value)s", params))
    assert fields["message_code"] == "schedule_kit.invalid_message"
    assert fields["message_params"] is None
    assert fields["message"] == "Task returned an invalid execution message"
    assert "app.secret" in caplog.text
    assert "object at" not in caplog.text


def test_rendering_does_not_change_worker_language():
    with translation.override("zh-hant"):
        fields = message_fields(messages.TASK_RAISED.with_params(exception="ValueError"))
        assert translation.get_language() == "zh-hant"
    assert fields["message"] == "Task raised ValueError"


def test_plain_text_keeps_legacy_fields():
    assert message_fields("ok") == {
        "message": "ok",
        "message_code": None,
        "message_params": None,
        "message_i18n": None,
    }
    assert message_fields("x" * 5000)["message"] == "x" * 4000


I18N = {"en": "English", "zh-hant": "中文"}


def _record(message_i18n, message="fallback"):
    return SimpleNamespace(message=message, message_i18n=message_i18n)


@pytest.mark.parametrize(
    "i18n, language, expected",
    [
        (I18N, "zh-hant", "中文"),
        ({"zh-Hant": "中文", "en": "English"}, "zh-hant", "中文"),
        ({"zh_Hant": "中文", "en": "English"}, "zh-hant", "中文"),
        ({"zh": "中文", "en": "English"}, "zh-hant", "中文"),
        (I18N, "ja", "English"),
        (None, "zh-hant", "fallback"),
        ({}, "zh-hant", "fallback"),
        (["zh-hant"], "zh-hant", "fallback"),
        ({"zh-hant": 1, "en": None}, "zh-hant", "fallback"),
    ],
)
def test_resolve_message(i18n, language, expected):
    assert resolve_message(_record(i18n), language) == expected


def test_resolve_message_uses_active_language():
    with translation.override("zh-hant"):
        assert resolve_message(_record(I18N)) == "中文"


def test_message_with_params_can_be_pickled_copied_and_hashed():
    import copy
    import pickle

    message = messages.TASK_RAISED.with_params(exception="ValueError")
    for clone in (pickle.loads(pickle.dumps(message)), copy.deepcopy(message)):
        assert clone == message
        assert dict(clone.params) == {"exception": "ValueError"}
        with pytest.raises(TypeError):
            clone.params["exception"] = "changed"  # still immutable
    assert hash(message) == hash(messages.TASK_RAISED.with_params(exception="ValueError"))
    assert {message: 1}[copy.copy(message)] == 1
