/* Pokémon merchandise catalogue — search, species filter, image grid, click for details. */
(function () {
    var DATA_URL = "collection.json";
    var IMAGES_BASE = "images/";

    var state = {
        items: [],
        species: [],
        query: "",
        speciesFilter: "all",
        updatedAt: null,
        activeItem: null
    };

    var modalRoot = null;
    var lastFocused = null;
    var modalFullLoader = null;

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) {
            node.className = className;
        }
        if (text != null) {
            node.textContent = text;
        }
        return node;
    }

    function normalize(value) {
        return String(value || "")
            .toLowerCase()
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "");
    }

    function speciesLabel(id) {
        var match = state.species.find(function (entry) {
            return entry.id === id;
        });
        return match ? match.label : id || "Others";
    }

    function itemSpeciesIds(item) {
        var raw = item && item.species;
        if (Array.isArray(raw)) {
            return raw.filter(Boolean);
        }
        if (raw) {
            return [raw];
        }
        return ["other"];
    }

    function speciesLabels(item) {
        return itemSpeciesIds(item)
            .map(speciesLabel)
            .join(", ");
    }

    function formatUpdatedAt(iso) {
        if (!iso) {
            return "not synced yet";
        }
        var date = new Date(iso);
        if (Number.isNaN(date.getTime())) {
            return iso;
        }
        return date.toLocaleDateString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric"
        });
    }

    function itemHaystack(item) {
        return normalize(
            [
                item.name,
                item.source,
                item.notes,
                itemSpeciesIds(item).join(" "),
                speciesLabels(item),
                (item.tags || []).join(" ")
            ].join(" ")
        );
    }

    function imageUrl(relativePath) {
        return IMAGES_BASE + String(relativePath || "").replace(/^\//, "");
    }

    function thumbPath(item) {
        if (item.imageThumb) {
            return item.imageThumb;
        }
        if (!item.image) {
            return null;
        }
        var parts = String(item.image).split("/");
        return "thumbs/" + parts[parts.length - 1].replace(/\.[^.]+$/, ".jpg");
    }

    function filteredItems() {
        var query = normalize(state.query.trim());
        return state.items.filter(function (item) {
            if (
                state.speciesFilter !== "all" &&
                itemSpeciesIds(item).indexOf(state.speciesFilter) === -1
            ) {
                return false;
            }
            if (!query) {
                return true;
            }
            return itemHaystack(item).indexOf(query) !== -1;
        });
    }

    function buildToolbar(mount) {
        mount.textContent = "";

        var searchWrap = el("div", "jp-toolbar-search");
        var searchIcon = el("i", "fa-solid fa-magnifying-glass");
        searchIcon.setAttribute("aria-hidden", "true");
        var searchInput = el("input", "jp-search-input");
        searchInput.type = "search";
        searchInput.id = "jp-search";
        searchInput.placeholder = "Search name, source, notes…";
        searchInput.autocomplete = "off";
        searchInput.value = state.query;
        searchInput.addEventListener("input", function () {
            state.query = searchInput.value;
            renderGrid(document.getElementById("jp-grid"));
            renderStatus(document.getElementById("jp-status"));
        });
        searchWrap.appendChild(searchIcon);
        searchWrap.appendChild(searchInput);
        mount.appendChild(searchWrap);

        var filters = el("div", "jp-filters");
        filters.setAttribute("role", "group");
        filters.setAttribute("aria-label", "Filter by Pokémon species");

        function addFilterChip(id, label) {
            var btn = el("button", "jp-filter-chip", label);
            btn.type = "button";
            btn.dataset.species = id;
            if (state.speciesFilter === id) {
                btn.classList.add("is-active");
                btn.setAttribute("aria-pressed", "true");
            } else {
                btn.setAttribute("aria-pressed", "false");
            }
            btn.addEventListener("click", function () {
                state.speciesFilter = id;
                renderToolbar(mount);
                renderGrid(document.getElementById("jp-grid"));
                renderStatus(document.getElementById("jp-status"));
            });
            filters.appendChild(btn);
        }

        addFilterChip("all", "All");
        state.species.forEach(function (entry) {
            addFilterChip(entry.id, entry.label);
        });
        mount.appendChild(filters);
    }

    function renderToolbar(mount) {
        if (!mount) {
            return;
        }
        buildToolbar(mount);
    }

    function renderStatus(mount) {
        if (!mount) {
            return;
        }
        var visible = filteredItems().length;
        var total = state.items.length;
        mount.textContent =
            visible === total
                ? visible +
                  (visible === 1 ? " item" : " items") +
                  " · click an image for details · updated " +
                  formatUpdatedAt(state.updatedAt)
                : "Showing " +
                  visible +
                  " of " +
                  total +
                  " · click an image for details · updated " +
                  formatUpdatedAt(state.updatedAt);
    }

    function buildImageFallback(name) {
        var fallback = el("span", "jp-card-fallback");
        fallback.textContent =
            String(name || "?")
                .trim()
                .charAt(0)
                .toUpperCase() || "?";
        fallback.setAttribute("aria-hidden", "true");
        return fallback;
    }

    function appendGridImage(parent, item) {
        if (!item.image) {
            parent.appendChild(buildImageFallback(item.name));
            return;
        }

        var thumb = thumbPath(item);
        var full = item.image;
        var img = el("img", "jp-card-image");
        img.alt = "";
        img.loading = "lazy";
        img.decoding = "async";
        img.fetchPriority = "low";
        img.src = imageUrl(thumb || full);

        img.onerror = function () {
            if (thumb && img.src.indexOf("/thumbs/") !== -1) {
                img.onerror = function () {
                    img.onerror = null;
                    img.replaceWith(buildImageFallback(item.name));
                };
                img.src = imageUrl(full);
                return;
            }
            img.onerror = null;
            img.replaceWith(buildImageFallback(item.name));
        };

        parent.appendChild(img);
    }

    function appendModalImage(parent, item) {
        if (modalFullLoader) {
            modalFullLoader.onload = null;
            modalFullLoader.onerror = null;
            modalFullLoader = null;
        }

        if (!item.image) {
            parent.appendChild(buildImageFallback(item.name));
            return;
        }

        var thumb = thumbPath(item);
        var full = item.image;
        var img = el("img", "jp-modal-image");
        img.alt = "";
        img.decoding = "async";
        parent.classList.toggle("is-loading-full", Boolean(thumb));

        if (thumb) {
            img.src = imageUrl(thumb);
            img.classList.add("is-preview");
            modalFullLoader = new Image();
            modalFullLoader.onload = function () {
                img.src = imageUrl(full);
                img.classList.remove("is-preview");
                parent.classList.remove("is-loading-full");
                modalFullLoader = null;
            };
            modalFullLoader.onerror = function () {
                parent.classList.remove("is-loading-full");
                modalFullLoader = null;
            };
            modalFullLoader.src = imageUrl(full);
        } else {
            img.src = imageUrl(full);
        }

        img.onerror = function () {
            img.onerror = null;
            parent.classList.remove("is-loading-full");
            img.replaceWith(buildImageFallback(item.name));
        };

        parent.appendChild(img);
    }

    function buildCard(item) {
        var card = el("button", "jp-card");
        card.type = "button";
        card.setAttribute("data-species", itemSpeciesIds(item).join(" "));
        card.setAttribute("aria-label", "View details for " + (item.name || "item"));

        var media = el("div", "jp-card-media");
        appendGridImage(media, item);
        card.appendChild(media);

        card.addEventListener("click", function () {
            openModal(item, card);
        });

        return card;
    }

    function addDetailRow(list, label, value) {
        if (!value) {
            return;
        }
        var row = el("div", "jp-detail-row");
        row.appendChild(el("dt", "jp-detail-label", label));
        row.appendChild(el("dd", "jp-detail-value", value));
        list.appendChild(row);
    }

    function ensureModal() {
        if (modalRoot) {
            return modalRoot;
        }

        modalRoot = el("div", "jp-modal");
        modalRoot.id = "jp-modal";
        modalRoot.setAttribute("aria-hidden", "true");

        var backdrop = el("button", "jp-modal-backdrop");
        backdrop.type = "button";
        backdrop.setAttribute("aria-label", "Close details");
        backdrop.addEventListener("click", closeModal);

        var dialog = el("div", "jp-modal-dialog");
        dialog.setAttribute("role", "dialog");
        dialog.setAttribute("aria-modal", "true");
        dialog.setAttribute("aria-labelledby", "jp-modal-title");

        var closeBtn = el("button", "jp-modal-close");
        closeBtn.type = "button";
        closeBtn.setAttribute("aria-label", "Close details");
        closeBtn.innerHTML = '<i class="fa-solid fa-xmark" aria-hidden="true"></i>';
        closeBtn.addEventListener("click", closeModal);

        var media = el("div", "jp-modal-media");
        media.id = "jp-modal-media";

        var body = el("div", "jp-modal-body");
        var title = el("h3", "jp-modal-title");
        title.id = "jp-modal-title";
        var list = el("dl", "jp-detail-list");
        list.id = "jp-modal-details";

        body.appendChild(title);
        body.appendChild(list);

        dialog.appendChild(closeBtn);
        dialog.appendChild(media);
        dialog.appendChild(body);

        modalRoot.appendChild(backdrop);
        modalRoot.appendChild(dialog);
        document.body.appendChild(modalRoot);

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && modalRoot.classList.contains("is-open")) {
                closeModal();
            }
        });

        return modalRoot;
    }

    function openModal(item, trigger) {
        state.activeItem = item;
        lastFocused = trigger || document.activeElement;

        var modal = ensureModal();
        var media = document.getElementById("jp-modal-media");
        var title = document.getElementById("jp-modal-title");
        var list = document.getElementById("jp-modal-details");

        media.textContent = "";
        appendModalImage(media, item);

        title.textContent = item.name || "Untitled item";
        list.textContent = "";
        addDetailRow(list, "Species", speciesLabels(item));
        addDetailRow(list, "Source", item.source);
        addDetailRow(list, "Notes", item.notes);

        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("jp-modal-open");

        var closeBtn = modal.querySelector(".jp-modal-close");
        if (closeBtn) {
            closeBtn.focus();
        }
    }

    function closeModal() {
        if (!modalRoot) {
            return;
        }
        if (modalFullLoader) {
            modalFullLoader.onload = null;
            modalFullLoader.onerror = null;
            modalFullLoader = null;
        }
        modalRoot.classList.remove("is-open");
        modalRoot.setAttribute("aria-hidden", "true");
        document.body.classList.remove("jp-modal-open");
        state.activeItem = null;
        if (lastFocused && typeof lastFocused.focus === "function") {
            lastFocused.focus();
        }
    }

    function renderGrid(mount) {
        if (!mount) {
            return;
        }
        mount.textContent = "";
        var items = filteredItems();

        if (!items.length) {
            var empty = el("div", "jp-empty");
            if (state.items.length === 0) {
                empty.appendChild(el("p", "jp-empty-title", "Catalogue is empty for now."));
                empty.appendChild(
                    el(
                        "p",
                        "jp-empty-copy",
                        "New items appear here after they are submitted on the Google Form and synced to the site."
                    )
                );
            } else {
                empty.appendChild(el("p", "jp-empty-title", "No matches."));
                empty.appendChild(
                    el("p", "jp-empty-copy", "Try another search term or reset the species filter.")
                );
            }
            mount.appendChild(empty);
            return;
        }

        var grid = el("div", "jp-grid");
        grid.setAttribute("role", "list");
        items.forEach(function (item) {
            var card = buildCard(item);
            card.setAttribute("role", "listitem");
            grid.appendChild(card);
        });
        mount.appendChild(grid);
    }

    function boot(data) {
        state.species = Array.isArray(data.species) ? data.species : [];
        state.items = Array.isArray(data.items) ? data.items : [];
        state.updatedAt = data.updatedAt || null;

        renderToolbar(document.getElementById("jp-toolbar"));
        renderStatus(document.getElementById("jp-status"));
        renderGrid(document.getElementById("jp-grid"));
    }

    function showLoadError(mount, message) {
        if (!mount) {
            return;
        }
        mount.textContent = "";
        var box = el("div", "jp-empty");
        box.appendChild(el("p", "jp-empty-title", "Could not load catalogue."));
        box.appendChild(el("p", "jp-empty-copy", message));
        mount.appendChild(box);
    }

    fetch(DATA_URL)
        .then(function (response) {
            if (!response.ok) {
                throw new Error("HTTP " + response.status);
            }
            return response.json();
        })
        .then(boot)
        .catch(function (error) {
            showLoadError(document.getElementById("jp-grid"), String(error.message || error));
        });
})();
