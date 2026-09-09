(function () {
    "use strict";

    var storageKey = "velmorax-theme";
    var root = document.documentElement;

    function currentTheme() {
        return root.dataset.theme === "dark" ? "dark" : "light";
    }

    function updateControls() {
        var isDark = currentTheme() === "dark";
        document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
            button.setAttribute("aria-checked", String(isDark));
            button.setAttribute("aria-label", isDark ? "Usar vista clara" : "Usar vista oscura");
        });
        document.querySelectorAll("[data-theme-label]").forEach(function (label) {
            label.textContent = isDark ? "Vista oscura" : "Vista clara";
        });
    }

    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
        button.addEventListener("click", function () {
            var nextTheme = currentTheme() === "dark" ? "light" : "dark";
            root.dataset.theme = nextTheme;
            try {
                localStorage.setItem(storageKey, nextTheme);
            } catch (error) {
                /* The theme still changes for this visit when storage is unavailable. */
            }
            updateControls();
        });
    });

    updateControls();
}());
