(function () {
    const topbar = document.querySelector(".topbar");
    const toggleButton = document.getElementById("themeToggle");

    function updateHeaderOffset() {
        if (!topbar) {
            return;
        }
        const offset = Math.ceil(topbar.getBoundingClientRect().height) + 10;
        document.documentElement.style.setProperty("--header-offset", offset + "px");
    }

    function setupAutoHideTopbar() {
        if (!topbar) {
            return;
        }

        let previousY = window.scrollY;
        window.addEventListener(
            "scroll",
            function () {
                const currentY = window.scrollY;
                const movingDown = currentY > previousY + 6;
                const movingUp = currentY < previousY - 6;

                if (currentY < 16 || movingUp) {
                    topbar.classList.remove("is-hidden");
                } else if (movingDown && currentY > topbar.offsetHeight + 24) {
                    topbar.classList.add("is-hidden");
                }

                previousY = currentY;
            },
            { passive: true }
        );
    }

    function initThemeToggle() {
        if (window.SiteTheme && window.SiteTheme.initThemeToggle) {
            window.SiteTheme.initThemeToggle(toggleButton);
            return;
        }
    }

    updateHeaderOffset();
    window.addEventListener("resize", updateHeaderOffset);
    setupAutoHideTopbar();
    initThemeToggle();
})();
