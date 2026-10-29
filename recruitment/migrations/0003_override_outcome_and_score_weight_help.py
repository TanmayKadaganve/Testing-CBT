from django.db import migrations, models


def backfill_override_decision(apps, schema_editor):
    Result = apps.get_model("recruitment", "RoundResult")
    Audit = apps.get_model("recruitment", "AuditLog")
    for result in Result.objects.filter(decision="MANUAL_OVERRIDE"):
        entry = Audit.objects.filter(
            action="MANUAL_PROMOTION",
            target_model="RoundResult",
            target_id=str(result.pk),
        ).order_by("-timestamp").first()
        if entry and entry.new_value in {"PASS", "FAIL", "ABSENT"}:
            Result.objects.filter(pk=result.pk).update(override_decision=entry.new_value)


class Migration(migrations.Migration):
    dependencies = [("recruitment", "0002_candidatepresence_integrityevent_acknowledged_and_more")]

    operations = [
        migrations.AddField(
            model_name="roundresult",
            name="override_decision",
            field=models.CharField(blank=True, choices=[("PASS", "Pass"), ("FAIL", "Fail"), ("ABSENT", "Absent")], help_text="Actual outcome selected by the administrator when decision is MANUAL_OVERRIDE.", max_length=10, null=True),
        ),
        migrations.RunPython(backfill_override_decision, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="round",
            name="score_weight",
            field=models.DecimalField(decimal_places=2, default=100, help_text="Reserved for reporting; it does not change round cutoffs or final selection.", max_digits=5),
        ),
        migrations.AlterField(
            model_name="round",
            name="max_attempts",
            field=models.PositiveSmallIntegerField(default=1, help_text="Set to 1. Candidate round sessions currently support one entry per round."),
        ),
    ]
