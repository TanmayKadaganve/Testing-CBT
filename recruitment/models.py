"""
recruitment/models.py
=====================
All new models for the PyForgeLabs College Interview & Placement Simulator.

Design rules:
- Reuses portal.Student, portal.Exam, portal.Section, portal.Attempt, etc. as-is.
- Never duplicates an existing model.
- Every status transition is recorded in AuditLog.
- CandidateRoundSession stores a server-owned deadline that gates linked portal exam access;
  portal scoring and grading rules remain unchanged.
"""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from portal.models import Student, Exam, Attempt


# ─────────────────────────────────────────────────────────────
#  Recruitment Drive
# ─────────────────────────────────────────────────────────────

class RecruitmentDrive(models.Model):
    """
    One company simulation campaign.
    A drive contains multiple rounds; students are enrolled into a drive,
    not directly into individual rounds.
    """

    STATUS_DRAFT = "DRAFT"
    STATUS_PUBLISHED = "PUBLISHED"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_PAUSED = "PAUSED"
    STATUS_CLOSED = "CLOSED"
    STATUS_ARCHIVED = "ARCHIVED"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_CLOSED, "Closed"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    # Allowed forward transitions (from → to)
    VALID_TRANSITIONS = {
        STATUS_DRAFT: {STATUS_PUBLISHED},
        STATUS_PUBLISHED: {STATUS_ACTIVE, STATUS_DRAFT},
        STATUS_ACTIVE: {STATUS_PAUSED, STATUS_CLOSED},
        STATUS_PAUSED: {STATUS_ACTIVE, STATUS_CLOSED},
        STATUS_CLOSED: {STATUS_ARCHIVED},
        STATUS_ARCHIVED: set(),
    }

    name = models.CharField(max_length=200, help_text="e.g. 'TCS Simulation 2026'")
    company_name = models.CharField(max_length=200, help_text="Simulated employer name")
    role = models.CharField(max_length=200, help_text="e.g. 'Software Engineer'")
    eligibility_criteria = models.TextField(
        blank=True,
        help_text="CGPA, branch, backlogs, batch year, etc.",
    )
    skill_requirements = models.TextField(blank=True)
    instructions = models.TextField(
        blank=True,
        help_text="Shown to enrolled candidates on their dashboard",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True,
    )
    start_date = models.DateField()
    end_date = models.DateField()

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_drives",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Recruitment Drive"
        verbose_name_plural = "Recruitment Drives"

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def can_transition_to(self, new_status):
        return new_status in self.VALID_TRANSITIONS.get(self.status, set())

    def transition_to(self, new_status, actor=None, reason=""):
        """
        Perform a validated status transition and log it.
        Raises ValueError if the transition is not permitted.
        """
        if not self.can_transition_to(new_status):
            raise ValueError(
                f"Cannot transition drive from '{self.status}' to '{new_status}'."
            )
        old_status = self.status
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])
        AuditLog.objects.create(
            action=AuditLog.DRIVE_STATUS_CHANGE,
            actor=actor,
            target_model="RecruitmentDrive",
            target_id=str(self.pk),
            old_value=old_status,
            new_value=new_status,
            reason=reason,
        )
        return self

    @property
    def is_active(self):
        return self.status == self.STATUS_ACTIVE

    @property
    def is_editable(self):
        """A drive is editable only while in DRAFT or PUBLISHED state."""
        return self.status in (self.STATUS_DRAFT, self.STATUS_PUBLISHED)

    @property
    def can_publish(self):
        return self.can_transition_to(self.STATUS_PUBLISHED)

    @property
    def can_activate(self):
        return self.can_transition_to(self.STATUS_ACTIVE)

    @property
    def can_pause(self):
        return self.can_transition_to(self.STATUS_PAUSED)

    @property
    def can_close(self):
        return self.can_transition_to(self.STATUS_CLOSED)

    @property
    def can_archive(self):
        return self.can_transition_to(self.STATUS_ARCHIVED)

    @property
    def ordered_rounds(self):
        return self.rounds.order_by("order")

    @property
    def total_enrolled(self):
        return self.enrollments.count()

    @property
    def total_selected(self):
        return self.enrollments.filter(final_selected=True).count()


# ─────────────────────────────────────────────────────────────
#  Round
# ─────────────────────────────────────────────────────────────

class Round(models.Model):
    """
    One stage in a recruitment drive.
    For MCQ/CODING rounds: link to an existing portal.Exam via `exam` FK.
    For TECHNICAL/BEHAVIORAL/HR rounds: link to an InterviewTemplate.
    """

    TYPE_APTITUDE = "APTITUDE"
    TYPE_CODING = "CODING"
    TYPE_TECHNICAL = "TECHNICAL"
    TYPE_PROJECT = "PROJECT"
    TYPE_BEHAVIORAL = "BEHAVIORAL"
    TYPE_HR = "HR"
    TYPE_CUSTOM = "CUSTOM"

    ROUND_TYPE_CHOICES = [
        (TYPE_APTITUDE, "Aptitude / MCQ"),
        (TYPE_CODING, "Coding / Programming"),
        (TYPE_TECHNICAL, "Technical Interview"),
        (TYPE_PROJECT, "Project Discussion"),
        (TYPE_BEHAVIORAL, "Behavioral Interview"),
        (TYPE_HR, "HR Interview"),
        (TYPE_CUSTOM, "Custom"),
    ]

    # Automated rounds use portal.Exam; human rounds use InterviewTemplate
    AUTO_ROUND_TYPES = {TYPE_APTITUDE, TYPE_CODING}
    HUMAN_ROUND_TYPES = {TYPE_TECHNICAL, TYPE_PROJECT, TYPE_BEHAVIORAL, TYPE_HR, TYPE_CUSTOM}

    drive = models.ForeignKey(
        RecruitmentDrive,
        on_delete=models.CASCADE,
        related_name="rounds",
    )
    name = models.CharField(max_length=200)
    round_type = models.CharField(
        max_length=20,
        choices=ROUND_TYPE_CHOICES,
        db_index=True,
    )
    order = models.PositiveSmallIntegerField(
        default=1,
        help_text="1 = first round. Must be unique within a drive.",
    )
    instructions = models.TextField(blank=True)
    start_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When candidates may begin this round",
    )
    end_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Hard deadline for this round",
    )
    duration_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Maximum time a candidate may spend on this round",
    )

    # Pass / fail configuration
    pass_threshold_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=40,
        help_text="Minimum percentage score required to proceed (e.g. 40.00)",
    )
    score_weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=100,
        help_text="Reserved for reporting; it does not change round cutoffs or final selection.",
    )
    is_mandatory = models.BooleanField(
        default=True,
        help_text="If False, candidates proceed regardless of this round's result",
    )

    # Retry policy
    max_attempts = models.PositiveSmallIntegerField(
        default=1,
        help_text="Set to 1. Candidate round sessions currently support one entry per round.",
    )

    # Integrity
    tab_switch_warning_threshold = models.PositiveSmallIntegerField(
        default=3,
        help_text="Number of tab-switch events before the invigilator is flagged",
    )
    fullscreen_exit_warning_threshold = models.PositiveSmallIntegerField(
        default=2,
        help_text="Number of fullscreen exit events before the invigilator is flagged",
    )
    stale_connection_threshold_seconds = models.PositiveIntegerField(
        default=45,
        help_text="Seconds without heartbeat before marked STALE (default: 45)",
    )

    # Link to portal.Exam for automated rounds
    exam = models.ForeignKey(
        Exam,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recruitment_rounds",
        help_text="For aptitude or coding rounds: the linked portal exam",
    )

    # Link to interview template for human rounds
    interview_template = models.ForeignKey(
        "InterviewTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rounds",
    )

    class Meta:
        ordering = ["drive", "order"]
        unique_together = [("drive", "order")]
        verbose_name = "Round"
        verbose_name_plural = "Rounds"

    def __str__(self):
        return f"{self.drive.name} — Round {self.order}: {self.name}"

    def clean(self):
        super().clean()
        if self.max_attempts != 1:
            raise ValidationError({"max_attempts": "Only one candidate session per round is currently supported."})

    @property
    def is_automated(self):
        return self.round_type in self.AUTO_ROUND_TYPES

    @property
    def is_human_evaluated(self):
        return self.round_type in self.HUMAN_ROUND_TYPES

    @property
    def next_round(self):
        return (
            Round.objects
            .filter(drive=self.drive, order__gt=self.order)
            .order_by("order")
            .first()
        )


# ─────────────────────────────────────────────────────────────
#  Candidate Enrollment
# ─────────────────────────────────────────────────────────────

class CandidateEnrollment(models.Model):
    """
    A Student enrolled in a RecruitmentDrive.
    Tracks the candidate's position and lifecycle within the drive.
    """

    STATUS_REGISTERED = "REGISTERED"
    STATUS_ENROLLED = "ENROLLED"
    STATUS_ELIGIBLE = "ELIGIBLE"
    STATUS_SCHEDULED = "SCHEDULED"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_AWAITING = "AWAITING_EVALUATION"
    STATUS_PASSED = "PASSED"
    STATUS_FAILED = "FAILED"
    STATUS_PROMOTED = "PROMOTED"
    STATUS_REJECTED = "REJECTED"
    STATUS_ABSENT = "ABSENT"
    STATUS_WITHDRAWN = "WITHDRAWN"
    STATUS_ARCHIVED = "ARCHIVED"

    STATUS_CHOICES = [
        ("REGISTERED", "Registered"),
        ("ENROLLED", "Enrolled"),
        ("ELIGIBLE", "Eligible"),
        ("SCHEDULED", "Scheduled"),
        ("IN_PROGRESS", "In Progress"),
        ("AWAITING_EVALUATION", "Awaiting Evaluation"),
        ("PASSED", "Passed"),
        ("FAILED", "Failed"),
        ("PROMOTED", "Promoted"),
        ("REJECTED", "Rejected"),
        ("ABSENT", "Absent"),
        ("WITHDRAWN", "Withdrawn"),
        ("ARCHIVED", "Archived"),
    ]

    # Active statuses — shown in the working candidate roster
    ACTIVE_STATUSES = {
        "REGISTERED", "ENROLLED", "ELIGIBLE",
        "SCHEDULED", "IN_PROGRESS", "AWAITING_EVALUATION",
        "PROMOTED",
    }

    # Terminal statuses — candidate has exited the active pipeline
    TERMINAL_STATUSES = {
        "PASSED", "FAILED", "REJECTED",
        "ABSENT", "WITHDRAWN", "ARCHIVED",
    }

    drive = models.ForeignKey(
        RecruitmentDrive,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    status = models.CharField(
        max_length=25,
        choices=STATUS_CHOICES,
        default=STATUS_ENROLLED,
        db_index=True,
    )
    current_round = models.ForeignKey(
        Round,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_candidates",
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    final_selected = models.BooleanField(
        default=False,
        help_text="True when the candidate is selected at the end of the drive",
    )
    notes = models.TextField(
        blank=True,
        help_text="Internal admin notes — not shown to candidates",
    )

    class Meta:
        unique_together = [("drive", "student")]
        ordering = ["drive", "student__usn"]
        verbose_name = "Candidate Enrollment"
        verbose_name_plural = "Candidate Enrollments"

    def __str__(self):
        return f"{self.student.usn} — {self.drive.name} ({self.get_status_display()})"

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    def set_status(self, new_status, actor=None, reason="", log_action=None):
        """
        Update enrollment status and write an AuditLog entry.
        Use log_action to specify the AuditLog action type; defaults to
        CANDIDATE_PROMOTED or CANDIDATE_REJECTED based on direction.
        """
        old_status = self.status
        self.status = new_status
        self.updated_at = timezone.now()
        self.save(update_fields=["status", "updated_at"])
        if log_action is None:
            if new_status in (self.STATUS_PROMOTED, self.STATUS_PASSED):
                log_action = AuditLog.CANDIDATE_PROMOTED
            elif new_status in (self.STATUS_FAILED, self.STATUS_REJECTED,
                                self.STATUS_ARCHIVED, self.STATUS_WITHDRAWN):
                log_action = AuditLog.CANDIDATE_REJECTED
            else:
                log_action = AuditLog.CANDIDATE_ENROLLED
        AuditLog.objects.create(
            action=log_action,
            actor=actor,
            target_model="CandidateEnrollment",
            target_id=str(self.pk),
            old_value=old_status,
            new_value=new_status,
            reason=reason,
        )


class CandidateRoundSession(models.Model):
    """Server-owned start and hard deadline for one candidate's single round attempt."""
    enrollment = models.ForeignKey(CandidateEnrollment, on_delete=models.CASCADE, related_name="round_sessions")
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="candidate_sessions")
    started_at = models.DateTimeField(default=timezone.now)
    deadline_at = models.DateTimeField()

    class Meta:
        unique_together = [("enrollment", "round")]

    def __str__(self):
        return f"{self.enrollment.student.usn} - {self.round.name}"


# ─────────────────────────────────────────────────────────────
#  Round Result
# ─────────────────────────────────────────────────────────────

class RoundResult(models.Model):
    """
    Server-authoritative result for one candidate in one round.
    Written by the promotion algorithm — never derived from frontend values.
    """

    DECISION_PENDING = "PENDING"
    DECISION_PASS = "PASS"
    DECISION_FAIL = "FAIL"
    DECISION_ABSENT = "ABSENT"
    DECISION_OVERRIDE = "MANUAL_OVERRIDE"

    DECISION_CHOICES = [
        (DECISION_PENDING, "Pending"),
        (DECISION_PASS, "Pass"),
        (DECISION_FAIL, "Fail"),
        (DECISION_ABSENT, "Absent"),
        (DECISION_OVERRIDE, "Manual Override"),
    ]

    enrollment = models.ForeignKey(
        CandidateEnrollment,
        on_delete=models.CASCADE,
        related_name="round_results",
    )
    round = models.ForeignKey(
        Round,
        on_delete=models.CASCADE,
        related_name="results",
    )

    # Link back to the portal.Attempt for automated rounds (nullable for human rounds)
    attempt = models.ForeignKey(
        Attempt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="round_results",
    )

    # Component scores (computed by progression service, never by frontend)
    mcq_score = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    coding_score = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    interview_score = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    total_score = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    max_score = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    decision = models.CharField(
        max_length=20,
        choices=DECISION_CHOICES,
        default=DECISION_PENDING,
        db_index=True,
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    # null = automated decision; set = manual decision by this user
    decided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="round_decisions",
    )
    override_reason = models.TextField(
        blank=True,
        help_text="Mandatory when decision is MANUAL_OVERRIDE",
    )
    override_decision = models.CharField(
        max_length=10,
        choices=[("PASS", "Pass"), ("FAIL", "Fail"), ("ABSENT", "Absent")],
        null=True,
        blank=True,
        help_text="Actual outcome selected by the administrator when decision is MANUAL_OVERRIDE.",
    )
    score_rule_snapshot = models.JSONField(
        default=dict,
        help_text="Snapshot of round scoring config at decision time",
    )

    class Meta:
        unique_together = [("enrollment", "round")]
        ordering = ["enrollment", "round__order"]
        verbose_name = "Round Result"
        verbose_name_plural = "Round Results"
        indexes = [
            models.Index(fields=["decision", "round"]),
            models.Index(fields=["enrollment", "decision"]),
        ]

    def __str__(self):
        return (
            f"{self.enrollment.student.usn} | {self.round.name} → "
            f"{self.display_decision}"
        )

    @property
    def passed(self):
        if self.decision == self.DECISION_OVERRIDE:
            return self.override_decision == self.DECISION_PASS
        return self.decision == self.DECISION_PASS

    @property
    def display_decision(self):
        if self.decision == self.DECISION_OVERRIDE:
            if self.override_decision:
                return f"Manual Override: {self.get_override_decision_display()}"
            return "Manual Override: review historical decision"
        return self.get_decision_display()

    @property
    def outcome_known(self):
        return self.decision != self.DECISION_OVERRIDE or bool(self.override_decision)


# ─────────────────────────────────────────────────────────────
#  Interview Template & Rubric
# ─────────────────────────────────────────────────────────────

class InterviewTemplate(models.Model):
    """
    Reusable set of competency rubrics for a human-evaluated round.
    An admin creates one template per round type; it can be shared
    across multiple rounds in multiple drives.
    """

    name = models.CharField(max_length=200)
    round_type = models.CharField(
        max_length=20,
        choices=Round.ROUND_TYPE_CHOICES,
        db_index=True,
    )
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["round_type", "name"]
        verbose_name = "Interview Template"
        verbose_name_plural = "Interview Templates"

    def __str__(self):
        return f"{self.name} ({self.get_round_type_display()})"

    @property
    def total_max_score(self):
        return sum(c.max_score * c.weight for c in self.criteria.all())


class RubricCriterion(models.Model):
    """
    One evaluable competency in an InterviewTemplate.
    Each criterion has a max score, a weight, and scoring anchors
    that describe what each level looks like.
    """

    template = models.ForeignKey(
        InterviewTemplate,
        on_delete=models.CASCADE,
        related_name="criteria",
    )
    name = models.CharField(
        max_length=200,
        help_text="e.g. 'Problem-solving approach'",
    )
    description = models.TextField(blank=True)
    max_score = models.PositiveSmallIntegerField(
        default=5,
        help_text="Maximum score for this criterion (e.g. 5)",
    )
    weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1,
        help_text="Relative weight when aggregating all criteria scores",
    )
    order = models.PositiveSmallIntegerField(default=1)
    # JSON list: [{"score": 1, "label": "Poor", "description": "..."},  ...]
    anchors_json = models.JSONField(
        default=list,
        help_text="Scoring anchors describing each score level",
    )

    class Meta:
        ordering = ["template", "order"]
        verbose_name = "Rubric Criterion"
        verbose_name_plural = "Rubric Criteria"

    def __str__(self):
        return f"{self.template.name} — {self.name}"


# ─────────────────────────────────────────────────────────────
#  Interview Assignment & Evaluation
# ─────────────────────────────────────────────────────────────

class InterviewAssignment(models.Model):
    """
    Assigns a specific interviewer to interview one candidate for one round.
    One candidate may have multiple assignments if a panel is configured.
    """

    STATUS_SCHEDULED = "SCHEDULED"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    enrollment = models.ForeignKey(
        CandidateEnrollment,
        on_delete=models.CASCADE,
        related_name="interview_assignments",
    )
    round = models.ForeignKey(
        Round,
        on_delete=models.CASCADE,
        related_name="interview_assignments",
    )
    interviewer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="assigned_interviews",
    )
    template = models.ForeignKey(
        InterviewTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
    )
    scheduled_at = models.DateTimeField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_SCHEDULED,
        db_index=True,
    )
    interview_notes = models.TextField(
        blank=True,
        help_text="Private interviewer notes — not shown to candidates",
    )
    # Lock after submission prevents re-scoring without admin action
    is_locked = models.BooleanField(default=False)

    class Meta:
        ordering = ["enrollment", "round", "interviewer"]
        verbose_name = "Interview Assignment"
        verbose_name_plural = "Interview Assignments"
        indexes = [
            models.Index(fields=["interviewer", "status"]),
            models.Index(fields=["round", "status"]),
        ]

    def __str__(self):
        return (
            f"{self.enrollment.student.usn} | {self.round.name} "
            f"— Interviewer: {self.interviewer.get_full_name() or self.interviewer.username}"
        )

    @property
    def weighted_score(self):
        """Returns the weighted total score for this assignment's evaluations."""
        evaluations = list(self.evaluations.select_related("criterion").all())
        if not evaluations:
            return None
        weighted_sum = sum(
            float(e.score) * float(e.criterion.weight) for e in evaluations
        )
        weight_total = sum(float(e.criterion.weight) for e in evaluations)
        if weight_total == 0:
            return 0
        return round(weighted_sum / weight_total, 2)


class InterviewEvaluation(models.Model):
    """
    An interviewer's score for one rubric criterion during an interview.
    One row per criterion per assignment.
    """

    assignment = models.ForeignKey(
        InterviewAssignment,
        on_delete=models.CASCADE,
        related_name="evaluations",
    )
    criterion = models.ForeignKey(
        RubricCriterion,
        on_delete=models.CASCADE,
        related_name="evaluations",
    )
    score = models.PositiveSmallIntegerField(
        help_text="Must be between 0 and criterion.max_score",
    )
    notes = models.TextField(
        blank=True,
        help_text="Evidence or observations for this criterion",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="submitted_evaluations",
    )

    class Meta:
        unique_together = [("assignment", "criterion")]
        ordering = ["assignment", "criterion__order"]
        verbose_name = "Interview Evaluation"
        verbose_name_plural = "Interview Evaluations"

    def __str__(self):
        return (
            f"{self.assignment.enrollment.student.usn} | "
            f"{self.criterion.name} = {self.score}"
        )

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.score > self.criterion.max_score:
            raise ValidationError(
                f"Score {self.score} exceeds max {self.criterion.max_score} "
                f"for criterion '{self.criterion.name}'."
            )


# ─────────────────────────────────────────────────────────────
#  Candidate Presence (Live Connectivity & Activity Tracking)
# ─────────────────────────────────────────────────────────────

class CandidatePresence(models.Model):
    """
    Per-candidate live connectivity and activity tracking.
    Updated in-place on periodic heartbeats and persisted actions.
    Does NOT insert a new row per heartbeat to avoid database bloat.
    """
    STATUS_CONNECTED = "CONNECTED"
    STATUS_STALE = "STALE"
    STATUS_DISCONNECTED = "DISCONNECTED"

    STATUS_CHOICES = [
        (STATUS_CONNECTED, "Connected"),
        (STATUS_STALE, "Stale"),
        (STATUS_DISCONNECTED, "Disconnected"),
    ]

    STALE_THRESHOLD_SECONDS = 45
    DISCONNECTED_THRESHOLD_SECONDS = 120

    enrollment = models.OneToOneField(
        CandidateEnrollment,
        on_delete=models.CASCADE,
        related_name="presence",
    )
    attempt = models.ForeignKey(
        Attempt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="presence_records",
    )
    last_heartbeat = models.DateTimeField(db_index=True)
    last_activity_type = models.CharField(
        max_length=50,
        default="HEARTBEAT",
    )
    last_persisted_at = models.DateTimeField(null=True, blank=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Candidate Presence"
        verbose_name_plural = "Candidate Presence Records"

    def __str__(self):
        return f"{self.enrollment.student.usn} — {self.connection_status} (Last: {self.last_heartbeat:%H:%M:%S})"

    @property
    def seconds_since_heartbeat(self):
        return (timezone.now() - self.last_heartbeat).total_seconds()

    @property
    def connection_status(self):
        delta = self.seconds_since_heartbeat
        stale_limit = getattr(
            self.enrollment.current_round,
            "stale_connection_threshold_seconds",
            self.STALE_THRESHOLD_SECONDS,
        ) or self.STALE_THRESHOLD_SECONDS

        if delta < stale_limit:
            return self.STATUS_CONNECTED
        elif delta < self.DISCONNECTED_THRESHOLD_SECONDS:
            return self.STATUS_STALE
        return self.STATUS_DISCONNECTED

    @property
    def is_online(self):
        return self.connection_status == self.STATUS_CONNECTED


# ─────────────────────────────────────────────────────────────
#  Integrity Events
# ─────────────────────────────────────────────────────────────

class IntegrityEvent(models.Model):
    """
    Records browser-observable exam integrity indicators.

    IMPORTANT: These events are indicators, not proof of misconduct.
    All disciplinary decisions require human review by an authorized admin.
    The browser cannot guarantee that a student has not used a second device,
    external AI tools, or other means not observable by the web page.
    """

    EVENT_TAB_HIDDEN = "TAB_HIDDEN"
    EVENT_FULLSCREEN_EXIT = "FULLSCREEN_EXIT"
    EVENT_DISCONNECT = "DISCONNECT"
    EVENT_RECONNECT = "RECONNECT"
    EVENT_DUPLICATE_LOGIN = "DUPLICATE_LOGIN"
    EVENT_INVIGILATOR_NOTE = "INVIGILATOR_NOTE"
    EVENT_SUBMIT_RATE = "SUBMISSION_RATE_EXCEEDED"
    EVENT_PASTE_DETECTED = "PASTE_DETECTED"
    EVENT_UNSAVED_DRAFT = "UNSAVED_DRAFT"
    EVENT_JOB_TIMEOUT = "JOB_TIMEOUT"
    EVENT_HEARTBEAT_STALE = "HEARTBEAT_STALE"

    EVENT_TYPE_CHOICES = [
        (EVENT_TAB_HIDDEN, "Tab Became Hidden"),
        (EVENT_FULLSCREEN_EXIT, "Fullscreen Exited"),
        (EVENT_DISCONNECT, "Connection Lost"),
        (EVENT_RECONNECT, "Reconnected"),
        (EVENT_DUPLICATE_LOGIN, "Duplicate Login Attempt"),
        (EVENT_INVIGILATOR_NOTE, "Invigilator Note"),
        (EVENT_SUBMIT_RATE, "Submission Rate Exceeded"),
        (EVENT_PASTE_DETECTED, "Paste Detected"),
        (EVENT_UNSAVED_DRAFT, "Unsaved Draft Warning"),
        (EVENT_JOB_TIMEOUT, "Execution Job Timeout"),
        (EVENT_HEARTBEAT_STALE, "Connection Became Stale"),
    ]

    SEVERITY_INFO = "INFO"
    SEVERITY_WARNING = "WARNING"
    SEVERITY_CRITICAL = "CRITICAL"

    SEVERITY_CHOICES = [
        (SEVERITY_INFO, "Info"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_CRITICAL, "Critical"),
    ]

    enrollment = models.ForeignKey(
        CandidateEnrollment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="integrity_events",
    )
    attempt = models.ForeignKey(
        Attempt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="integrity_events",
    )
    round = models.ForeignKey(
        Round,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="integrity_events",
    )
    event_type = models.CharField(
        max_length=30,
        choices=EVENT_TYPE_CHOICES,
        db_index=True,
    )
    severity = models.CharField(
        max_length=10,
        choices=SEVERITY_CHOICES,
        default=SEVERITY_INFO,
        db_index=True,
    )
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    # Non-sensitive context only — never store code, answers, or personal data here
    context = models.JSONField(
        default=dict,
        help_text="Non-sensitive event context (e.g. elapsed time, tab count)",
    )

    # Acknowledgment & Review workflow
    acknowledged = models.BooleanField(default=False, db_index=True)
    acknowledged_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_integrity_events",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    reviewed = models.BooleanField(default=False, db_index=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_integrity_events",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(
        blank=True,
        help_text="Admin's conclusion after reviewing this event",
    )

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = "Integrity Event"
        verbose_name_plural = "Integrity Events"
        indexes = [
            models.Index(fields=["enrollment", "event_type"]),
            models.Index(fields=["reviewed", "event_type"]),
            models.Index(fields=["severity", "reviewed"]),
        ]

    def __str__(self):
        usn = (
            self.enrollment.student.usn
            if self.enrollment
            else "unknown"
        )
        return f"{usn} | [{self.severity}] {self.get_event_type_display()} @ {self.occurred_at:%Y-%m-%d %H:%M}"


# ─────────────────────────────────────────────────────────────
#  Audit Log
# ─────────────────────────────────────────────────────────────

class ImmutableAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise RuntimeError("AuditLog entries are immutable; updates are prohibited.")

    def delete(self):
        raise RuntimeError("AuditLog entries are immutable; deletes are prohibited.")


class ImmutableAuditManager(models.Manager.from_queryset(ImmutableAuditQuerySet)):
    pass


class AuditLog(models.Model):
    """
    Immutable record of significant administrative actions.
    Protected from modification; should not be exposed for editing in admin.
    """

    DRIVE_CREATED = "DRIVE_CREATED"
    DRIVE_STATUS_CHANGE = "DRIVE_STATUS_CHANGE"
    ROUND_PUBLISHED = "ROUND_PUBLISHED"
    CANDIDATE_ENROLLED = "CANDIDATE_ENROLLED"
    CANDIDATE_PROMOTED = "CANDIDATE_PROMOTED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"
    SCORE_OVERRIDE = "SCORE_OVERRIDE"
    MANUAL_PROMOTION = "MANUAL_PROMOTION"
    CANDIDATE_ARCHIVED = "CANDIDATE_ARCHIVED"
    CANDIDATE_DELETED = "CANDIDATE_DELETED"
    EXPORT = "EXPORT"
    INTEGRITY_REVIEW = "INTEGRITY_REVIEW"
    EVALUATION_LOCKED = "EVALUATION_LOCKED"
    EVALUATION_UNLOCKED = "EVALUATION_UNLOCKED"
    INVIGILATOR_NOTE = "INVIGILATOR_NOTE"
    WARNING_ACKNOWLEDGED = "WARNING_ACKNOWLEDGED"

    ACTION_CHOICES = [
        (DRIVE_CREATED, "Drive Created"),
        (DRIVE_STATUS_CHANGE, "Drive Status Change"),
        (ROUND_PUBLISHED, "Round Published"),
        (CANDIDATE_ENROLLED, "Candidate Enrolled"),
        (CANDIDATE_PROMOTED, "Candidate Promoted"),
        (CANDIDATE_REJECTED, "Candidate Rejected"),
        (SCORE_OVERRIDE, "Score Override"),
        (MANUAL_PROMOTION, "Manual Promotion"),
        (CANDIDATE_ARCHIVED, "Candidate Archived"),
        (CANDIDATE_DELETED, "Candidate Deleted"),
        (EXPORT, "Data Export"),
        (INTEGRITY_REVIEW, "Integrity Event Review"),
        (EVALUATION_LOCKED, "Evaluation Locked"),
        (EVALUATION_UNLOCKED, "Evaluation Unlocked"),
        (INVIGILATOR_NOTE, "Invigilator Note"),
        (WARNING_ACKNOWLEDGED, "Warning Acknowledged"),
    ]

    action = models.CharField(
        max_length=30,
        choices=ACTION_CHOICES,
        db_index=True,
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_actions",
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    target_model = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=200, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    objects = ImmutableAuditManager()

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Audit Log Entry"
        verbose_name_plural = "Audit Log"
        indexes = [
            models.Index(fields=["action", "timestamp"]),
            models.Index(fields=["target_model", "target_id"]),
        ]

    def __str__(self):
        actor_name = (
            self.actor.get_full_name() or self.actor.username
            if self.actor else "system"
        )
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.get_action_display()} by {actor_name}"

    # Prevent accidental modification of audit records from code
    def save(self, *args, **kwargs):
        if self.pk:
            raise RuntimeError(
                "AuditLog entries are immutable and cannot be modified. "
                "Create a new entry instead."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError(
            "AuditLog entries cannot be deleted programmatically. "
            "Use database-level archival if retention policy requires removal."
        )
