from django import template
from django.apps import apps
from portal.services.dashboard_analytics import get_overview_metrics, get_data_integrity_report
from portal.models import Exam

register = template.Library()


@register.simple_tag
def get_cbt_admin_metrics():
    """Returns overview summary metrics from the database."""
    return get_overview_metrics()


@register.simple_tag
def get_model_count(app_label, model_name):
    """Safely retrieves live record count for a given app model."""
    try:
        model = apps.get_model(app_label, model_name)
        return model.objects.count()
    except Exception:
        return 0


@register.simple_tag
def get_cbt_integrity_alerts():
    """Returns genuine configuration and integrity alerts from the database."""
    try:
        return get_data_integrity_report()[:5]
    except Exception:
        return []


@register.simple_tag
def get_cbt_active_exams():
    """Returns recent configured exams with section and student counts."""
    try:
        return Exam.objects.prefetch_related("sections", "students").order_by("-id")[:5]
    except Exception:
        return []
