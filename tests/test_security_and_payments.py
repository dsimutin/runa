from types import SimpleNamespace
from unittest.mock import patch

import product_runtime_final as runtime


def _update(user_id: int, username: str | None = None):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, username=username),
        effective_chat=SimpleNamespace(id=-100123, type="supergroup"),
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
