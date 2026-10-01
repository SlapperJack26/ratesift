import os
import re
import shutil

QUICK_HERTZ_DIR = r"c:\Users\Dylan\Documents\antigravity\quick-hertz"
TEMPLATES_DIR = os.path.join(QUICK_HERTZ_DIR, "templates")
ARTIFACTS_DIR = r"C:\Users\Dylan\.gemini\antigravity\brain\b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4"

BRAND_HTML = 'r<span class="text-red-600">A</span>tes<span class="text-red-600">I</span>ft'
BRAND_PLAIN = 'rAtesIft'

def transform_content(content):
    # 1. First, protect <title>, <meta>, and JSON-LD from containing <span> tags
    # Replace ShipFlow in <title>
    content = re.sub(
        r'<title>(.*?)</title>',
        lambda m: '<title>' + m.group(1).replace('SHIPFLOW', BRAND_PLAIN).replace('ShipFlow', BRAND_PLAIN) + '</title>',
        content,
        flags=re.IGNORECASE
    )

    # Replace ShipFlow in <script type="application/ld+json">
    content = re.sub(
        r'(<script type="application/ld\+json">)([\s\S]*?)(</script>)',
        lambda m: m.group(1) + m.group(2).replace('SHIPFLOW', BRAND_PLAIN).replace('ShipFlow', BRAND_PLAIN) + m.group(3),
        content,
        flags=re.IGNORECASE
    )

    # Replace ShipFlow in meta tags content="..."
    content = re.sub(
        r'(<meta [^>]*content=")([^"]*)(")',
        lambda m: m.group(1) + m.group(2).replace('SHIPFLOW', BRAND_PLAIN).replace('ShipFlow', BRAND_PLAIN) + m.group(3),
        content,
        flags=re.IGNORECASE
    )

    # Replace ShipFlow in attributes: title="...", alt="...", aria-label="...", placeholder="..."
    for attr in ['title', 'alt', 'aria-label', 'aria-description', 'placeholder', 'download']:
        content = re.sub(
            rf'({attr}=")([^"]*)(")',
            lambda m: m.group(1) + m.group(2).replace('SHIPFLOW', BRAND_PLAIN).replace('ShipFlow', BRAND_PLAIN) + m.group(3),
            content,
            flags=re.IGNORECASE
        )

    # 2. Logo Badge initials: SF -> rI
    content = re.sub(r'>\s*SF\s*<', '>rI<', content)
    content = re.sub(r'aria-hidden="true">\s*SF\s*</div>', 'aria-hidden="true">rI</div>', content)
    content = re.sub(r'text-\[10px\]" aria-hidden="true">\s*SF\s*</div>', 'text-[10px]" aria-hidden="true">rI</div>', content)
    content = re.sub(r'text-\[9px\]">\s*SF\s*</div>', 'text-[9px]">rI</div>', content)
    content = re.sub(r'text-\[7px\]">\s*SF\s*</div>', 'text-[7px]">rI</div>', content)
    content = re.sub(r'SF SHIPFLOW', f'rI {BRAND_HTML}', content)

    # 3. Brand Text in Header & Footer: SHIPFLOW / ShipFlow -> r<span class="text-red-600">A</span>tes<span class="text-red-600">I</span>ft
    # Replace literal SHIPFLOW or ShipFlow that is outside of tag attributes
    # Specifically for the brand span
    content = re.sub(
        r'(<span class="font-bold text-base tracking-tight text-\[var\(--foreground\)\]">)(SHIPFLOW|ShipFlow)(</span>)',
        rf'\1{BRAND_HTML}\3',
        content
    )
    content = re.sub(
        r'(<span class="font-bold text-sm tracking-tight text-\[var\(--foreground\)\]">)(SHIPFLOW|ShipFlow)(</span>)',
        rf'\1{BRAND_HTML}\3',
        content
    )
    content = re.sub(
        r'(<span class="font-bold text-xs tracking-tight text-\[var\(--foreground\)\]">)(SHIPFLOW|ShipFlow)(</span>)',
        rf'\1{BRAND_HTML}\3',
        content
    )
    content = re.sub(
        r'(<span class="font-bold text-slate-800">)(SF SHIPFLOW|SHIPFLOW|ShipFlow)(</span>)',
        rf'\1rI {BRAND_HTML}\3',
        content
    )

    # In other visible body text, replace remaining ShipFlow with BRAND_HTML
    # Ensure we don't replace inside URLs or script tags or already-replaced spans
    # Replace >ShipFlow< or > ShipFlow < or words
    content = re.sub(r'\bShipFlow\b', BRAND_HTML, content)
    content = re.sub(r'\bSHIPFLOW\b', BRAND_HTML, content)

    # Clean any accidental double-spans if any occurred
    content = content.replace(f'{BRAND_HTML}{BRAND_HTML}', BRAND_HTML)

    # 4. Color Theme transformation: Blue -> Red
    # Replace all Tailwind blue classes with red classes
    # e.g., bg-blue-600 -> bg-red-600, text-blue-600 -> text-red-600, border-blue-200 -> border-red-200
    content = re.sub(r'\bblue-', 'red-', content)
    content = re.sub(r'\bhover:bg-blue-', 'hover:bg-red-', content)
    content = re.sub(r'\bhover:text-blue-', 'hover:text-red-', content)
    content = re.sub(r'\bhover:border-blue-', 'hover:border-red-', content)
    content = re.sub(r'\bfocus:ring-blue-', 'focus:ring-red-', content)
    content = re.sub(r'\bfocus:bg-blue-', 'focus:bg-red-', content)
    content = re.sub(r'\bring-blue-', 'ring-red-', content)

    # Any remaining standalone references to shipflow.io domain in copy or links can become ratesift.io
    content = content.replace('shipflow.io', 'ratesift.io')

    return content

def process_file(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    new_content = transform_content(content)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"[OK] Transformed: {filepath}")

def main():
    print("Applying rAtesIft brand name and Red color theme...")

    files_to_update = [
        # Public
        os.path.join(TEMPLATES_DIR, "public", "home.html"),
        os.path.join(TEMPLATES_DIR, "public", "demo.html"),
        os.path.join(TEMPLATES_DIR, "public", "pricing.html"),
        os.path.join(TEMPLATES_DIR, "public", "login.html"),
        os.path.join(TEMPLATES_DIR, "public", "get_started.html"),

        # Console
        os.path.join(TEMPLATES_DIR, "console", "new_quote.html"),
        os.path.join(TEMPLATES_DIR, "console", "history.html"),
        os.path.join(TEMPLATES_DIR, "console", "account.html"),
        os.path.join(TEMPLATES_DIR, "console", "settings.html"),

        # Showcase & Flowchart
        os.path.join(TEMPLATES_DIR, "showcase.html"),
        os.path.join(TEMPLATES_DIR, "flowchart.html"),
    ]

    for f in files_to_update:
        process_file(f)

    # Brain Artifacts mapping
    sync_mapping = [
        (os.path.join(TEMPLATES_DIR, "public", "home.html"), os.path.join(ARTIFACTS_DIR, "public_landing_seo.html")),
        (os.path.join(TEMPLATES_DIR, "public", "demo.html"), os.path.join(ARTIFACTS_DIR, "public_demo_view.html")),
        (os.path.join(TEMPLATES_DIR, "public", "pricing.html"), os.path.join(ARTIFACTS_DIR, "public_pricing_view.html")),
        (os.path.join(TEMPLATES_DIR, "public", "login.html"), os.path.join(ARTIFACTS_DIR, "public_login_view.html")),
        (os.path.join(TEMPLATES_DIR, "public", "get_started.html"), os.path.join(ARTIFACTS_DIR, "public_get_started_view.html")),
        (os.path.join(TEMPLATES_DIR, "console", "new_quote.html"), os.path.join(ARTIFACTS_DIR, "shipping_demo_view.html")),
        (os.path.join(TEMPLATES_DIR, "console", "history.html"), os.path.join(ARTIFACTS_DIR, "quotes_view.html")),
        (os.path.join(TEMPLATES_DIR, "console", "account.html"), os.path.join(ARTIFACTS_DIR, "account_settings_view.html")),
        (os.path.join(TEMPLATES_DIR, "console", "settings.html"), os.path.join(ARTIFACTS_DIR, "settings_view.html")),
        (os.path.join(TEMPLATES_DIR, "showcase.html"), os.path.join(ARTIFACTS_DIR, "showcase_all_views.html")),
        (os.path.join(TEMPLATES_DIR, "flowchart.html"), os.path.join(ARTIFACTS_DIR, "site_flowchart.html")),
    ]

    for src, dst in sync_mapping:
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"[OK] Synced {os.path.basename(src)} -> artifact {os.path.basename(dst)}")

    print("\nrAtesIft rebranding and Red color theme successfully applied to all views and artifacts!")

if __name__ == "__main__":
    main()
