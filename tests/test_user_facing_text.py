import bot
from premium_subscription import PREMIUM_BENEFITS


def test_help_does_not_advertise_moon_phase():
    assert "лунная фаза" not in bot.short_help().lower()


def test_trial_copy_does_not_claim_every_premium_feature():
    assert "со всеми функциями" not in PREMIUM_BENEFITS.lower()
