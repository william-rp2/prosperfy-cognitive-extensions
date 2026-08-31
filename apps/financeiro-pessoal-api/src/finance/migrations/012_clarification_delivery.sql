-- F2B: clarification delivery/resolution state (PLAN.md decision, SUBAGENT_B).
-- Extends finance_clarifications (migration 003). Does not touch the one-open-per
-- (transaction, question_type) partial unique index, and reuses the existing
-- source_message_id / quoted_message_id columns as the delivery/reply binding.
-- source_message_id = id of the outbound WhatsApp question we sent.
-- quoted_message_id = id of the inbound reply the owner sent quoting it.

ALTER TABLE finance_clarifications ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE finance_clarifications ADD COLUMN delivery_chat_id TEXT;
ALTER TABLE finance_clarifications ADD COLUMN first_delivered_at TEXT;
ALTER TABLE finance_clarifications ADD COLUMN last_delivered_at TEXT;
ALTER TABLE finance_clarifications ADD COLUMN delivery_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE finance_clarifications ADD COLUMN snoozed_until TEXT;
-- resolved_by_actor_id is NOT a new column: migration 003's resolved_by already
-- serves that role (actor id of who resolved it). Reused as-is, not duplicated.

-- Read pattern is "open clarifications ordered by priority/recency for delivery".
CREATE INDEX IF NOT EXISTS ix_finance_clarifications_priority
  ON finance_clarifications(status, priority, created_at);

CREATE INDEX IF NOT EXISTS ix_finance_clarifications_source_message
  ON finance_clarifications(source_message_id);
