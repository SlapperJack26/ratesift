import os
import re
import shutil

QUICK_HERTZ_DIR = r"c:\Users\Dylan\Documents\antigravity\quick-hertz"
TEMPLATES_DIR = os.path.join(QUICK_HERTZ_DIR, "templates")
ARTIFACTS_DIR = r"C:\Users\Dylan\.gemini\antigravity\brain\b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4"

CSS_VARS_STYLE = """  <style>
    :root {
      --background: #ffffff;
      --foreground: #0f172a;
      --card: #ffffff;
      --card-foreground: #0f172a;
      --border: #e2e8f0;
      --muted: #f8fafc;
      --muted-foreground: #64748b;
    }
  </style>"""

MOBILE_NAV_SCRIPT = """
    function toggleMobileNav() {
      const drawer = document.getElementById('mobile-nav-drawer');
      if (drawer) {
        drawer.classList.toggle('hidden');
      }
    }
"""

def update_common_head_and_container(content):
    # Viewport
    content = re.sub(
        r'<meta name="viewport" content="[^"]*">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">',
        content
    )
    # Ensure CSS vars
    if "--border: #e2e8f0" not in content and "</head>" in content:
        content = content.replace("</head>", f"{CSS_VARS_STYLE}\n</head>", 1)

    # Auto-scale outer container from phone to 4K monitor
    content = re.sub(
        r'class="([^"]*?)max-w-5xl mx-auto([^"]*?)"',
        r'class="\1w-full max-w-5xl lg:max-w-6xl xl:max-w-7xl 2xl:max-w-[1400px] mx-auto transition-all\2"',
        content
    )
    content = re.sub(
        r'class="([^"]*?)max-w-6xl mx-auto([^"]*?)"',
        r'class="\1w-full max-w-5xl lg:max-w-6xl xl:max-w-7xl 2xl:max-w-[1400px] mx-auto transition-all\2"',
        content
    )
    return content

def process_public_home(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    content = update_common_head_and_container(content)

    # Update header nav to hide on mobile (< 768px) and show on md+
    if 'hidden md:flex absolute inset-x-0 mx-auto' not in content:
        content = content.replace(
            '<nav role="navigation" aria-label="Main Navigation" class="absolute inset-x-0 mx-auto flex items-center justify-center gap-8 text-sm font-medium">',
            '<nav role="navigation" aria-label="Main Navigation" class="hidden md:flex absolute inset-x-0 mx-auto items-center justify-center gap-6 lg:gap-8 text-sm font-medium">'
        )

    # Add mobile hamburger button if not present
    if 'toggleMobileNav()' not in content:
        # Replace right CTA container to include hamburger
        old_cta = r'(<div class="flex items-center gap-3 z-10">\s*<a href="/login"[^>]*>[\s\S]*?</a>\s*<a href="/get-started"[^>]*>[\s\S]*?</a>)(\s*</div>)'
        new_cta = r'''\1
        <!-- Mobile Menu Toggle Button (Phone Only) -->
        <button type="button" onclick="toggleMobileNav()" aria-label="Toggle mobile menu" class="md:hidden p-1.5 rounded-lg border border-[var(--border)] text-slate-600 hover:bg-black/5 focus:outline-hidden transition-colors">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16m-7 6h7"></path></svg>
        </button>\2'''
        content = re.sub(old_cta, new_cta, content)

    # Add mobile drawer right below </header> if not present
    if 'id="mobile-nav-drawer"' not in content:
        mobile_drawer = '''    </header>

    <!-- Collapsible Mobile Navigation Drawer for Phones (< 768px) -->
    <nav id="mobile-nav-drawer" aria-label="Mobile Navigation" class="hidden md:hidden border-b border-[var(--border)] bg-slate-50/95 px-4 py-3 space-y-1.5 text-xs font-medium transition-all">
      <button onclick="setPublicTab('home'); toggleMobileNav();" class="w-full text-left px-3 py-2 rounded-lg text-blue-600 font-bold bg-blue-50/80">Home</button>
      <button onclick="setPublicTab('demo'); toggleMobileNav();" class="w-full text-left px-3 py-2 rounded-lg text-slate-700 hover:text-blue-600">Demo</button>
      <button onclick="setPublicTab('pricing'); toggleMobileNav();" class="w-full text-left px-3 py-2 rounded-lg text-slate-700 hover:text-blue-600">Pricing</button>
      <div class="pt-2 mt-2 border-t border-[var(--border)] flex items-center justify-between">
        <a href="/login" class="text-xs font-semibold text-slate-700 hover:text-blue-600 px-1 py-1">Log in</a>
        <a href="/get-started" class="text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 px-3 py-1.5 rounded-md shadow-2xs">Get Started</a>
      </div>
    </nav>'''
        content = content.replace("    </header>", mobile_drawer, 1)

    # Hero buttons responsiveness (flex-col on phone, flex-row on sm+)
    content = content.replace(
        '<div class="flex items-center justify-center gap-3 pt-1">',
        '<div class="flex flex-col sm:flex-row items-center justify-center gap-3 pt-1">'
    )

    # Add toggleMobileNav JS
    if 'function toggleMobileNav()' not in content and '</script>' in content:
        content = content.replace('</script>', MOBILE_NAV_SCRIPT + '\n  </script>', 1)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Updated: {filepath}")

def process_standalone_public_page(filepath, current_page):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    content = update_common_head_and_container(content)

    # Update header nav to hidden md:flex
    content = re.sub(
        r'<nav role="navigation" aria-label="Main Navigation" class="([^"]*?)absolute inset-x-0 mx-auto flex items-center justify-center([^"]*?)">',
        r'<nav role="navigation" aria-label="Main Navigation" class="hidden md:flex absolute inset-x-0 mx-auto items-center justify-center gap-6 lg:gap-8 text-sm font-medium">',
        content
    )

    # Add mobile hamburger button if not present
    if 'toggleMobileNav()' not in content:
        old_cta = r'(<div class="flex items-center gap-[0-9.]+ z-10">\s*<a href="/login"[^>]*>[\s\S]*?</a>\s*<a href="/get-started"[^>]*>[\s\S]*?</a>)(\s*</div>)'
        new_cta = r'''\1
        <!-- Mobile Menu Toggle Button (Phone Only) -->
        <button type="button" onclick="toggleMobileNav()" aria-label="Toggle mobile menu" class="md:hidden p-1.5 rounded-lg border border-[var(--border)] text-slate-600 hover:bg-black/5 focus:outline-hidden transition-colors">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16m-7 6h7"></path></svg>
        </button>\2'''
        content = re.sub(old_cta, new_cta, content)

    # Add mobile drawer right below </header> if not present
    if 'id="mobile-nav-drawer"' not in content:
        home_cls = 'text-blue-600 font-bold bg-blue-50/80' if current_page == 'home' else 'text-slate-700 hover:text-blue-600'
        demo_cls = 'text-blue-600 font-bold bg-blue-50/80' if current_page == 'demo' else 'text-slate-700 hover:text-blue-600'
        pricing_cls = 'text-blue-600 font-bold bg-blue-50/80' if current_page == 'pricing' else 'text-slate-700 hover:text-blue-600'
        login_cls = 'text-blue-600 font-bold bg-blue-50/80' if current_page == 'login' else 'text-slate-700 hover:text-blue-600'
        get_started_cls = 'ring-2 ring-blue-600' if current_page == 'get_started' else ''

        mobile_drawer = f'''    </header>

    <!-- Collapsible Mobile Navigation Drawer for Phones (< 768px) -->
    <nav id="mobile-nav-drawer" aria-label="Mobile Navigation" class="hidden md:hidden border-b border-[var(--border)] bg-slate-50/95 px-4 py-3 space-y-1.5 text-xs font-medium transition-all">
      <a href="/" class="block px-3 py-2 rounded-lg {home_cls}">Home</a>
      <a href="/demo" class="block px-3 py-2 rounded-lg {demo_cls}">Demo</a>
      <a href="/pricing" class="block px-3 py-2 rounded-lg {pricing_cls}">Pricing</a>
      <div class="pt-2 mt-2 border-t border-[var(--border)] flex items-center justify-between">
        <a href="/login" class="text-xs font-semibold px-2 py-1 rounded {login_cls}">Log in</a>
        <a href="/get-started" class="text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 px-3 py-1.5 rounded-md shadow-2xs {get_started_cls}">Get Started</a>
      </div>
    </nav>'''
        content = content.replace("    </header>", mobile_drawer, 1)

    # Add toggleMobileNav JS
    if 'function toggleMobileNav()' not in content and '</script>' in content:
        content = content.replace('</script>', MOBILE_NAV_SCRIPT + '\n  </script>', 1)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Updated: {filepath}")

def process_console_page(filepath, active_page="new_quote"):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    content = update_common_head_and_container(content)

    # Fix relative link in settings.html if present
    content = content.replace('href="public_landing_view.html"', 'href="/"')

    # Nav responsive adjustments
    content = content.replace(
        '<nav role="navigation" aria-label="Main Navigation" class="absolute inset-x-0 mx-auto flex items-center justify-center gap-8 text-sm font-medium">',
        '<nav role="navigation" aria-label="Main Navigation" class="hidden xs:flex sm:flex absolute inset-x-0 mx-auto items-center justify-center gap-4 sm:gap-8 text-xs sm:text-sm font-medium">'
    )

    # Header container responsive padding
    content = content.replace(
        'class="px-6 py-3.5 border-b border-[var(--border)] flex items-center justify-between bg-[var(--card)] relative"',
        'class="px-4 sm:px-6 py-3.5 border-b border-[var(--border)] flex items-center justify-between bg-[var(--card)] relative"'
    )

    # Ensure table containers in history have smooth touch scrolling
    if 'overflow-x-auto' in content and '-webkit-overflow-scrolling' not in content:
        content = content.replace(
            'class="overflow-x-auto"',
            'class="overflow-x-auto" style="-webkit-overflow-scrolling: touch;"'
        )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Updated console: {filepath}")

def process_showcase(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    content = update_common_head_and_container(content)

    # Fix nested quotes in switchLiveTab calls
    content = content.replace('onclick="switchLiveTab("/console/new-quote")"', 'onclick="switchLiveTab(\'/console/new-quote\')"')
    content = content.replace('onclick="switchLiveTab("/console/history")"', 'onclick="switchLiveTab(\'/console/history\')"')
    content = content.replace('onclick="switchLiveTab("/console/account")"', 'onclick="switchLiveTab(\'/console/account\')"')
    content = content.replace('onclick="switchLiveTab("/console/settings")"', 'onclick="switchLiveTab(\'/console/settings\')"')
    content = content.replace('onclick="switchLiveTab("/")"', 'onclick="switchLiveTab(\'/\')"')
    content = content.replace('onclick="switchLiveTab("/demo")"', 'onclick="switchLiveTab(\'/demo\')"')
    content = content.replace('onclick="switchLiveTab("/pricing")"', 'onclick="switchLiveTab(\'/pricing\')"')
    content = content.replace('onclick="switchLiveTab("/login")"', 'onclick="switchLiveTab(\'/login\')"')
    content = content.replace('onclick="switchLiveTab("/get-started")"', 'onclick="switchLiveTab(\'/get-started\')"')
    content = content.replace('onclick="switchLiveTab("/flowchart")"', 'onclick="switchLiveTab(\'/flowchart\')"')

    # Add Device Viewport Switcher Controls Toolbar
    device_controls = """        <!-- Device Viewport & Auto-Scaling Controls Toolbar -->
        <div class="px-4 py-2 bg-slate-50 border-b border-[var(--border)] flex flex-wrap items-center justify-between gap-3 text-xs">
          <div class="flex items-center gap-2">
            <span class="font-bold text-slate-700 flex items-center gap-1.5">
              <span>📐 Device Viewport:</span>
            </span>
            <div class="inline-flex rounded-lg border border-slate-200 p-0.5 bg-white shadow-2xs gap-1">
              <button id="dev-phone" type="button" onclick="setDeviceViewport('phone')" class="device-btn px-2.5 py-1 rounded-md font-medium text-slate-600 hover:text-blue-600 transition-all flex items-center gap-1">
                <span>📱</span> <span>Phone (390px)</span>
              </button>
              <button id="dev-tablet" type="button" onclick="setDeviceViewport('tablet')" class="device-btn px-2.5 py-1 rounded-md font-medium text-slate-600 hover:text-blue-600 transition-all flex items-center gap-1">
                <span>📟</span> <span>iPad / Tablet (768px)</span>
              </button>
              <button id="dev-laptop" type="button" onclick="setDeviceViewport('laptop')" class="device-btn px-2.5 py-1 rounded-md font-medium text-slate-600 hover:text-blue-600 transition-all flex items-center gap-1">
                <span>💻</span> <span>Laptop (1024px)</span>
              </button>
              <button id="dev-desktop" type="button" onclick="setDeviceViewport('desktop')" class="device-btn px-2.5 py-1 rounded-md font-semibold bg-blue-50 text-blue-700 border border-blue-200 transition-all flex items-center gap-1">
                <span>🖥️</span> <span>Desktop (100% Fluid)</span>
              </button>
            </div>
          </div>

          <!-- Zoom / Scale Controls -->
          <div class="flex items-center gap-3">
            <div class="flex items-center gap-1 text-[11px] text-slate-500">
              <span>Scale:</span>
              <select id="scale-select" onchange="setDeviceScale(this.value)" class="bg-white border border-slate-200 rounded px-1.5 py-0.5 text-xs text-slate-700 font-mono">
                <option value="1">100%</option>
                <option value="0.9">90%</option>
                <option value="0.8">80%</option>
                <option value="0.75">75%</option>
              </select>
            </div>
            
            <span id="viewport-dimension-badge" class="font-mono text-[11px] text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-200 font-semibold">
              🖥️ Desktop: 100% Fluid Monitor
            </span>
          </div>
        </div>

        <!-- Device Wrapper Frame -->
        <div id="device-wrapper-outer" class="p-4 bg-slate-100/60 overflow-x-auto flex justify-center transition-all">
          <div id="device-mockup-frame" class="w-full transition-all duration-300" style="max-width: 100%;">
            <iframe id="live-frame" src="/console/new-quote" title="ShipFlow Active Screen Preview" class="w-full h-[620px] bg-white border border-slate-200 rounded-lg shadow-sm transition-all"></iframe>
          </div>
        </div>"""

    # Replace live-frame with the new wrapper if not already done
    if 'id="device-mockup-frame"' not in content:
        content = re.sub(
            r'<iframe id="live-frame"[^>]*></iframe>',
            '',
            content
        )
        content = content.replace(
            '<span class="text-[10px] text-[var(--muted-foreground)]">Interactive live preview frame</span>\n        </div>',
            '<span class="text-[10px] text-[var(--muted-foreground)]">Interactive live preview frame</span>\n        </div>\n' + device_controls
        )

    # Add Device Viewport Script
    device_script = """
    let currentDevice = 'desktop';
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
    }
"""
    if 'function setDeviceViewport' not in content and '</script>' in content:
        content = content.replace('</script>', device_script + '\n  </script>', 1)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Updated showcase: {filepath}")

def process_flowchart(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    content = update_common_head_and_container(content)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Updated flowchart: {filepath}")

def sync_to_artifacts():
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

def main():
    print("Applying Full Responsive Auto-Scaling across all views...")

    # Public Pages
    process_public_home(os.path.join(TEMPLATES_DIR, "public", "home.html"))
    process_standalone_public_page(os.path.join(TEMPLATES_DIR, "public", "demo.html"), "demo")
    process_standalone_public_page(os.path.join(TEMPLATES_DIR, "public", "pricing.html"), "pricing")
    process_standalone_public_page(os.path.join(TEMPLATES_DIR, "public", "login.html"), "login")
    process_standalone_public_page(os.path.join(TEMPLATES_DIR, "public", "get_started.html"), "get_started")

    # Console Pages
    process_console_page(os.path.join(TEMPLATES_DIR, "console", "new_quote.html"), "new_quote")
    process_console_page(os.path.join(TEMPLATES_DIR, "console", "history.html"), "history")
    process_console_page(os.path.join(TEMPLATES_DIR, "console", "account.html"), "account")
    process_console_page(os.path.join(TEMPLATES_DIR, "console", "settings.html"), "settings")

    # Showcase & Flowchart
    process_showcase(os.path.join(TEMPLATES_DIR, "showcase.html"))
    process_flowchart(os.path.join(TEMPLATES_DIR, "flowchart.html"))

    # Sync to Brain Artifacts
    sync_to_artifacts()
    print("\nAll responsive auto-scaling changes successfully applied!")

if __name__ == "__main__":
    main()
