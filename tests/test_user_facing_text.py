import bot
import human_reading
import product_runtime_final
from premium_subscription import PREMIUM_BENEFITS


def test_help_does_not_advertise_moon_phase():
    assert "лунная фаза" not in bot.short_help().lower()


def test_payment_details_use_compact_copyable_format():
    assert "<pre>" not in human_reading.HUMAN_READING_TEXT
    assert "<code>5536 9141 3069 4684</code>" in human_reading.HUMAN_READING_TEXT
    assert "<code>+7 999 221-86-89</code>" in human_reading.HUMAN_READING_TEXT

    premium_text = product_runtime_final.premium_card_payment_text()
    assert "<pre>" not in premium_text
    assert "<code>5536 9141 3069 4684</code>" in premium_text
    assert "<code>+7 999 221-86-89</code>" in premium_text


def test_trial_copy_does_not_claim_every_premium_feature():
    assert "со всеми функциями" not in PREMIUM_BENEFITS.lower()
