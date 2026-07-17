from types import SimpleNamespace
from unittest.mock import patch

import product_runtime_final as runtime


def _update(user_id: int, username: str | None = None):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, username=username),
        effective_chat=SimpleNamespace(id=-100123, type="supergroup"),
    )


def _private_reply_update(user_id: int, source_text: str | None):
    reply = SimpleNamespace(text=source_text, caption=None) if source_text else None
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, username=None),
        effective_chat=SimpleNamespace(id=user_id, type="private"),
        effective_message=SimpleNamespace(reply_to_message=reply),
    )


def test_premium_payment_requires_exact_payload_currency_and_amount():
    assert runtime._valid_premium_payment("premium_stars_1month", "XTR", 99)
    assert runtime._valid_premium_payment("premium_card_1month", "RUB", 29_900)

    assert not runtime._valid_premium_payment("premium_stars_fake", "XTR", 99)
    assert not runtime._valid_premium_payment("premium_stars_1month", "RUB", 99)
    assert not runtime._valid_premium_payment("premium_stars_1month", "XTR", 1)


def test_chat_membership_alone_does_not_grant_operator_access():
    with (
        patch.object(runtime.bot, "ADMIN_IDS", {-100123}),
        patch.object(runtime, "list_operator_ids", return_value=[]),
    ):
        assert not runtime.is_authorized_operator(_update(555))


def test_admin_user_id_grants_operator_access():
    with patch.object(runtime.bot, "ADMIN_IDS", {555}):
        assert runtime.is_authorized_operator(_update(555))


def test_registered_operator_id_grants_operator_access():
    with (
        patch.object(runtime.bot, "ADMIN_IDS", set()),
        patch.object(runtime, "list_operator_ids", return_value=[555]),
    ):
        assert runtime.is_authorized_operator(_update(555))


def test_private_admin_reply_to_request_is_routed_to_operator_handler():
    update = _private_reply_update(555, "🕯 Новая заявка #42")
    with patch.object(runtime.bot, "ADMIN_IDS", {555}):
        assert runtime.is_operator_reply(update)


def test_private_admin_regular_message_is_not_intercepted():
    update = _private_reply_update(555, None)
    with patch.object(runtime.bot, "ADMIN_IDS", {555}):
        assert not runtime.is_operator_reply(update)


def test_common_bot_sender_uses_product_keyboard_factory():
    with patch("premium_subscription.is_premium_active", return_value=True), patch(
        "premium_subscription.is_trial_active", return_value=False
    ):
        labels = {button.text for row in runtime.bot.main_keyboard_for(555).keyboard for button in row}
    assert "🗓 Расклад на год" in labels
    assert "👥 Взаимоотношения" in labels
    assert "📜 Значения рун" in labels
