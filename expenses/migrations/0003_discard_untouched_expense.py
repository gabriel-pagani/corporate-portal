from django.db import migrations


# O histórico continua sem alteração nem exclusão, com uma exceção: o funcionário
# exclui a despesa que ninguém tratou ainda, e com ela vai o registro do envio.
# A exclusão marca na transação qual despesa sai (expenses.discarding_expense), e
# o banco só deixa apagar o registro de envio dessa despesa; qualquer outro
# registro, ou fora dessa marcação, continua recusado.
ALLOW_DISCARD = """
CREATE OR REPLACE FUNCTION expenses_event_immutable() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.action = 'submit'
       AND OLD.expense_id::text = current_setting('expenses.discarding_expense', true) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'O histórico da nota não pode ser alterado nem apagado.';
END;
$$ LANGUAGE plpgsql;
"""

IMMUTABLE_ONLY = """
CREATE OR REPLACE FUNCTION expenses_event_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'O histórico da nota não pode ser alterado nem apagado.';
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0002_alter_expenseevent_action_and_more'),
    ]

    operations = [
        migrations.RunSQL(ALLOW_DISCARD, IMMUTABLE_ONLY),
    ]
