-- Run this in Supabase SQL Editor (once).
-- Safe to re-run — all statements are idempotent.

-- Drop the placeholder table created by Supabase
DROP TABLE IF EXISTS runa;

CREATE TABLE IF NOT EXISTS users (
    user_id             BIGINT PRIMARY KEY,
    preferred_name      TEXT    NOT NULL DEFAULT 'друг',
    palette             TEXT,
    psychotype          TEXT,
    onboarding_step     INTEGER NOT NULL DEFAULT 0,
    onboarding_score_light    INTEGER NOT NULL DEFAULT 0,
    onboarding_score_dark     INTEGER NOT NULL DEFAULT 0,
    onboarding_score_premium  INTEGER NOT NULL DEFAULT 0,
    broadcast_enabled   INTEGER NOT NULL DEFAULT 1,
    premium_expires_at  TEXT,
    premium_readings_used     INTEGER NOT NULL DEFAULT 0,
    weekly_question_day INTEGER NOT NULL DEFAULT 6
);

CREATE TABLE IF NOT EXISTS daily_runes (
    user_id  BIGINT NOT NULL,
    date     TEXT   NOT NULL,
    main_rune TEXT  NOT NULL,
    aux_rune  TEXT  NOT NULL,
    PRIMARY KEY (user_id, date)
);
