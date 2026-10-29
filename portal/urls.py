from django.urls import path
from django.views.generic.base import RedirectView
from . import views

urlpatterns = [
    # Candidate CBT Portal Endpoints (Preserved 100%)
    path("", views.login_view, name="login"),
    path("instructions/", views.instructions, name="instructions"),
    path("logout/", views.logout_view, name="logout"),
    path("exam/", views.exam_page, name="exam"),
    path("coding/", views.exam_page, name="coding"),
    path("exam/save/", views.save_answer, name="save_answer"),
    path("exam/submit/", views.submit_exam, name="submit_exam"),
    path("feedback/", views.feedback_page, name="feedback"),
    path("done/", views.done_page, name="done"),
    path("exam/code/save/", views.save_code, name="save_code"),
    path("exam/code/run/", views.code_run, name="code_run"),
    path("exam/code/submit/", views.code_submit, name="code_submit"),
    path("exam/code/job/<uuid:job_id>/", views.code_job_status, name="code_job_status"),

    # Backward-compatible redirects from /dashboard/ to /admin/dashboard/
    path("dashboard/", RedirectView.as_view(url="/admin/dashboard/", permanent=False)),
    path("dashboard/<path:subpath>", RedirectView.as_view(url="/admin/dashboard/%(subpath)s", permanent=False)),
]