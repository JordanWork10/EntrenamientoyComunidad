"""V131.85: atribución segura del operador de un cambio económico.

Copiar como: apps/payments/migrations/0010_economic_actor_context_v13185.py

Reemplaza solo la función de captura de la V131.84, sin recrear triggers ni
alterar el historial. Mantiene la inferencia previa de solicitante/autorizador
cuando no existe un actor autenticado en la transacción.
"""

from importlib import import_module

from django.db import migrations


FUNCTION_START = 'CREATE OR REPLACE FUNCTION payments_capture_economic_audit_v13184()'
FUNCTION_END = 'CREATE OR REPLACE FUNCTION payments_protect_economic_audit_v13184()'
INSERT_BEFORE = '    target_row := CASE\n'

ACTOR_CONTEXT_SQL = """
    -- V131.85: el ID proviene de una petición autenticada, dentro de una
    -- transacción ATOMIC + SET LOCAL. No queda guardado entre conexiones.
    IF NULLIF(current_setting('payments.audit_actor_id', true), '') IS NOT NULL THEN
        actor_ref := current_setting('payments.audit_actor_id', true);
        actor_origin := 'operador_autenticado';
    END IF;

"""


def _previous_function_sql():
    # La V131.84 ya contiene la definición completa del trigger; su archivo
    # es una dependencia permanente en el historial de migraciones.
    previous = import_module('apps.payments.migrations.0009_economic_audit_v13184')
    sql = previous.AUDIT_CAPTURE_SQL
    start = sql.index(FUNCTION_START)
    end = sql.index(FUNCTION_END)
    function_sql = sql[start:end].strip()
    if function_sql.count(INSERT_BEFORE) != 1:
        raise RuntimeError('El origen de la función de auditoría cambió.')
    return function_sql


def apply_actor_context(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    previous_sql = _previous_function_sql()
    updated_sql = previous_sql.replace(
        INSERT_BEFORE,
        ACTOR_CONTEXT_SQL + INSERT_BEFORE,
        1,
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(updated_sql)


def remove_actor_context(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(_previous_function_sql())


class Migration(migrations.Migration):
    dependencies = [
        ('payments', '0009_economic_audit_v13184'),
    ]

    operations = [
        migrations.RunPython(
            apply_actor_context,
            reverse_code=remove_actor_context,
        ),
    ]
