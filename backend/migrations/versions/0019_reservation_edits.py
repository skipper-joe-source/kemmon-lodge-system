"""Optional historical guest counts and immutable, reasoned booking corrections."""
from alembic import op
revision='0019_reservation_edits'
down_revision='0018_owner_alerts'
branch_labels=None
depends_on=None


def upgrade():
    # NULL preserves the fact that earlier bookings did not record this information.
    op.execute('ALTER TABLE reservations ADD COLUMN guest_count integer CHECK(guest_count BETWEEN 1 AND 100)')
    op.execute('''CREATE TABLE reservation_edits (
        id uuid PRIMARY KEY,reservation_id uuid NOT NULL REFERENCES reservations(id),
        request_hash varchar(64) NOT NULL,changed_by uuid NOT NULL REFERENCES users(id),
        changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),reason varchar(500) NOT NULL CHECK(length(trim(reason))>0),
        before_snapshot jsonb NOT NULL,after_snapshot jsonb NOT NULL,changed_fields jsonb NOT NULL)''')
    op.execute('CREATE INDEX reservation_edits_booking ON reservation_edits(reservation_id,changed_at DESC,id DESC)')
    op.execute('CREATE TRIGGER reservation_edits_keep_history BEFORE UPDATE OR DELETE ON reservation_edits FOR EACH ROW EXECUTE FUNCTION protect_operating_history()')
    op.execute('''CREATE FUNCTION audit_reservation_edit() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE name text;
        BEGIN
            SELECT username INTO name FROM users WHERE id=NEW.changed_by;
            INSERT INTO audit_events(event_at,actor_id,actor_name,action,entity_type,entity_id,source_table,source_key,origin,details)
                VALUES(NEW.changed_at,NEW.changed_by,COALESCE(name,'Not recorded'),'reservation.edited','reservation',NEW.reservation_id::text,
                    TG_TABLE_NAME,NEW.id::text,'live',jsonb_build_object('reason',NEW.reason,'changed_fields',NEW.changed_fields,
                        'before',audit_pick(NEW.before_snapshot,ARRAY['guestCount','checkIn','checkOut','roomNumber','nightlyRate','roomTotal','barCharges','total','paid','balance','credit']),
                        'after',audit_pick(NEW.after_snapshot,ARRAY['guestCount','checkIn','checkOut','roomNumber','nightlyRate','roomTotal','barCharges','total','paid','balance','credit'])));
            RETURN NEW;
        END $$''')
    op.execute('CREATE TRIGGER zz_reservation_edit_audit AFTER INSERT ON reservation_edits FOR EACH ROW EXECUTE FUNCTION audit_reservation_edit()')
    # Keep earlier audit behavior, but use the more detailed edit record for the new API route.
    op.execute('''CREATE OR REPLACE FUNCTION capture_operating_audit() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE actor uuid;name text;prior_count integer;
        BEGIN
            IF TG_TABLE_NAME='reservations' THEN
                IF TG_OP='UPDATE' AND COALESCE(current_setting('kemmon.request_path',true),'') ~ '^/api/reservations/[0-9a-fA-F-]+/edit$' THEN RETURN NEW; END IF;
                PERFORM write_operating_audit(TG_TABLE_NAME,to_jsonb(NEW),CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) ELSE NULL END,'live');
                prior_count=CASE WHEN TG_OP='INSERT' THEN NULL ELSE OLD.guest_count END;
                IF NEW.guest_count IS DISTINCT FROM prior_count THEN
                    actor=NULLIF(current_setting('kemmon.actor_id',true),'')::uuid;
                    SELECT username INTO name FROM users WHERE id=actor;
                    INSERT INTO audit_events(event_at,actor_id,actor_name,action,entity_type,entity_id,source_table,origin,details)
                        VALUES(clock_timestamp(),actor,COALESCE(name,'Not recorded'),'reservation.guest_count_changed','reservation',NEW.id::text,
                            'reservation_guest_counts','live',jsonb_build_object('previous_guest_count',prior_count,'guest_count',NEW.guest_count));
                END IF;
            ELSE
                PERFORM write_operating_audit(TG_TABLE_NAME,to_jsonb(NEW),CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) ELSE NULL END,'live');
            END IF;
            RETURN NEW;
        END $$''')


def downgrade():
    raise RuntimeError('Preserve guest correction history before reverting.')
