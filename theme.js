(function () {
    const SITE_THEME_KEY = "yanniSiteThemeV1";
    const SITE_THEME_COOKIE = "yanniSiteTheme";
    const VALID_THEMES = new Set(["light", "dark"]);
    let themeTransitionTimer = null;

    function isValidTheme(value) {
        return VALID_THEMES.has(value);
    }

    function readThemeFromLocalStorage() {
        try {
            const site = localStorage.getItem(SITE_THEME_KEY);
            return isValidTheme(site) ? site : "";
        } catch (error) {
            return "";
        }
    }

    function readThemeFromCookie() {
        const cookieParts = document.cookie.split(";").map((part) => part.trim());
        const pair = cookieParts.find((item) => item.startsWith(SITE_THEME_COOKIE + "="));
        if (!pair) {
            return "";
        }
        const value = decodeURIComponent(pair.slice((SITE_THEME_COOKIE + "=").length));
        return isValidTheme(value) ? value : "";
    }

    function getPreferredTheme() {
        const prefersDark =
            window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
        return prefersDark ? "dark" : "light";
    }

    function startThemeTransition() {
        document.documentElement.classList.add("theme-transition");
        if (themeTransitionTimer) {
            window.clearTimeout(themeTransitionTimer);
        }
        themeTransitionTimer = window.setTimeout(() => {
            document.documentElement.classList.remove("theme-transition");
            themeTransitionTimer = null;
        }, 220);
    }

    function applyTheme(themeName, animate = false) {
        const safeTheme = isValidTheme(themeName) ? themeName : "light";
        if (animate) {
            startThemeTransition();
        }
        document.documentElement.setAttribute("data-theme", safeTheme);
        document.documentElement.style.colorScheme = safeTheme;
    }

    function persistTheme(themeName) {
        const safeTheme = isValidTheme(themeName) ? themeName : "light";
        try {
            localStorage.setItem(SITE_THEME_KEY, safeTheme);
        } catch (error) {}

        const oneYear = 60 * 60 * 24 * 365;
        document.cookie =
            SITE_THEME_COOKIE +
            "=" +
            encodeURIComponent(safeTheme) +
            "; path=/; max-age=" +
            oneYear +
            "; SameSite=Lax";
    }

    function getCurrentTheme() {
        const current = document.documentElement.getAttribute("data-theme");
        if (isValidTheme(current)) {
            return current;
        }
        return "light";
    }

    function updateToggleLabel(button) {
        if (!button) {
            return;
        }
        const isDark = getCurrentTheme() === "dark";
        button.innerHTML = isDark
            ? '<i class="fas fa-sun" aria-hidden="true"></i>'
            : '<i class="fas fa-moon" aria-hidden="true"></i>';
        const nextLabel = isDark ? "Switch to light mode" : "Switch to dark mode";
        button.setAttribute("aria-label", nextLabel);
        button.setAttribute("title", nextLabel);
    }

    function initThemeToggle(button) {
        if (!button) {
            return;
        }

        updateToggleLabel(button);

        button.addEventListener("click", () => {
            const next = getCurrentTheme() === "dark" ? "light" : "dark";
            applyTheme(next, true);
            persistTheme(next);
            updateToggleLabel(button);
        });

        window.addEventListener("storage", (event) => {
            if (event.key === SITE_THEME_KEY && isValidTheme(event.newValue)) {
                applyTheme(event.newValue, true);
                persistTheme(event.newValue);
                updateToggleLabel(button);
            }
        });
    }

    const initialTheme = readThemeFromLocalStorage() || readThemeFromCookie() || getPreferredTheme();
    applyTheme(initialTheme);
    persistTheme(initialTheme);

    window.SiteTheme = {
        initThemeToggle,
        applyTheme,
        persistTheme,
        getCurrentTheme,
        THEME_KEY: SITE_THEME_KEY
    };
})();
