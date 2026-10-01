import os, glob, re, sys
sys.stdout.reconfigure(encoding='utf-8')

HEADER_TARGET_REGEX = re.compile(
    r'<div class="w-7 h-7 rounded-lg bg-red-600 flex items-center justify-center text-white font-bold text-xs shadow-xs"[^>]*>ri</div>\s*<span class="font-bold text-base tracking-tight text-\[var\(--foreground\)\]">r<span class="text-red-600">A</span>tes<span class="text-red-600">i</span>ft</span>',
    re.DOTALL
)

HEADER_REPLACEMENT = '<img src="/static/images/ratesift-logo.png" onerror="this.onerror=null; this.src=\'ratesift-logo.png\';" alt="RateSift" class="h-8 md:h-9 w-auto object-contain" />'

FOOTER_TARGET_REGEX = re.compile(
    r'<div class="flex items-center gap-2">\s*<div class="w-5 h-5 rounded-md bg-red-600 flex items-center justify-center text-white font-bold text-\[10px\]"[^>]*>ri</div>\s*<span class="font-bold text-sm tracking-tight text-\[var\(--foreground\)\]">r<span class="text-red-600">A</span>tes<span class="text-red-600">i</span>ft</span>\s*</div>',
    re.DOTALL
)

FOOTER_REPLACEMENT = '<div class="flex items-center"><img src="/static/images/ratesift-logo.png" onerror="this.onerror=null; this.src=\'ratesift-logo.png\';" alt="RateSift" class="h-6 md:h-7 w-auto object-contain" /></div>'

def process_file(file_path):
    if not os.path.exists(file_path):
        print(f"Skipping missing file: {file_path}")
        return
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    orig_content = content

    # Replace header brand
    content = HEADER_TARGET_REGEX.sub(HEADER_REPLACEMENT, content)

    # Replace footer brand
    content = FOOTER_TARGET_REGEX.sub(FOOTER_REPLACEMENT, content)

    # Showcase specific replacements
    if 'showcase' in file_path:
        # header
        content = re.sub(
            r'<div class="w-8 h-8 rounded-xl bg-red-600 flex items-center justify-center text-white font-bold text-sm shadow-xs" aria-hidden="true">ri</div>\s*<div>\s*<h1 class="text-base font-bold tracking-tight text-\[var\(--foreground\)\]">Ratesift Design Suite</h1>\s*<p class="text-xs text-\[var\(--muted-foreground\)\]">Side-by-side visual comparison of all 4 application screens</p>\s*</div>',
            r'<img src="/static/images/ratesift-logo.png" onerror="this.onerror=null; this.src=\'ratesift-logo.png\';" alt="RateSift" class="h-8 md:h-9 w-auto object-contain" />\n        <div class="border-l border-slate-200 pl-3">\n          <h1 class="text-base font-bold tracking-tight text-[var(--foreground)]">Design Suite</h1>\n          <p class="text-xs text-[var(--muted-foreground)]">Side-by-side visual comparison of all 4 application screens</p>\n        </div>',
            content
        )
        # footer
        content = re.sub(
            r'<div class="flex items-center gap-1\.5 font-bold text-\[var\(--foreground\)\]">\s*<div class="w-4 h-4 rounded-sm bg-red-600 flex items-center justify-center text-white text-\[9px\]">ri</div>\s*<span>Ratesift</span>\s*</div>',
            r'<div class="flex items-center"><img src="/static/images/ratesift-logo.png" onerror="this.onerror=null; this.src=\'ratesift-logo.png\';" alt="RateSift" class="h-6 md:h-7 w-auto object-contain" /></div>',
            content
        )

    # Flowchart specific replacements
    if 'flowchart' in file_path:
        content = re.sub(
            r'<div class="w-8 h-8 rounded-lg bg-red-600 flex items-center justify-center text-white font-bold text-sm shadow-xs">ri</div>\s*<div>\s*<h1 class="text-base font-bold text-slate-900 tracking-tight">Ratesift Page Architecture Flowchart</h1>\s*<p class="text-xs text-slate-500">Visual mapping of Public vs\. Private \(Authenticated\) pages and user routing</p>\s*</div>',
            r'<img src="/static/images/ratesift-logo.png" onerror="this.onerror=null; this.src=\'ratesift-logo.png\';" alt="RateSift" class="h-8 md:h-9 w-auto object-contain" />\n        <div class="border-l border-slate-200 pl-3">\n          <h1 class="text-base font-bold text-slate-900 tracking-tight">Page Architecture Flowchart</h1>\n          <p class="text-xs text-slate-500">Visual mapping of Public vs. Private (Authenticated) pages and user routing</p>\n        </div>',
            content
        )
        content = re.sub(
            r'<div class="flex items-center gap-2">\s*<div class="w-4 h-4 rounded-sm bg-red-600 flex items-center justify-center text-white text-\[9px\] font-bold">ri</div>\s*<span class="font-bold text-slate-700">Ratesift Architecture</span>\s*</div>',
            r'<div class="flex items-center gap-2"><img src="/static/images/ratesift-logo.png" onerror="this.onerror=null; this.src=\'ratesift-logo.png\';" alt="RateSift" class="h-6 md:h-7 w-auto object-contain" /><span class="font-bold text-slate-700 text-xs border-l border-slate-200 pl-2">Architecture</span></div>',
            content
        )

    if content != orig_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated: {file_path}")
    else:
        print(f"No changes matched in: {file_path}")

template_files = glob.glob('templates/**/*.html', recursive=True) + glob.glob('templates/*.html')
for tf in sorted(template_files):
    process_file(tf)

brain_dir = r'C:\Users\Dylan\.gemini\antigravity\brain\b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4'
brain_html_files = [
    'public_landing_seo.html',
    'public_demo_view.html',
    'public_pricing_view.html',
    'public_login_view.html',
    'public_get_started_view.html',
    'shipping_demo_view.html',
    'quotes_view.html',
    'account_settings_view.html',
    'settings_view.html',
    'showcase_all_views.html',
    'site_flowchart.html'
]
for bf in brain_html_files:
    full_p = os.path.join(brain_dir, bf)
    process_file(full_p)
