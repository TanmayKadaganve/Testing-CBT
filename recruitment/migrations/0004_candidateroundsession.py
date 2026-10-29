import django.utils.timezone
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("recruitment", "0003_override_outcome_and_score_weight_help")]

    operations = [
        migrations.CreateModel(
            name="CandidateRoundSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("deadline_at", models.DateTimeField()),
                ("enrollment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="round_sessions", to="recruitment.candidateenrollment")),
                ("round", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="candidate_sessions", to="recruitment.round")),
            ],
            options={"unique_together": {("enrollment", "round")}},
        ),
    ]
