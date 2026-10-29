import uuid
from django.db import models


class Student(models.Model):
    usn = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    dob = models.DateField()
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    active_token = models.CharField(max_length=64, blank=True, default="")
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        self.usn = self.usn.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.usn} - {self.name}"


class QueueAdmissionLock(models.Model):
    """Singleton row used to serialize queue admission across app processes."""
    updated_at = models.DateTimeField(auto_now=True)


class Exam(models.Model):
    title = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)
    min_stay_minutes = models.PositiveIntegerField(default=90)
    students = models.ManyToManyField(Student, blank=True)

    def __str__(self):
        return self.title
            
    @property
    def start_time(self):
        first = self.sections.order_by("start_time").first()
        return first.start_time if first else None

    @property
    def end_time(self):
        last = self.sections.order_by("-end_time").first()
        return last.end_time if last else None


class Section(models.Model):
    KIND_CHOICES = [("MCQ", "MCQ"), ("CODING", "Coding")]

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=100)
    order = models.PositiveSmallIntegerField(default=1)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="MCQ")
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    class Meta:
        ordering = ["exam", "order"]

    def __str__(self):
        return f"{self.exam.title} - {self.title}"

class Question(models.Model):
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveSmallIntegerField(default=1)
    text = models.TextField()
    marks = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["section", "order"]

    def __str__(self):
        return f"Q{self.order}: {self.text[:50]}"


class Option(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return self.text


class Attempt(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("student", "exam")

    def __str__(self):
        return f"{self.student.usn} - {self.exam.title}"


class Answer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    selected_option = models.ForeignKey(Option, on_delete=models.SET_NULL, null=True, blank=True)
    marked_for_review = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("attempt", "question")

class Feedback(models.Model):
    attempt = models.OneToOneField(Attempt, on_delete=models.CASCADE)
    experience_rating = models.PositiveSmallIntegerField()
    realism_rating = models.PositiveSmallIntegerField()
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Feedback - {self.attempt}"

class CodingQuestion(models.Model):
    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name="coding_questions"
    )
    order = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=200)
    statement = models.TextField()
    input_format = models.TextField(blank=True)
    output_format = models.TextField(blank=True)
    constraints = models.TextField(blank=True)
    sample_input = models.TextField(blank=True)
    sample_output = models.TextField(blank=True)
    time_limit_seconds = models.PositiveIntegerField(default=2)
    marks = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ["section", "order"]

    def __str__(self):
        return f"{self.order}. {self.title}"


class TestCase(models.Model):
    question = models.ForeignKey(
        CodingQuestion, on_delete=models.CASCADE, related_name="testcases"
    )
    input_data = models.TextField(blank=True)
    expected_output = models.TextField()
    is_sample = models.BooleanField(default=False)
    marks = models.PositiveIntegerField(default=1)

    def __str__(self):
        kind = "sample" if self.is_sample else "hidden"
        return f"{self.question.title} ({kind})"


class CodingQuestionStarterCode(models.Model):
    """Starter / scaffolding code for a CodingQuestion in a specific language."""
    coding_question = models.ForeignKey(
        CodingQuestion, on_delete=models.CASCADE, related_name="starter_codes"
    )
    language = models.CharField(max_length=20)
    code = models.TextField(help_text="Starter code template for this question and language")
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("coding_question", "language")
        ordering = ["coding_question", "language"]
        verbose_name = "Starter Code"
        verbose_name_plural = "Starter Codes"

    def __str__(self):
        return f"{self.coding_question.title} ({self.language})"


class CodeDraft(models.Model):
    """The student's last written code for a question in a specific language (kept when a section locks)."""
    attempt = models.ForeignKey(
        Attempt, on_delete=models.CASCADE, related_name="code_drafts"
    )
    question = models.ForeignKey(CodingQuestion, on_delete=models.CASCADE)
    language = models.CharField(max_length=20, default="python")
    code = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("attempt", "question", "language")
        indexes = [
            models.Index(fields=["attempt", "question", "language"]),
        ]

    def __str__(self):
        return f"{self.attempt.student.usn} - Q{self.question_id} ({self.language})"


class CodeSubmission(models.Model):
    """One row each time the student presses Submit."""
    attempt = models.ForeignKey(
        Attempt, on_delete=models.CASCADE, related_name="code_submissions"
    )
    question = models.ForeignKey(CodingQuestion, on_delete=models.CASCADE)
    language = models.CharField(max_length=20, default="c")
    code = models.TextField()
    verdict = models.CharField(max_length=40, blank=True)
    passed = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    score = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.attempt} - {self.question} - {self.score}"


class CodingQuestionAssignment(models.Model):
    attempt = models.ForeignKey(
        Attempt, on_delete=models.CASCADE, related_name="coding_question_assignments"
    )
    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name="coding_assignments"
    )
    questions = models.ManyToManyField(CodingQuestion, related_name="student_assignments")
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("attempt", "section"),)

    def __str__(self):
        return f"{self.attempt} - {self.section.title} coding questions"


class ExecutionJob(models.Model):
    JOB_KIND_CHOICES = [("RUN", "Run"), ("SUBMIT", "Submit")]
    STATUS_CHOICES = [
        ("QUEUED", "Queued"),
        ("RUNNING", "Running"),
        ("COMPLETED", "Completed"),
        ("FAILED", "Failed"),
        ("TIMED_OUT", "Timed Out"),
        ("CANCELLED", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(
        Attempt, on_delete=models.CASCADE, related_name="execution_jobs"
    )
    question = models.ForeignKey(CodingQuestion, on_delete=models.CASCADE)
    kind = models.CharField(max_length=10, choices=JOB_KIND_CHOICES, default="RUN")
    language = models.CharField(max_length=20, default="python")
    code = models.TextField()
    stdin = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="QUEUED", db_index=True
    )

    verdict = models.CharField(max_length=50, blank=True, default="")
    passed = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    score = models.PositiveIntegerField(default=0)
    stdout = models.TextField(blank=True, default="")
    stderr = models.TextField(blank=True, default="")
    duration_ms = models.FloatField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    test_results_json = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    worker_id = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["attempt", "status"]),
        ]

    def __str__(self):
        return f"{self.kind} Job {self.id} ({self.status}) - {self.attempt.student.usn}"

