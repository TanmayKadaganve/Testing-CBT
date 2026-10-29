from django.db import migrations, models


def create_singleton(apps, schema_editor):
    Lock = apps.get_model("portal", "QueueAdmissionLock")
    Lock.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("portal", "0008_codingquestionstartercode_and_more")]

    operations = [
        migrations.CreateModel(
            name="QueueAdmissionLock",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.RunPython(create_singleton, migrations.RunPython.noop),
    ]
