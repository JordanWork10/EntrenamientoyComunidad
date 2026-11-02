"""V131.84: auditoría económica transaccional para PostgreSQL.

Copiar como: apps/payments/migrations/0009_economic_audit_v13184.py

El trigger se ejecuta en la misma transacción que el cambio económico. Una
transacción revertida no deja un evento engañoso en el historial.
"""

import sqlparse

from django.db import migrations, models


AUDIT_CAPTURE_SQL = r"""
CREATE OR REPLACE FUNCTION payments_capture_economic_audit_v13184()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    watched text[];
    origin text;
    original_data jsonb := '{}'::jsonb;
    modified_data jsonb := '{}'::jsonb;
    modified_fields jsonb := '[]'::jsonb;
    actor_ref text := '';
    actor_origin text := '';
    original_row jsonb;
    modified_row jsonb;
    target_row jsonb;
BEGIN
    CASE TG_TABLE_NAME
        WHEN 'payments_payment' THEN
            origin := 'payment';
            watched := ARRAY[
                'status', 'economic_scope', 'amount_clp',
                'refunded_amount_clp', 'commission_base_clp',
                'commission_amount_clp', 'net_amount_clp',
                'commission_rate_percent', 'plan_code_snapshot',
                'policy_version', 'settlement_status',
                'settlement_id', 'settlement_eligible_at',
                'settled_at', 'settlement_hold_reason',
                'provider_reference', 'failure_reason'
            ];
        WHEN 'payments_refund' THEN
            origin := 'refund';
            watched := ARRAY[
                'status', 'refund_type', 'reason', 'amount_clp',
                'policy_percentage_snapshot',
                'hours_before_service_snapshot',
                'policy_version_snapshot', 'requested_by_id',
                'resolved_at', 'processed_at', 'provider_reference'
            ];
        WHEN 'payments_settlement' THEN
            origin := 'settlement';
            watched := ARRAY[
                'status', 'scope_type', 'gross_amount_clp',
                'refunded_amount_clp', 'commission_base_clp',
                'commission_amount_clp', 'net_amount_clp',
                'eligible_at', 'settled_at', 'settled_by_id',
                'hold_reason', 'provider_reference'
            ];
        ELSE
            RAISE EXCEPTION 'Origen económico de auditoría no válido';
    END CASE;

    IF TG_OP <> 'INSERT' THEN
        original_row := to_jsonb(OLD);
        SELECT COALESCE(jsonb_object_agg(key, value), '{}'::jsonb)
          INTO original_data
          FROM jsonb_each(original_row)
         WHERE key = ANY(watched);
    END IF;

    IF TG_OP <> 'DELETE' THEN
        modified_row := to_jsonb(NEW);
        SELECT COALESCE(jsonb_object_agg(key, value), '{}'::jsonb)
          INTO modified_data
          FROM jsonb_each(modified_row)
         WHERE key = ANY(watched);
    END IF;

    SELECT COALESCE(jsonb_agg(field_name ORDER BY field_name), '[]'::jsonb)
      INTO modified_fields
      FROM (
          SELECT DISTINCT key AS field_name
            FROM jsonb_object_keys(original_data || modified_data) AS fields(key)
      ) AS key_list
     WHERE original_data -> field_name IS DISTINCT FROM modified_data -> field_name;

    IF TG_OP = 'UPDATE' AND modified_fields = '[]'::jsonb THEN
        RETURN NEW;
    END IF;

    -- El actor se conoce solo cuando lo identifica inequívocamente el dato.
    -- No confundir al pagador o beneficiario con el operador de un cambio.
    IF origin = 'refund' AND TG_OP = 'INSERT' THEN
        actor_ref := COALESCE(modified_row ->> 'requested_by_id', '');
        IF actor_ref <> '' THEN
            actor_origin := 'solicitante';
        END IF;
    ELSIF origin = 'settlement' AND TG_OP = 'UPDATE'
          AND modified_row ->> 'status' = 'settled'
          AND original_row ->> 'status' IS DISTINCT FROM 'settled' THEN
        actor_ref := COALESCE(modified_row ->> 'settled_by_id', '');
        IF actor_ref <> '' THEN
            actor_origin := 'autorizador';
        END IF;
    END IF;

    target_row := CASE
        WHEN TG_OP = 'DELETE' THEN original_row
        ELSE modified_row
    END;

    INSERT INTO payments_economic_audit_event (
        source_type, source_pk, source_public_id, action,
        before_state, after_state, changed_fields,
        actor_identifier, actor_source, occurred_at
    ) VALUES (
        origin,
        (target_row ->> 'id')::bigint,
        (target_row ->> 'public_id')::uuid,
        CASE TG_OP
            WHEN 'INSERT' THEN 'created'
            WHEN 'UPDATE' THEN 'updated'
            ELSE 'deleted'
        END,
        original_data, modified_data, modified_fields,
        actor_ref, actor_origin, clock_timestamp()
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION payments_protect_economic_audit_v13184()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'Los eventos económicos son de solo inserción';
END;
$function$;

CREATE TRIGGER payments_payment_audit_v13184
AFTER INSERT OR UPDATE OR DELETE ON payments_payment
FOR EACH ROW EXECUTE FUNCTION payments_capture_economic_audit_v13184();

CREATE TRIGGER payments_refund_audit_v13184
AFTER INSERT OR UPDATE OR DELETE ON payments_refund
FOR EACH ROW EXECUTE FUNCTION payments_capture_economic_audit_v13184();

CREATE TRIGGER payments_settlement_audit_v13184
AFTER INSERT OR UPDATE OR DELETE ON payments_settlement
FOR EACH ROW EXECUTE FUNCTION payments_capture_economic_audit_v13184();

CREATE TRIGGER payments_audit_immutable_v13184
BEFORE UPDATE OR DELETE ON payments_economic_audit_event
FOR EACH ROW EXECUTE FUNCTION payments_protect_economic_audit_v13184();
"""


AUDIT_REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS payments_payment_audit_v13184 ON payments_payment;
DROP TRIGGER IF EXISTS payments_refund_audit_v13184 ON payments_refund;
DROP TRIGGER IF EXISTS payments_settlement_audit_v13184 ON payments_settlement;
DROP TRIGGER IF EXISTS payments_audit_immutable_v13184
    ON payments_economic_audit_event;
DROP FUNCTION IF EXISTS payments_capture_economic_audit_v13184();
DROP FUNCTION IF EXISTS payments_protect_economic_audit_v13184();
"""


def install_postgres_audit(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            for statement in sqlparse.split(AUDIT_CAPTURE_SQL):
                cursor.execute(statement)


def remove_postgres_audit(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            for statement in sqlparse.split(AUDIT_REVERSE_SQL):
                cursor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [
        ('payments', '0008_professional_day_settlement'),
    ]

    operations = [
        migrations.CreateModel(
            name='EconomicAuditEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                            serialize=False, verbose_name='ID')),
                ('source_type', models.CharField(
                    choices=[('payment', 'Pago'), ('refund', 'Reembolso'),
                             ('settlement', 'Liquidación')], max_length=16)),
                ('source_pk', models.BigIntegerField()),
                ('source_public_id', models.UUIDField()),
                ('action', models.CharField(
                    choices=[('created', 'Creación'), ('updated', 'Actualización'),
                             ('deleted', 'Eliminación')], max_length=12)),
                ('before_state', models.JSONField(default=dict)),
                ('after_state', models.JSONField(default=dict)),
                ('changed_fields', models.JSONField(default=list)),
                ('actor_identifier', models.CharField(blank=True, max_length=120)),
                ('actor_source', models.CharField(blank=True, max_length=30)),
                ('occurred_at', models.DateTimeField()),
            ],
            options={
                'db_table': 'payments_economic_audit_event',
                'verbose_name': 'Evento de auditoría económica',
                'verbose_name_plural': 'Eventos de auditoría económica',
                'ordering': ('-occurred_at', '-id'),
                'indexes': [
                    models.Index(
                        fields=['source_type', 'source_public_id', '-occurred_at'],
                        name='pay_audit_source_13184_idx',
                    ),
                    models.Index(
                        fields=['-occurred_at'],
                        name='pay_audit_time_13184_idx',
                    ),
                ],
            },
        ),
        migrations.RunPython(
            install_postgres_audit,
            reverse_code=remove_postgres_audit,
        ),
    ]
