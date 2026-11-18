(() => {
    const root = document.querySelector("[data-admin-module]");
    if (!root) return;
    root.classList.add("admin-js-ready");
    const tabs = [...root.querySelectorAll("[data-admin-tab]")];
    const panels = [...root.querySelectorAll(".admin-tab-panel")];
    function activateTab(id, focus = false) {
        tabs.forEach((tab) => {
            const active = tab.dataset.adminTab === id;
            tab.setAttribute("aria-selected", String(active));
            tab.tabIndex = active ? 0 : -1;
            if (active && focus) tab.focus();
        });
        panels.forEach((panel) => { panel.hidden = panel.id !== id; });
    }
    tabs.forEach((tab, index) => {
        tab.addEventListener("click", () => activateTab(tab.dataset.adminTab));
        tab.addEventListener("keydown", (event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
            activateTab(tabs[next].dataset.adminTab, true);
        });
    });
    const selected = new URLSearchParams(location.search).get("panel");
    if (selected && panels.some((panel) => panel.id === selected)) activateTab(selected);
    root.querySelectorAll("[data-open-form]").forEach((button) => button.addEventListener("click", () => {
        const form = document.getElementById(button.dataset.openForm);
        if (!form) return;
        form.hidden = !form.hidden;
        if (!form.hidden) form.querySelector("input")?.focus();
    }));
    root.querySelectorAll("form[data-confirm]").forEach((form) => form.addEventListener("submit", (event) => {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    }));
})();
