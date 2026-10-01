import os
import re

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
ARTIFACTS_DIR = r"C:\Users\Dylan\.gemini\antigravity\brain\b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4"

MOBILE_NAV_SCRIPT = """
    function toggleMobileNav() {
      const drawer = document.getElementById('mobile-nav-drawer');
      if (drawer) {
        drawer.classList.toggle('hidden');
      }
    }
"""

def update_public_template(filepath, current_page="home"):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Update viewport meta tag
    content = re.sub(
        r'<meta name="viewport" content="[^"]*">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">',
        content
    )

    # 2. Update outer container max-width to auto-scale from phone to 4K monitor
    content = re.sub(
        r'class="([^"]*?)max-w-5xl mx-auto([^"]*?)"',
        r'class="\1w-full max-w-5xl lg:max-w-6xl xl:max-w-7xl mx-auto transition-all\2"',
        content
    )

    # 3. Add responsive hamburger button and mobile nav drawer if not present
    if "mobile-nav-drawer" not in content:
        # Update public nav in header
        old_nav_pattern = r'(<nav role="navigation" aria-label="Main Navigation" class=")([^"]*)(">\s*<a href="/"[^>]*>Home</a>\s*<a href="/demo"[^>]*>Demo</a>\s*<a href="/pricing"[^>]*>Pricing</a>\s*</nav>)'
        
        replacement_nav = r'\1hidden md:flex absolute inset-x-0 mx-auto items-center justify-center gap-6 lg:gap-8 text-sm font-medium\3'
        content = re.sub(old_nav_pattern, replacement_nav, content)

        # Add hamburger button to the header right zone
        right_zone_pattern = r'(<div class="flex items-center gap-[0-9.]+ z-10">\s*<a href="/login"[^>]*>[\s\S]*?</a>\s*<a href="/get-started"[^>]*>[\s\S]*?</a>)(\s*</div>)'
        
        hamburger_btn = r'''\1
        <!-- Mobile Menu Toggle Button (Phone Only) -->
        <button type="button" onclick="toggleMobileNav()" aria-label="Toggle mobile menu" class="md:hidden p-1.5 rounded-lg border border-[var(--border)] text-slate-600 hover:bg-black/5 focus:outline-hidden">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16m-7 6h7"></path></svg>
        </button>\2'''
        content = re.sub(right_zone_pattern, hamburger_btn, content)

        # Insert mobile drawer right below </header>
        home_active = 'text-blue-600 font-bold bg-blue-50/70' if current_page == 'home' else 'text-slate-700 hover:text-blue-600'
        demo_active = 'text-blue-600 font-bold bg-blue-50/70' if current_page == 'demo' else 'text-slate-700 hover:text-blue-600'
        pricing_active = 'text-blue-600 font-bold bg-blue-50/70' if current_page == 'pricing' else 'text-slate-700 hover:text-blue-600'
        
        mobile_drawer = f'''    </header>

    <!-- Collapsible Mobile Navigation Drawer for Phones (< 768px) -->
    <nav id="mobile-nav-drawer" aria-label="Mobile Navigation" class="hidden md:hidden border-b border-[var(--border)] bg-slate-50/90 px-4 py-3 space-y-1.5 text-xs font-medium">
      <a href="/" class="block px-2.5 py-1.5 rounded-md {home_active}">Home</a>
      <a href="/demo" class="block px-2.5 py-1.5 rounded-md {demo_active}">Demo</a>
      <a href="/pricing" class="block px-2.5 py-1.5 rounded-md {pricing_active}">Pricing</a>
      <div class="pt-2 border-t border-[var(--border)] flex items-center justify-between">
        <a href="/login" class="text-xs font-semibold text-slate-700 hover:text-blue-600">Log in</a>
        <a href="/get-started" class="text-xs font-semibold text-white bg-blue-600 px-3 py-1 rounded-md">Get Started</a>
      </div>
    </nav>'''
        content = content.replace("    </header>", mobile_drawer, 1)

        # Append script if toggleMobileNav not present
        if "toggleMobileNav" not in content and "</script>" in content:
            content = content.replace("</script>", MOBILE_NAV_SCRIPT + "\n  </script>", 1)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Updated responsive auto-scaling for: {filepath}")

def update_console_template(filepath):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Update viewport meta tag
    content = re.sub(
        r'<meta name="viewport" content="[^"]*">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">',
        content
    )

    # Outer container max-width auto-scaling
    content = re.sub(
        r'class="([^"]*?)max-w-5xl mx-auto([^"]*?)"',
        r'class="\1w-full max-w-5xl lg:max-w-6xl xl:max-w-7xl mx-auto transition-all\2"',
        content
    )

    # Header nav gap responsive
    content = content.replace('gap-8 text-sm font-medium', 'gap-4 sm:gap-8 text-xs sm:text-sm font-medium')

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Updated responsive auto-scaling for console: {filepath}")

def main():
    # Update public pages
    update_public_template(os.path.join(TEMPLATES_DIR, "public", "home.html"), "home")
    update_public_template(os.path.join(TEMPLATES_DIR, "public", "demo.html"), "demo")
    update_public_template(os.path.join(TEMPLATES_DIR, "public", "pricing.html"), "pricing")
    update_public_template(os.path.join(TEMPLATES_DIR, "public", "login.html"), "login")
    update_public_template(os.path.join(TEMPLATES_DIR, "public", "get_started.html"), "get_started")

    # Update console pages
    update_console_template(os.path.join(TEMPLATES_DIR, "console", "new_quote.html"))
    update_console_template(os.path.join(TEMPLATES_DIR, "console", "history.html"))
    update_console_template(os.path.join(TEMPLATES_DIR, "console", "account.html"))
    update_console_template(os.path.join(TEMPLATES_DIR, "console", "settings.html"))

    # Also update corresponding artifacts
    update_public_template(os.path.join(ARTIFACTS_DIR, "public_landing_seo.html"), "home")
    update_public_template(os.path.join(ARTIFACTS_DIR, "public_demo_view.html"), "demo")
    update_public_template(os.path.join(ARTIFACTS_DIR, "public_pricing_view.html"), "pricing")
    update_public_template(os.path.join(ARTIFACTS_DIR, "public_login_view.html"), "login")
    update_public_template(os.path.join(ARTIFACTS_DIR, "public_get_started_view.html"), "get_started")

if __name__ == "__main__":
    main()
