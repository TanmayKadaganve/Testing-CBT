from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # 1. Canonical Admin Dashboard routes (routed before admin.site.urls catch-all)
    path("admin/dashboard/", include("portal.dashboard_urls")),

    # 2. Django Administration
    path("admin/", admin.site.urls),

    # 3. Recruitment & Placement Simulator
    path("recruitment/", include("recruitment.urls")),

    # 4. Candidate CBT Portal & Backward-Compatible Redirects
    path("", include("portal.urls")),
]
