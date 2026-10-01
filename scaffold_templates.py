import os
import re

ARTIFACT_DIR = r"C:\Users\Dylan\.gemini\antigravity\brain\b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4"
BASE_DIR = os.path.dirname(__file__)
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

os.makedirs(os.path.join(TEMPLATES_DIR, "public"), exist_ok=True)
os.makedirs(os.path.join(TEMPLATES_DIR, "console"), exist_ok=True)

MAPPINGS = {
    # Artifact filename -> Target relative path in templates
    "public_landing_seo.html": "public/home.html",
    "public_demo_view.html": "public/demo.html",
    "public_pricing_view.html": "public/pricing.html",
    "public_login_view.html": "public/login.html",
    "public_get_started_view.html": "public/get_started.html",
    "shipping_demo_view.html": "console/new_quote.html",
    "quotes_view.html": "console/history.html",
    "account_settings_view.html": "console/account.html",
    "settings_view.html": "console/settings.html",
    "site_flowchart.html": "flowchart.html",
    "showcase_all_views.html": "showcase.html",
}

URL_REPLACEMENTS = [
    (r'href="public_landing_seo\.html"', 'href="/"'),
    (r'href="public_demo_view\.html"', 'href="/demo"'),
    (r'href="public_pricing_view\.html"', 'href="/pricing"'),
    (r'href="public_login_view\.html"', 'href="/login"'),
    (r'href="public_get_started_view\.html"', 'href="/get-started"'),
    (r'href="shipping_demo_view\.html"', 'href="/console/new-quote"'),
    (r'href="quotes_view\.html"', 'href="/console/history"'),
    (r'href="account_settings_view\.html"', 'href="/console/account"'),
    (r'href="settings_view\.html"', 'href="/console/settings"'),
    (r'href="site_flowchart\.html"', 'href="/flowchart"'),
    (r'href="showcase_all_views\.html"', 'href="/showcase"'),
    # Also in JS redirections
    (r'window\.location\.href\s*=\s*["\']shipping_demo_view\.html["\']', 'window.location.href = "/console/new-quote"'),
    (r'window\.location\.href\s*=\s*["\']quotes_view\.html["\']', 'window.location.href = "/console/history"'),
    (r'window\.location\.href\s*=\s*["\']public_landing_seo\.html["\']', 'window.location.href = "/"'),
    (r'window\.location\.href\s*=\s*["\']public_login_view\.html["\']', 'window.location.href = "/login"'),
    (r'switchLiveTab\(["\']shipping_demo_view\.html["\']\)', 'switchLiveTab("/console/new-quote")'),
    (r'switchLiveTab\(["\']quotes_view\.html["\']\)', 'switchLiveTab("/console/history")'),
    (r'switchLiveTab\(["\']account_settings_view\.html["\']\)', 'switchLiveTab("/console/account")'),
    (r'switchLiveTab\(["\']settings_view\.html["\']\)', 'switchLiveTab("/console/settings")'),
    (r'switchLiveTab\(["\']public_landing_seo\.html["\']\)', 'switchLiveTab("/")'),
    (r'switchLiveTab\(["\']public_demo_view\.html["\']\)', 'switchLiveTab("/demo")'),
    (r'switchLiveTab\(["\']public_pricing_view\.html["\']\)', 'switchLiveTab("/pricing")'),
    (r'switchLiveTab\(["\']public_login_view\.html["\']\)', 'switchLiveTab("/login")'),
    (r'switchLiveTab\(["\']public_get_started_view\.html["\']\)', 'switchLiveTab("/get-started")'),
    (r'switchLiveTab\(["\']site_flowchart\.html["\']\)', 'switchLiveTab("/flowchart")'),
    (r'src="shipping_demo_view\.html"', 'src="/console/new-quote"')
]

def main():
    copied = 0
    for art_file, target_rel in MAPPINGS.items():
        src_path = os.path.join(ARTIFACT_DIR, art_file)
        dst_path = os.path.join(TEMPLATES_DIR, target_rel)
        
        if not os.path.exists(src_path):
            print(f"Warning: source file not found: {src_path}")
            continue
            
        with open(src_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        for pattern, replacement in URL_REPLACEMENTS:
            content = re.sub(pattern, replacement, content)
            
        with open(dst_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        print(f"Ported {art_file} -> {target_rel}")
        copied += 1
        
    print(f"\nSuccessfully ported {copied} view templates into {TEMPLATES_DIR}")

if __name__ == "__main__":
    main()
