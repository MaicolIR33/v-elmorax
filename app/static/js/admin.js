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

    const modal = document.querySelector("[data-admin-confirm-modal]");
    const card = modal?.querySelector(".admin-confirm-card");
    const title = modal?.querySelector("[data-admin-confirm-title]");
    const description = modal?.querySelector("[data-admin-confirm-description]");
    const eyebrow = modal?.querySelector("[data-admin-confirm-eyebrow]");
    const confirmButton = modal?.querySelector("[data-admin-confirm-submit]");
    let pendingForm = null;
    let confirmedForm = null;
    let returnFocus = null;

    function closeConfirmation() {
        if (!modal || modal.classList.contains("is-hidden")) return;
        modal.classList.add("is-hidden");
        document.body.style.overflow = "";
        pendingForm = null;
        if (returnFocus?.isConnected) returnFocus.focus();
        returnFocus = null;
    }

    root.querySelectorAll("form[data-admin-confirm]").forEach((form) => form.addEventListener("submit", (event) => {
        if (form === confirmedForm) {
            confirmedForm = null;
            return;
        }
        event.preventDefault();
        if (!modal || !card || !title || !description || !confirmButton || !eyebrow) return;

        pendingForm = form;
        returnFocus = event.submitter || form.querySelector("button[type='submit']");
        const name = form.dataset.confirmName || "este registro";
        const entity = form.dataset.confirmEntity || "registro";
        const isRestore = form.dataset.confirmMode === "restore";
        const isPermanent = form.dataset.confirmMode === "permanent";
        eyebrow.textContent = isRestore ? "Restaurar acceso" : isPermanent ? "Acción irreversible" : "Eliminación reversible";
        title.textContent = isRestore ? `¿Restaurar ${entity}?` : isPermanent ? `¿Eliminar definitivamente ${entity}?` : `¿Eliminar ${entity}?`;
        description.textContent = (form.dataset.confirmCopy || "Se conservarán los datos relacionados.").replaceAll("{name}", name);
        confirmButton.textContent = form.dataset.confirmSubmit || (isRestore ? "Restaurar" : "Eliminar");
        confirmButton.classList.toggle("vet-delete-confirm", !isRestore);
        modal.classList.remove("is-hidden");
        document.body.style.overflow = "hidden";
        card.focus();
    }));

    modal?.querySelectorAll("[data-admin-confirm-cancel]").forEach((button) => button.addEventListener("click", closeConfirmation));
    confirmButton?.addEventListener("click", () => {
        if (!pendingForm) return;
        const form = pendingForm;
        pendingForm = null;
        confirmedForm = form;
        modal.classList.add("is-hidden");
        document.body.style.overflow = "";
        returnFocus = null;
        form.requestSubmit();
    });
    card?.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            event.preventDefault();
            closeConfirmation();
            return;
        }
        if (event.key !== "Tab") return;
        const focusable = [...card.querySelectorAll("button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])")];
        if (!focusable.length) return;
        if (event.shiftKey && document.activeElement === focusable[0]) {
            event.preventDefault();
            focusable.at(-1).focus();
        } else if (!event.shiftKey && document.activeElement === focusable.at(-1)) {
            event.preventDefault();
            focusable[0].focus();
        }
    });
})();
