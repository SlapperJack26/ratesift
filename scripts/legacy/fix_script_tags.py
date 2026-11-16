import os
import re
import shutil

QUICK_HERTZ_DIR = r"c:\Users\Dylan\Documents\antigravity\quick-hertz"
TEMPLATES_DIR = os.path.join(QUICK_HERTZ_DIR, "templates")
ARTIFACTS_DIR = r"C:\Users\Dylan\.gemini\antigravity\brain\b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4"

TAILWIND_PROPER = '<script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>'

MOBILE_NAV_FN = """    function toggleMobileNav() {
      const drawer = document.getElementById('mobile-nav-drawer');
      if (drawer) {
        drawer.classList.toggle('hidden');
      }
    }"""

SHOWCASE_DEVICE_FN = """    let currentDevice = 'desktop';
    let currentScale = 1;

    function setDeviceViewport(device) {
      currentDevice = device;
      document.querySelectorAll('.device-btn').forEach(btn => {
        btn.classList.remove('bg-blue-50', 'text-blue-700', 'border', 'border-blue-200', 'font-semibold');
        btn.classList.add('text-slate-600');
      });

      const activeBtn = document.getElementById('dev-' + device);
      if (activeBtn) {
        activeBtn.classList.add('bg-blue-50', 'text-blue-700', 'border', 'border-blue-200', 'font-semibold');
        activeBtn.classList.remove('text-slate-600');
      }

      const frame = document.getElementById('device-mockup-frame');
      const iframe = document.getElementById('live-frame');
      const badge = document.getElementById('viewport-dimension-badge');

      if (device === 'phone') {
        frame.style.maxWidth = '390px';
        iframe.style.height = '844px';
        iframe.className = 'w-full bg-white border-8 border-slate-800 rounded-[36px] shadow-2xl transition-all';
        badge.innerText = '📱 Phone: 390 × 844 px (iPhone 14/15)';
      } else if (device === 'tablet') {
        frame.style.maxWidth = '768px';
        iframe.style.height = '1024px';
        iframe.className = 'w-full bg-white border-8 border-slate-700 rounded-[28px] shadow-xl transition-all';
        badge.innerText = '📟 iPad: 768 × 1024 px (Portrait)';
      } else if (device === 'laptop') {
        frame.style.maxWidth = '1024px';
        iframe.style.height = '768px';
        iframe.className = 'w-full bg-white border-4 border-slate-600 rounded-xl shadow-lg transition-all';
        badge.innerText = '💻 Laptop: 1024 × 768 px (13-inch)';
      } else if (device === 'desktop') {
        frame.style.maxWidth = '100%';
        iframe.style.height = '620px';
        iframe.className = 'w-full h-[620px] bg-white border border-slate-200 rounded-lg shadow-sm transition-all';
        badge.innerText = '🖥️ Desktop: 100% Fluid Monitor';
      }
      applyDeviceScale();
    }

    function setDeviceScale(scale) {
      currentScale = parseFloat(scale);
      applyDeviceScale();
    }

    function applyDeviceScale() {
      const frame = document.getElementById('device-mockup-frame');
      if (currentScale === 1) {
        frame.style.transform = 'none';
      } else {
        frame.style.transform = `scale(${currentScale})`;
        frame.style.transformOrigin = 'top center';
      }
    }"""

def clean_file(filepath, is_showcase=False):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Clean Tailwind tag in <head>
    content = re.sub(
        r'<script src="https://www\.gstatic\.com/antigravity/web/dev/tailwindcss\.min\.js">[\s\S]*?</script>',
        TAILWIND_PROPER,
        content
    )

    # 2. For public files, ensure toggleMobileNav is in the bottom <script> before </body>
    if not is_showcase:
        if "toggleMobileNav()" in content:
            # Check if function toggleMobileNav is already inside a bottom <script>
            bottom_script_match = re.search(r'<script>([\s\S]*?)</script>\s*</body>', content)
            if bottom_script_match:
                script_body = bottom_script_match.group(1)
                if "function toggleMobileNav" not in script_body:
                    new_script_body = script_body + "\n\n" + MOBILE_NAV_FN
                    content = content.replace(f"<script>{script_body}</script>", f"<script>{new_script_body}</script>")
            else:
                # Add bottom script
                content = content.replace("</body>", f"<script>\n{MOBILE_NAV_FN}\n  </script>\n</body>")

    # 3. For showcase, ensure setDeviceViewport and related functions are inside the bottom <script>
    if is_showcase:
        bottom_script_match = re.search(r'<script>([\s\S]*?)</script>\s*</body>', content)
        if bottom_script_match:
            script_body = bottom_script_match.group(1)
            if "function setDeviceViewport" not in script_body:
                new_script_body = script_body + "\n\n" + SHOWCASE_DEVICE_FN
                content = content.replace(f"<script>{script_body}</script>", f"<script>{new_script_body}</script>")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Cleaned script tags for: {filepath}")

def main():
    public_files = [
        os.path.join(TEMPLATES_DIR, "public", "home.html"),
        os.path.join(TEMPLATES_DIR, "public", "demo.html"),
        os.path.join(TEMPLATES_DIR, "public", "pricing.html"),
        os.path.join(TEMPLATES_DIR, "public", "login.html"),
        os.path.join(TEMPLATES_DIR, "public", "get_started.html"),
    ]
    for p in public_files:
        clean_file(p, is_showcase=False)

    clean_file(os.path.join(TEMPLATES_DIR, "showcase.html"), is_showcase=True)

    # Sync to brain artifacts
    mapping = [
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

    for src, dst in mapping:
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"[OK] Synced {os.path.basename(src)} -> artifact {os.path.basename(dst)}")

if __name__ == "__main__":
    main()
