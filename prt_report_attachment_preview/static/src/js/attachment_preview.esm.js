/** @odoo-module **/

function isWebContentDownloadLink(link) {
    const href = link.getAttribute("href");
    if (!href || !href.includes("/web/content")) {
        return false;
    }
    let url;
    try {
        url = new URL(href, window.location.origin);
    } catch {
        return false;
    }
    const download = (url.searchParams.get("download") || "").toLowerCase();
    return (
        url.pathname.includes("/web/content") &&
        (download === "true" || download === "1" || link.hasAttribute("download"))
    );
}

function isAttachmentWidgetLink(link) {
    return Boolean(
        link.closest(
            [
                ".o_field_binary",
                ".o_field_binary_file",
                ".o_field_many2many_binary",
                ".o_attachment",
                ".o_attachments",
                ".o_attachment_wrap",
                ".o-mail-Attachment",
                ".o-mail-AttachmentCard",
                ".o_Attachment",
            ].join(",")
        )
    );
}

document.addEventListener(
    "click",
    (ev) => {
        if (ev.defaultPrevented || !ev.target.closest) {
            return;
        }
        const link = ev.target.closest("a[href]");
        if (!link || !isWebContentDownloadLink(link) || !isAttachmentWidgetLink(link)) {
            return;
        }

        const previewUrl = new URL(link.href, window.location.origin);
        previewUrl.searchParams.delete("download");
        ev.preventDefault();
        ev.stopImmediatePropagation();
        window.open(previewUrl.toString(), "_blank", "noopener");
    },
    true
);
