#!/usr/bin/env python3
"""
Export the Odit help page as a self-contained static HTML file for GitHub Pages.

Usage:
    python scripts/export_docs.py

Output:
    docs/index.html   — standalone help page
    docs/screenshots/ — all help screenshots (copied from app/static/help/)
"""

import os
import shutil
import sys
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOTS_SRC = os.path.join(ROOT, "app", "static", "help")
DOCS_DIR = os.path.join(ROOT, "docs")
SCREENSHOTS_DST = os.path.join(DOCS_DIR, "screenshots")

# ── CSS variables + utility classes extracted from base.html ─────────────────
ODIT_STYLES = """
    :root {
        --odit-bg:            #f8fafc;
        --odit-surface:       #ffffff;
        --odit-surface-2:     #f1f5f9;
        --odit-surface-hover: #f4f4f8;
        --odit-border:        rgba(15,23,42,0.07);
        --odit-border-md:     rgba(15,23,42,0.11);
        --odit-border-strong: rgba(15,23,42,0.18);
        --odit-shadow-sm:     0 1px 3px rgba(15,23,42,0.06), 0 0 0 1px rgba(15,23,42,0.04);
        --odit-shadow:        0 4px 16px rgba(15,23,42,0.08), 0 0 0 1px rgba(15,23,42,0.04);
        --odit-brand:         #1800ad;
        --odit-brand-hover:   #13008a;
        --odit-brand-2:       #3820c4;
        --odit-brand-light:   #eff0ff;
        --odit-text:          #0f172a;
        --odit-text-2:        #64748b;
        --odit-text-3:        #94a3b8;
    }
    html.dark {
        --odit-bg:            #000000;
        --odit-surface:       #0d0d0d;
        --odit-surface-2:     #0c0c18;
        --odit-surface-hover: #141420;
        --odit-border:        rgba(255,255,255,0.05);
        --odit-border-md:     rgba(255,255,255,0.08);
        --odit-border-strong: rgba(255,255,255,0.12);
        --odit-shadow-sm:     0 1px 3px rgba(0,0,0,0.8);
        --odit-shadow:        0 4px 16px rgba(0,0,0,0.9);
        --odit-brand:         #7c6af0;
        --odit-brand-hover:   #9585f8;
        --odit-brand-2:       #a898ff;
        --odit-brand-light:   #111118;
        --odit-text:          #e2e8f0;
        --odit-text-2:        #9090b8;
        --odit-text-3:        #606080;
    }
    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        background: var(--odit-bg);
        color: var(--odit-text);
        margin: 0;
    }
    * { transition-property: color, background-color, border-color; transition-duration: 150ms; }
    .odit-card {
        background: var(--odit-surface);
        border-radius: 16px;
        border: 1px solid var(--odit-border);
        box-shadow: var(--odit-shadow-sm);
    }
    .odit-card:hover { box-shadow: var(--odit-shadow); border-color: var(--odit-border-md); }

    /* Nav */
    #docs-nav {
        position: sticky; top: 0; z-index: 50;
        height: 56px;
        background: rgba(255,255,255,0.92);
        backdrop-filter: blur(12px);
        border-bottom: 1px solid var(--odit-border);
        display: flex; align-items: center; justify-content: space-between;
        padding: 0 24px;
    }
    html.dark #docs-nav { background: rgba(0,0,0,0.92); }
    html.dark .nav-logo img { filter: brightness(0) invert(1); }
    .nav-logo { display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 1.1rem; color: var(--odit-brand); text-decoration: none; }
    .nav-links { display: flex; align-items: center; gap: 8px; }
    .nav-link { color: var(--odit-text-2); border-radius: 8px; padding: 6px 12px; font-size: 0.875rem; font-weight: 500; text-decoration: none; }
    .nav-link:hover { color: var(--odit-text); background: var(--odit-surface-hover); }
    .nav-btn {
        background: var(--odit-brand); color: #fff; border: none; border-radius: 8px;
        padding: 6px 14px; font-size: 0.875rem; font-weight: 600;
        text-decoration: none; display: inline-flex; align-items: center; gap-6px;
        box-shadow: 0 1px 4px rgba(24,0,173,0.25);
    }
    .nav-btn:hover { background: var(--odit-brand-hover); }
    html.dark .nav-btn { color: #fff; }

    /* Dark toggle */
    #dark-toggle { cursor: pointer; padding: 6px; border-radius: 8px; border: none; background: transparent; color: var(--odit-text-2); }
    #dark-toggle:hover { background: var(--odit-surface-hover); color: var(--odit-text); }

    /* Content */
    .docs-content { max-width: 768px; margin: 0 auto; padding: 40px 24px 80px; }
    details summary { list-style: none; }
    details summary::-webkit-details-marker { display: none; }
    img { max-width: 100%; height: auto; }

    /* Screenshot frame */
    .screenshot { border: 1px solid var(--odit-border); border-radius: 12px; overflow: hidden; display: block; }

    /* Responsive */
    @media (max-width: 640px) {
        .sm\\:grid-cols-2 { grid-template-columns: 1fr !important; }
        .sm\\:grid-cols-3 { grid-template-columns: 1fr !important; }
        .sm\\:grid-cols-4 { grid-template-columns: repeat(2,1fr) !important; }
        .sm\\:col-span-2 { grid-column: span 1 !important; }
    }
"""

DARK_TOGGLE_SCRIPT = """
<script>
(function(){
    var s = localStorage.getItem('oditDarkMode');
    if (s === 'dark' || (s === null && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
    }
})();
function toggleDark() {
    var isDark = document.documentElement.classList.toggle('dark');
    localStorage.setItem('oditDarkMode', isDark ? 'dark' : 'light');
    document.getElementById('dark-toggle').textContent = isDark ? '☀' : '☾';
}
window.addEventListener('DOMContentLoaded', function() {
    var isDark = document.documentElement.classList.contains('dark');
    document.getElementById('dark-toggle').textContent = isDark ? '☀' : '☾';
});
</script>
"""

NAV_HTML = """
<nav id="docs-nav">
    <a class="nav-logo" href="index.html">
        <img src="odit.svg" alt="Odit" height="26" width="52" style="object-fit:contain;display:block;" />
    </a>
    <div class="nav-links">
        <a class="nav-link" href="index.html">Home</a>
        <a class="nav-link" href="https://github.com/venk-hub/Odit">GitHub</a>
        <button id="dark-toggle" onclick="toggleDark()" aria-label="Toggle dark mode" title="Toggle dark mode">☾</button>
        <a class="nav-btn" href="https://github.com/venk-hub/Odit#quick-start">Get started →</a>
    </div>
</nav>
"""


def render_help_template() -> str:
    """Render the help.html Jinja2 template to a string."""
    sys.path.insert(0, ROOT)

    # Minimal stub so Jinja2 can render without a running FastAPI app
    from jinja2 import Environment, FileSystemLoader

    env = Environment(
        loader=FileSystemLoader(os.path.join(ROOT, "app", "templates")),
        autoescape=True,
    )

    # Patch the extends to use a minimal standalone base
    template_src = env.loader.get_source(env, "help.html")[0]

    # Replace {% extends "base.html" %} and {% block content %} / {% endblock %}
    # to render just the content block
    template_src = re.sub(r'\{%[-\s]*extends[^%]+%\}', '', template_src)
    template_src = re.sub(r'\{%[-\s]*block title[^%]*%\}.*?\{%[-\s]*endblock[^%]*%\}', '', template_src, flags=re.DOTALL)
    template_src = re.sub(r'\{%[-\s]*block page_context_script[^%]*%\}.*?\{%[-\s]*endblock[^%]*%\}', '', template_src, flags=re.DOTALL)
    template_src = re.sub(r'\{%[-\s]*block content[^%]*%\}', '', template_src)
    template_src = re.sub(r'\{%[-\s]*endblock[^%]*%\}', '', template_src)

    # Fix screenshot paths: /static/help/foo.png → screenshots/foo.png
    template_src = template_src.replace('/static/help/', 'screenshots/')

    tmpl = env.from_string(template_src)
    return tmpl.render()


def build():
    print("Building Odit docs...")

    # 1. Copy screenshots
    os.makedirs(SCREENSHOTS_DST, exist_ok=True)
    if os.path.exists(SCREENSHOTS_SRC):
        for f in os.listdir(SCREENSHOTS_SRC):
            if f.endswith('.png'):
                shutil.copy2(
                    os.path.join(SCREENSHOTS_SRC, f),
                    os.path.join(SCREENSHOTS_DST, f)
                )
                print(f"  Copied screenshot: {f}")
    else:
        print(f"  Warning: screenshots dir not found at {SCREENSHOTS_SRC}")

    # 2. Copy logo
    logo_src = os.path.join(ROOT, "Odit.svg")
    if os.path.exists(logo_src):
        shutil.copy2(logo_src, os.path.join(DOCS_DIR, "odit.svg"))
        print("  Copied logo: odit.svg")

    # 3. Render help template
    print("  Rendering help template...")
    content_html = render_help_template()

    # 4. Assemble final HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Help & Documentation — Odit</title>
    <meta name="description" content="Complete documentation for Odit — the local-first website tracking auditor. Learn how to audit sites, read results, and use AI payload analysis." />
    <meta property="og:title" content="Odit — Help & Documentation" />
    <meta property="og:description" content="Every screen, tab, and button in Odit explained with screenshots." />
    <script>
    (function(){{
        var s = localStorage.getItem('oditDarkMode');
        if (s === 'dark' || (s === null && window.matchMedia('(prefers-color-scheme: dark)').matches)) {{
            document.documentElement.classList.add('dark');
        }}
    }})();
    </script>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>tailwind.config = {{ darkMode: 'class' }};</script>
    <style>
{ODIT_STYLES}
    </style>
</head>
<body>

{NAV_HTML}

<div class="docs-content">
{content_html}
</div>

<script>
function toggleDark() {{
    var isDark = document.documentElement.classList.toggle('dark');
    localStorage.setItem('oditDarkMode', isDark ? 'dark' : 'light');
    document.getElementById('dark-toggle').textContent = isDark ? '☀' : '☾';
}}
window.addEventListener('DOMContentLoaded', function() {{
    var isDark = document.documentElement.classList.contains('dark');
    document.getElementById('dark-toggle').textContent = isDark ? '☀' : '☾';
}});
</script>

</body>
</html>"""

    out_path = os.path.join(DOCS_DIR, "help.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    size_kb = os.path.getsize(out_path) // 1024
    print(f"  Written: docs/help.html ({size_kb} KB)")
    print("Done. Commit docs/ and enable GitHub Pages → /docs on main branch.")


if __name__ == "__main__":
    build()
