import os
import re
import shutil

QUICK_HERTZ_DIR = r"c:\Users\Dylan\Documents\antigravity\quick-hertz"
TEMPLATES_DIR = os.path.join(QUICK_HERTZ_DIR, "templates")
ARTIFACTS_DIR = r"C:\Users\Dylan\.gemini\antigravity\brain\b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4"

def update_file(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Lowercase 'I' in stylized HTML brand name
    content = content.replace(
        'r<span class="text-red-600">A</span>tes<span class="text-red-600">I</span>ft',
        'r<span class="text-red-600">A</span>tes<span class="text-red-600">i</span>ft'
    )

    # 2. Lowercase 'I' in plain text brand name
    content = content.replace('rAtesIft', 'rAtesift')

    # 3. Lowercase 'I' in badge
    content = content.replace('>rI<', '>ri<')
    content = content.replace('>rI</div>', '>ri</div>')
    content = content.replace('rI r<span', 'ri r<span')
    content = content.replace('rI</span>', 'ri</span>')

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Updated: {filepath}")

def main():
    print("Lowercasing 'i' in company name across all templates and files...")

    files = [
        # Templates
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

        # Backend & Tests
        os.path.join(QUICK_HERTZ_DIR, "main.py"),
        os.path.join(QUICK_HERTZ_DIR, "test_server_startup.py"),
        os.path.join(QUICK_HERTZ_DIR, "test_full_platform_e2e.py"),
    ]

    for f in files:
        update_file(f)

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
        update_file(mdf)

    print("\nAll files successfully updated to lowercase 'i' (rAtesift)!")

if __name__ == "__main__":
    main()
