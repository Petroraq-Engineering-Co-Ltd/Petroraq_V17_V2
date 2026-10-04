import json
import logging

from lxml import etree


_logger = logging.getLogger(__name__)

_STALE_STUDIO_XPATH = (
    "//form[1]/sheet[1]/notebook[1]/page[3]/"
    "button[@name='action_view_attachments']"
)


def _remove_stale_attachment_xpath(arch):
    """Remove the obsolete Studio instruction without touching other edits."""
    if not arch or _STALE_STUDIO_XPATH not in arch:
        return arch, False

    root = etree.fromstring(arch.encode("utf-8"))
    stale_nodes = root.xpath(
        ".//xpath[@expr=$expression]",
        expression=_STALE_STUDIO_XPATH,
    )
    for node in stale_nodes:
        node.getparent().remove(node)

    if not stale_nodes:
        return arch, False
    return etree.tostring(root, encoding="unicode"), True


def migrate(cr, version):
    """Repair stale Studio customizations before the canonical view is loaded."""
    cr.execute(
        """
        SELECT id, arch_db
          FROM ir_ui_view
         WHERE model = 'purchase.requisition'
           AND arch_db::text LIKE %s
         FOR UPDATE
        """,
        ("%notebook[1]/page[3]/button%action_view_attachments%",),
    )

    repaired_view_ids = []
    for view_id, stored_arch in cr.fetchall():
        translations = (
            stored_arch
            if isinstance(stored_arch, dict)
            else json.loads(stored_arch)
        )
        repaired_translations = dict(translations)
        changed = False

        for language, arch in translations.items():
            repaired_arch, arch_changed = _remove_stale_attachment_xpath(arch)
            if arch_changed:
                repaired_translations[language] = repaired_arch
                changed = True

        if not changed:
            continue

        cr.execute(
            """
            UPDATE ir_ui_view
               SET arch_db = %s::jsonb,
                   write_date = NOW()
             WHERE id = %s
            """,
            (json.dumps(repaired_translations), view_id),
        )
        repaired_view_ids.append(view_id)

    if repaired_view_ids:
        _logger.info(
            "Removed stale Purchase Requisition attachment XPath from Studio views %s",
            repaired_view_ids,
        )
