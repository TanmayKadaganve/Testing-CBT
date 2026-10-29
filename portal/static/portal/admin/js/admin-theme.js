/**
 * PyForgeLabs CBT Admin Portal — Interactive Admin Theme JS
 */

document.addEventListener("DOMContentLoaded", function () {
  // 1. Highlight active navigation item in the persistent left sidebar
  const currentPath = window.location.pathname;
  const navLinks = document.querySelectorAll(".pf-nav-link, .cbt-admin-nav-link");

  let bestMatch = null;
  let bestMatchLength = 0;

  navLinks.forEach(function (link) {
    const href = link.getAttribute("href");
    if (!href) return;

    if (currentPath === href) {
      bestMatch = link;
      bestMatchLength = 9999;
    } else if (href !== "/admin/" && href !== "/admin/dashboard/" && currentPath.startsWith(href)) {
      if (href.length > bestMatchLength) {
        bestMatch = link;
        bestMatchLength = href.length;
      }
    }
  });

  if (bestMatch) {
    bestMatch.classList.add("active");
  } else if (currentPath === "/admin/") {
    // If exact admin home, highlight Admin Home link
    navLinks.forEach(function (link) {
      if (link.getAttribute("href") === "/admin/") {
        link.classList.add("active");
      }
    });
  }

  // 2. Mobile drawer and desktop collapse toggle for admin sidebar
  const mobileToggle = document.getElementById("pfMobileToggleBtn") || document.getElementById("cbtMobileToggleBtn") || document.getElementById("cbtAdminMobileToggle");
  const sidebar = document.getElementById("cbtSidebar") || document.getElementById("pfAdminSidebar") || document.getElementById("cbtAdminSidebar");
  const overlay = document.getElementById("pfAdminSidebarOverlay") || document.getElementById("cbtSidebarOverlay");
  const collapseBtn = document.getElementById("cbtCollapseBtn") || document.getElementById("pfCollapseBtn");

  if (sidebar && collapseBtn) {
    const isCollapsed = localStorage.getItem("cbt_sidebar_collapsed") === "true";
    if (isCollapsed) {
      sidebar.classList.add("collapsed");
      document.body.classList.add("sidebar-collapsed");
    }

    collapseBtn.addEventListener("click", function () {
      sidebar.classList.toggle("collapsed");
      document.body.classList.toggle("sidebar-collapsed");
      localStorage.setItem("cbt_sidebar_collapsed", sidebar.classList.contains("collapsed"));
    });
  }

  function openSidebar() {
    if (sidebar) sidebar.classList.add("mobile-open");
    if (overlay) overlay.classList.add("active");
    document.body.style.overflow = "hidden";
  }

  function closeSidebar() {
    if (sidebar) sidebar.classList.remove("mobile-open");
    if (overlay) overlay.classList.remove("active");
    document.body.style.overflow = "";
  }

  if (mobileToggle && sidebar) {
    mobileToggle.addEventListener("click", function (e) {
      e.stopPropagation();
      if (sidebar.classList.contains("mobile-open")) {
        closeSidebar();
      } else {
        openSidebar();
      }
    });
  }

  if (overlay) {
    overlay.addEventListener("click", closeSidebar);
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && sidebar && sidebar.classList.contains("mobile-open")) {
      closeSidebar();
    }
  });

  // 3. File Input Interactive Feedback on Import Pages
  const fileInputs = document.querySelectorAll('.pf-file-dropzone input[type="file"], .form-row input[type="file"], .module input[type="file"]');
  fileInputs.forEach(function (input) {
    input.addEventListener("change", function () {
      const dropzone = input.closest(".pf-file-dropzone");
      if (input.files && input.files[0]) {
        const file = input.files[0];
        const fileSize = (file.size / 1024).toFixed(1) + " KB";
        let feedbackEl = dropzone ? dropzone.querySelector(".pf-file-selected-name") : null;
        
        if (!feedbackEl && dropzone) {
          feedbackEl = document.createElement("div");
          feedbackEl.className = "pf-file-selected-name";
          dropzone.appendChild(feedbackEl);
        }
        
        if (feedbackEl) {
          feedbackEl.innerHTML = `&#10003; <strong>${file.name}</strong> (${fileSize})`;
          feedbackEl.style.display = "inline-block";
        }
      }
    });
  });
});
