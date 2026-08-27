# Petroraq Backend Language Switcher — Odoo 17

A lightweight Odoo 17 addon that adds a global **🌐 EN | العربية** switcher to the backend systray/navbar.

## Features

- Visible throughout the Odoo backend, regardless of the current app/module.
- One-click switch between:
  - English (`en_US`)
  - Arabic (`ar_001`)
- Saves the selection on the currently logged-in Odoo user.
- Reloads the web client after switching so Odoo applies translations and RTL/LTR direction correctly.
- Server route only permits the two configured languages and only updates the current user's `lang` field.
- No modification of standard Odoo source code.

## Prerequisite

Both languages must be active in the database. English is normally active by default.

Before using Arabic, activate/install Arabic in Odoo from the language/translation settings. The technical Arabic code used by Odoo 17 is `ar_001`.

## Installation on Odoo.sh

1. Copy the entire `petroraq_language_switcher` folder into your custom addons repository.
2. Commit and push it to your Odoo.sh branch.
3. Wait for the Odoo.sh build to complete successfully.
4. In Odoo, enable Developer Mode.
5. Go to **Apps**.
6. Click **Update Apps List** if the module does not appear yet.
7. Search for **Petroraq Backend Language Switcher**.
8. Install it.
9. Hard-refresh the browser if the navbar item is not immediately visible.

## Updating after code changes

Upgrade the module from Apps, or from the Odoo shell/server command using your normal Odoo.sh upgrade workflow.

## Uninstallation

Uninstalling the addon removes the navbar switcher. It does not remove any language or translation data and does not change users' existing language preference.

## Technical structure

```text
petroraq_language_switcher/
├── __init__.py
├── __manifest__.py
├── README.md
├── controllers/
│   ├── __init__.py
│   └── main.py
└── static/
    └── src/
        ├── js/
        │   └── language_switcher.js
        ├── scss/
        │   └── language_switcher.scss
        └── xml/
            └── language_switcher.xml
```

## Notes

- Odoo interface labels change only where Arabic translations exist.
- Ordinary database text entered only in English is not automatically machine-translated.
- The module is deliberately limited to English and Arabic. More languages can be added later by extending the allow-list and buttons.
