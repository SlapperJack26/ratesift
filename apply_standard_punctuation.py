import os
import re
import shutil

QUICK_HERTZ_DIR = r"c:\Users\Dylan\Documents\antigravity\quick-hertz"
TEMPLATES_DIR = os.path.join(QUICK_HERTZ_DIR, "templates")
ARTIFACTS_DIR = r"C:\Users\Dylan\.gemini\antigravity\brain\b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4"

STYLIZED_BRAND = 'r<span class="text-red-600">A</span>tes<span class="text-red-600">i</span>ft'
STANDARD_BRAND = 'Ratesift'

# Placeholders to protect header and footer during transformation
HEADER_PLACEHOLDER = "___HEADER_BRAND_PLACEHOLDER___"
FOOTER_PLACEHOLDER = "___FOOTER_BRAND_PLACEHOLDER___"

def process_template_content(content):
    # 1. Protect the brand in the top navigation header
    # Match the brand logo link in <header>
    # <span class="font-bold text-base tracking-tight text-[var(--foreground)]">r<span class="text-red-600">A</span>tes<span class="text-red-600">i</span>ft</span>
    header_pattern = rf'(<header role="banner"[\s\S]*?<span class="font-bold text-base tracking-tight text-\[var\(--foreground\)\]">)({re.escape(STYLIZED_BRAND)})(</span>)'
    content = re.sub(header_pattern, rf'\1{HEADER_PLACEHOLDER}\3', content)

    # In case the header has slightly different classes (e.g. flowchart or showcase)
    header_pattern2 = rf'(<header[\s\S]*?<span class="font-bold text-base[^>]*>)({re.escape(STYLIZED_BRAND)})(</span>)'
    content = re.sub(header_pattern2, rf'\1{HEADER_PLACEHOLDER}\3', content)

    # 2. Protect the brand in the footer
    # <span class="font-bold text-sm tracking-tight text-[var(--foreground)]">r<span class="text-red-600">A</span>tes<span class="text-red-600">i</span>ft</span>
    footer_pattern = rf'(<footer role="contentinfo"[\s\S]*?<span class="font-bold text-sm tracking-tight text-\[var\(--foreground\)\]">)({re.escape(STYLIZED_BRAND)})(</span>)'
    content = re.sub(footer_pattern, rf'\1{FOOTER_PLACEHOLDER}\3', content)

    footer_pattern2 = rf'(<footer[\s\S]*?<span class="font-bold text-sm[^>]*>)({re.escape(STYLIZED_BRAND)})(</span>)'
    content = re.sub(footer_pattern2, rf'\1{FOOTER_PLACEHOLDER}\3', content)

    # 3. Everywhere else, replace stylized brand with STANDARD_BRAND (Ratesift)
    content = content.replace(STYLIZED_BRAND, STANDARD_BRAND)

    # 4. Everywhere else, replace plain 'rAtesift' with STANDARD_BRAND (Ratesift), except in URLs (ratesift.io)
    # Match standalone rAtesift or rAtesIft
    content = re.sub(r'\brAtesift\b', STANDARD_BRAND, content)
    content = re.sub(r'\brAtesIft\b', STANDARD_BRAND, content)

    # 5. Restore the protected header and footer brand marks
    content = content.replace(HEADER_PLACEHOLDER, STYLIZED_BRAND)
    content = content.replace(FOOTER_PLACEHOLDER, STYLIZED_BRAND)

    # 6. Ensure domains remain proper lowercase
    content = content.replace('Ratesift.io', 'ratesift.io')
    content = content.replace('https://Ratesift.io', 'https://ratesift.io')

    return content

def update_file(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    new_content = process_template_content(content)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"[OK] Processed: {filepath}")

def main():
    print("Applying standard punctuation ('Ratesift') everywhere except header and footer...")

    templates = [
        os.path.join(TEMPLATES_DIR, "public", "home.html"),
        os.path.join(TEMPLATES_DIR, "public", "demo.html"),
        os.path.join(TEMPLATES_DIR, "public", "pricing.html"),
        os.path.join(TEMPLATES_DIR, "public", "login.html"),
        os.path.join(TEMPLATES_DIR, "public", "get_started.html"),
        os.path.join(TEMPLATES_DIR, "console", "new_quote.html"),
        os.path.join(TEMPLATES_DIR, "console", "history.html"),
        os.path.join(TEMPLATES_DIR, "console", "account.html"),
        os.path.join(TEMPLATES_DIR, "console", "settings.html"),
        os.path.join(TEMPLATES_DIR, "showcase.html"),
        os.path.join(TEMPLATES_DIR, "flowchart.html"),
    ]

    for t in templates:
        update_file(t)

    # Update backend title & test strings
    main_py = os.path.join(QUICK_HERTZ_DIR, "main.py")
    if os.path.exists(main_py):
        with open(main_py, "r", encoding="utf-8") as f:
            mc = f.read()
        mc = mc.replace("rAtesift Quoting API", "Ratesift Quoting API")
        mc = mc.replace("rAtesIft Quoting API", "Ratesift Quoting API")
        mc = mc.replace("rAtesift_Quotes_Export.xlsx", "Ratesift_Quotes_Export.xlsx")
        mc = mc.replace("rAtesIft_Quotes_Export.xlsx", "Ratesift_Quotes_Export.xlsx")
        with open(main_py, "w", encoding="utf-8") as f:
            f.write(mc)
        print(f"[OK] Updated main.py")

    test_startup = os.path.join(QUICK_HERTZ_DIR, "test_server_startup.py")
    if os.path.exists(test_startup):
        with open(test_startup, "r", encoding="utf-8") as f:
            sc = f.read()
        sc = sc.replace('assert "rAtesift" in r.text', 'assert "Ratesift" in r.text')
        sc = sc.replace('assert "rAtesIft" in r.text', 'assert "Ratesift" in r.text')
        with open(test_startup, "w", encoding="utf-8") as f:
            f.write(sc)
        print(f"[OK] Updated test_server_startup.py")

    # Sync to Brain Artifacts
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

    # Update markdown specifications in Artifacts
    md_files = [
        os.path.join(ARTIFACTS_DIR, "design_rules_specification.md"),
        os.path.join(ARTIFACTS_DIR, "site_architecture_flowchart.md"),
        os.path.join(ARTIFACTS_DIR, "responsive_auto_scaling_specification.md"),
        os.path.join(ARTIFACTS_DIR, "implementation_plan.md"),
    ]
    for mdf in md_files:
        if os.path.exists(mdf):
            with open(mdf, "r", encoding="utf-8") as f:
                content = f.read()
            # In docs, update general occurrences to Ratesift, while noting header/footer branding
            content = content.replace("rAtesift", "Ratesift")
            content = content.replace("rAtesIft", "Ratesift")
            with open(mdf, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[OK] Updated doc: {os.path.basename(mdf)}")

    print("\nTransformation complete: Standard punctuation ('Ratesift') applied everywhere except header and footer!")

if __name__ == "__main__":
    main()
