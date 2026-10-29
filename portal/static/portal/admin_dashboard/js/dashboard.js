/**
 * PyForgeLabs CBT Admin Portal — Interactive Dashboard JS
 * Pure vanilla JavaScript, zero external dependencies
 */

document.addEventListener("DOMContentLoaded", function () {
  // 1. Sidebar Collapse (Desktop)
  const sidebar = document.getElementById("cbtSidebar");
  const collapseBtn = document.getElementById("cbtCollapseBtn");
  const mobileToggleBtn = document.getElementById("cbtMobileToggleBtn");
  const sidebarOverlay = document.getElementById("cbtSidebarOverlay");

  if (sidebar && collapseBtn) {
    const isCollapsed = localStorage.getItem("cbt_sidebar_collapsed") === "true";
    if (isCollapsed) {
      sidebar.classList.add("collapsed");
    }

    collapseBtn.addEventListener("click", function () {
      sidebar.classList.toggle("collapsed");
      localStorage.setItem(
        "cbt_sidebar_collapsed",
        sidebar.classList.contains("collapsed")
      );
    });
  }

  // 2. Mobile Drawer Toggle
  if (sidebar && mobileToggleBtn && sidebarOverlay) {
    mobileToggleBtn.addEventListener("click", function () {
      sidebar.classList.toggle("mobile-open");
    });

    sidebarOverlay.addEventListener("click", function () {
      sidebar.classList.remove("mobile-open");
    });
  }

  // 3. Close mobile drawer on Escape key
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      if (sidebar && sidebar.classList.contains("mobile-open")) {
        sidebar.classList.remove("mobile-open");
      }
      closeUserDropdown();
    }
  });

  // 4. User Profile Dropdown
  const userProfile = document.getElementById("cbtUserProfile");
  const userDropdown = document.getElementById("cbtUserDropdown");

  function closeUserDropdown() {
    if (userDropdown) {
      userDropdown.classList.remove("open");
    }
  }

  if (userProfile && userDropdown) {
    userProfile.addEventListener("click", function (e) {
      e.stopPropagation();
      userDropdown.classList.toggle("open");
    });

    document.addEventListener("click", function (e) {
      if (!userProfile.contains(e.target)) {
        closeUserDropdown();
      }
    });
  }

  // 5. Destructive Action Confirmation
  document.querySelectorAll("[data-confirm]").forEach(function (element) {
    element.addEventListener("click", function (e) {
      const message = this.getAttribute("data-confirm") || "Are you sure you want to proceed?";
      if (!confirm(message)) {
        e.preventDefault();
      }
    });
  });

  // 6. Dismiss Alert Messages
  document.querySelectorAll(".cbt-alert-dismiss").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const alert = this.closest(".cbt-alert");
      if (alert) {
        alert.style.opacity = "0";
        setTimeout(function () {
          alert.remove();
        }, 200);
      }
    });
  });

  // 7. Dynamic Chart Bar and Progress Width Initializers
  document.querySelectorAll(".cbt-bar-fill[data-height]").forEach(function (el) {
    const val = el.getAttribute("data-height");
    if (val !== null) {
      el.style.height = val + "%";
    }
  });

  document.querySelectorAll(".cbt-progress-fill[data-width]").forEach(function (el) {
    const val = el.getAttribute("data-width");
    if (val !== null) {
      el.style.width = val + "%";
    }
  });
});
