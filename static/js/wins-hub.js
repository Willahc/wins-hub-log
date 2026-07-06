document.addEventListener("DOMContentLoaded", function () {
  const sidebar = document.getElementById("appSidebar");
  const toggleBtn = document.getElementById("toggleSidebarBtn");
  const closeBtn = document.getElementById("closeSidebarBtn");
  let backdrop = document.getElementById("sidebarBackdrop");

  // Criar o backdrop se ele não existir e estivermos no mobile
  if (!backdrop) {
    backdrop = document.createElement("div");
    backdrop.id = "sidebarBackdrop";
    backdrop.className = "sidebar-backdrop";
    document.body.appendChild(backdrop);
  }

  function openSidebar() {
    if (sidebar) sidebar.classList.add("show");
    if (backdrop) backdrop.classList.add("show");
  }

  function closeSidebar() {
    if (sidebar) sidebar.classList.remove("show");
    if (backdrop) backdrop.classList.remove("show");
  }

  if (toggleBtn) {
    toggleBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      openSidebar();
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", closeSidebar);
  }

  if (backdrop) {
    backdrop.addEventListener("click", closeSidebar);
  }

  // Prevenir fechamento se clicar de dentro da sidebar
  if (sidebar) {
    sidebar.addEventListener("click", function (e) {
      e.stopPropagation();
    });
  }
});
