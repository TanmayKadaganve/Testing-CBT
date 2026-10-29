from django.urls import path
from django.contrib import admin
from . import dashboard_views

# Wrap each view with admin.site.admin_view for native Django Admin staff authorization
def admin_view(view_func):
    return admin.site.admin_view(view_func)

urlpatterns = [
    path("", admin_view(dashboard_views.dashboard_overview), name="dashboard_overview"),
    path("students/", admin_view(dashboard_views.dashboard_students), name="dashboard_students"),
    path("students/<int:student_id>/", admin_view(dashboard_views.student_detail), name="student_detail"),
    path("students/<int:student_id>/toggle-active/", admin_view(dashboard_views.toggle_student_active), name="toggle_student_active"),
    path("students/<int:student_id>/reset-login/", admin_view(dashboard_views.reset_student_login), name="reset_student_login"),
    path("exams/", admin_view(dashboard_views.dashboard_exams), name="dashboard_exams"),
    path("questions/", admin_view(dashboard_views.dashboard_questions), name="dashboard_questions"),
    path("coding/", admin_view(dashboard_views.dashboard_coding), name="dashboard_coding"),
    path("attempts/", admin_view(dashboard_views.dashboard_attempts), name="dashboard_attempts"),
    path("submissions/", admin_view(dashboard_views.dashboard_submissions), name="dashboard_submissions"),
    path("feedback/", admin_view(dashboard_views.dashboard_feedback), name="dashboard_feedback"),
    path("health/", admin_view(dashboard_views.dashboard_health), name="dashboard_health"),
    path("performance/", admin_view(dashboard_views.dashboard_performance), name="dashboard_performance"),
    path("integrity/", admin_view(dashboard_views.dashboard_integrity), name="dashboard_integrity"),
]
