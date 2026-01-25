# Documentation automation

This page covers how to generate screenshots for the docs.

## Admin UI screenshot

1) Install Playwright (one time):

```bash
python -m pip install playwright
python -m playwright install
```

2) Capture the screenshot:

```bash
python scripts/capture_admin_screenshot.py --output documentation/assets/admin-ui-preview.png
```

This will start the agent on `http://127.0.0.1:8000`, open the Admin UI, and write a PNG to the assets folder.
