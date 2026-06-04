(function () {
    "use strict";

    const CARD_IMAGE_SELECTOR = [
        ".service-card img",
        ".project-card img",
        ".pr-card img",
        ".life-card img",
        ".org-card img",
        ".cert-item > img",
        ".cap-card img",
        ".feat-card img",
        ".benefit-card img",
        ".value-card img",
        ".expertise-card img",
        ".mv-card img",
        ".stat-card img",
        ".info-card img",
        ".owner-approval-card img",
        ".contact-card img",
        ".map-card img",
        ".iso-cert-card img",
        ".card-image img",
        "[class*='-card'] img"
    ].join(",");

    const EXCLUDED_CONTAINER_SELECTOR = [
        ".petroraq-header",
        ".petroraq-footer",
        ".cert-preview-modal",
        ".prq-image-lightbox",
        ".modal",
        ".o_dialog"
    ].join(",");

    function createLightbox() {
        let lightbox = document.getElementById("prqImageLightbox");
        if (lightbox) {
            return lightbox;
        }

        lightbox = document.createElement("div");
        lightbox.id = "prqImageLightbox";
        lightbox.className = "prq-image-lightbox";
        lightbox.setAttribute("aria-hidden", "true");
        lightbox.innerHTML = [
            '<div class="prq-image-lightbox-dialog" role="dialog" aria-modal="true" aria-labelledby="prqImageLightboxTitle">',
            '    <div class="prq-image-lightbox-head">',
            '        <h3 id="prqImageLightboxTitle" class="prq-image-lightbox-title">Image Preview</h3>',
            '        <button type="button" class="prq-image-lightbox-close" aria-label="Close preview">Close</button>',
            "    </div>",
            '    <div class="prq-image-lightbox-body">',
            '        <img class="prq-image-lightbox-img" src="" alt="Image preview"/>',
            "    </div>",
            "</div>"
        ].join("");
        document.body.appendChild(lightbox);
        return lightbox;
    }

    function getPreviewTitle(image) {
        return (
            image.getAttribute("data-preview-title") ||
            image.getAttribute("alt") ||
            image.closest("[data-preview-title]")?.getAttribute("data-preview-title") ||
            "Image Preview"
        );
    }

    function isPreviewableImage(image) {
        if (!image || !image.matches(CARD_IMAGE_SELECTOR)) {
            return false;
        }
        if (image.closest(EXCLUDED_CONTAINER_SELECTOR)) {
            return false;
        }
        if (image.hasAttribute("data-no-preview") || image.closest("[data-no-preview]")) {
            return false;
        }
        if (!image.currentSrc && !image.getAttribute("src")) {
            return false;
        }
        return true;
    }

    function markPreviewableImages() {
        document.querySelectorAll(CARD_IMAGE_SELECTOR).forEach(function (image) {
            if (isPreviewableImage(image)) {
                image.classList.add("prq-previewable-image");
                image.setAttribute("tabindex", "0");
                image.setAttribute("role", "button");
                image.setAttribute("aria-label", "Preview " + getPreviewTitle(image));
            }
        });
    }

    function openPreview(image) {
        const lightbox = createLightbox();
        const previewImage = lightbox.querySelector(".prq-image-lightbox-img");
        const previewTitle = lightbox.querySelector(".prq-image-lightbox-title");
        const src = image.currentSrc || image.getAttribute("src");
        const title = getPreviewTitle(image);

        previewImage.setAttribute("src", src);
        previewImage.setAttribute("alt", title);
        previewTitle.textContent = title;
        lightbox.classList.add("is-open");
        lightbox.setAttribute("aria-hidden", "false");
        document.documentElement.classList.add("prq-lightbox-open");
    }

    function closePreview() {
        const lightbox = document.getElementById("prqImageLightbox");
        if (!lightbox) {
            return;
        }
        lightbox.classList.remove("is-open");
        lightbox.setAttribute("aria-hidden", "true");
        const previewImage = lightbox.querySelector(".prq-image-lightbox-img");
        if (previewImage) {
            previewImage.setAttribute("src", "");
        }
        document.documentElement.classList.remove("prq-lightbox-open");
    }

    function setupImagePreview() {
        markPreviewableImages();

        document.addEventListener("click", function (event) {
            const closeButton = event.target.closest(".prq-image-lightbox-close");
            if (closeButton || event.target.id === "prqImageLightbox") {
                closePreview();
                return;
            }

            const image = event.target.closest("img");
            if (!isPreviewableImage(image)) {
                return;
            }
            event.preventDefault();
            openPreview(image);
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                closePreview();
                return;
            }

            if (event.key !== "Enter" && event.key !== " ") {
                return;
            }

            const image = event.target.closest("img");
            if (!isPreviewableImage(image)) {
                return;
            }
            event.preventDefault();
            openPreview(image);
        });

        if ("MutationObserver" in window) {
            const observer = new MutationObserver(function () {
                markPreviewableImages();
            });
            observer.observe(document.body, {
                childList: true,
                subtree: true
            });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", setupImagePreview);
    } else {
        setupImagePreview();
    }
})();
