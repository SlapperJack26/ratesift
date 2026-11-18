/**
 * Quotelytics Global Chrome & Navigation Suite
 * Provides unified interactive functionality for all headers and footers across Quotelytics:
 * - Documentation Drawer / Modal (Quoting engine, CzarLite, Tariff Excel formatting, FSA routing)
 * - Support Desk & Hotline Drawer (Hotline 289-929-8565, ticket submission, FAQs)
 * - Developer API Reference Modal (Embedded quoting /api/v1/quotes/batch, curl/python snippets, Swagger)
 * - Canadian PIPEDA & Data Residency Modal (WHC Montreal/Halifax hosting, tenant quarantine)
 * - Notification Bell Popover & Telemetry (Quota alerts, weekly OTA fuel index updates)
 * - Header Quota synchronization & User Avatar Menu
 * - Public Header auth-state adaptation (Go to Console if logged in)
 */

(function () {
  // 1. Inject Global Modals Container if not present
  function injectModals() {
    if (document.getElementById('quotelytics-global-chrome-modals')) return;

    const container = document.createElement('div');
    container.id = 'quotelytics-global-chrome-modals';
    container.innerHTML = `
      <!-- DOCUMENTATION MODAL -->
      <div id="rs-modal-docs" class="hidden fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-3 sm:p-6 overflow-y-auto">
        <div class="bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden text-slate-800 animate-in fade-in zoom-in-95 duration-150">
          <div class="p-4 sm:p-5 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <div class="flex items-center gap-2.5">
              <div class="w-8 h-8 rounded-lg bg-red-600 flex items-center justify-center text-white font-bold text-xs">RS</div>
              <div>
                <h3 class="text-base font-bold text-slate-900">Quotelytics Knowledge Base & Documentation</h3>
                <p class="text-xs text-slate-500">Deterministic calculation engine, tariff structure, and Canadian postal routing guide</p>
              </div>
            </div>
            <button type="button" onclick="closeDocsModal()" class="p-1.5 rounded-lg hover:bg-slate-200 text-slate-400 hover:text-slate-700 transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Documentation Tabs -->
          <div class="px-5 pt-3 border-b border-slate-200 flex gap-4 overflow-x-auto text-xs font-semibold text-slate-500">
            <button type="button" id="doc-tab-btn-engine" onclick="switchDocTab('engine')" class="pb-2.5 text-red-600 border-b-2 border-red-600 font-bold">Rating Engine & Deficit</button>
            <button type="button" id="doc-tab-btn-tariffs" onclick="switchDocTab('tariffs')" class="pb-2.5 hover:text-slate-900">Tariff Excel Formats</button>
            <button type="button" id="doc-tab-btn-fsa" onclick="switchDocTab('fsa')" class="pb-2.5 hover:text-slate-900">Canadian FSA Routing</button>
            <button type="button" id="doc-tab-btn-privacy" onclick="switchDocTab('privacy')" class="pb-2.5 hover:text-slate-900">Tenant Quarantine</button>
          </div>

          <!-- Documentation Tab Contents -->
          <div class="p-5 sm:p-6 overflow-y-auto space-y-4 text-xs leading-relaxed flex-1">
            <div id="doc-pane-engine" class="space-y-3">
              <h4 class="text-sm font-bold text-slate-900">Deterministic Rating & Deficit Pricing Logic</h4>
              <p>Quotelytics evaluates every freight quote using absolute mathematical precision. If a shipment weighs 850 lbs under a base rate of $12.50/cwt ($106.25), but the 1,000 lbs break drops to $9.50/cwt ($95.00), the deficit weight engine automatically rates the shipment at the lower 1,000 lbs threshold ($95.00), saving you money on every lane.</p>
              <div class="bg-slate-50 border border-slate-200 rounded-lg p-3 space-y-1 font-mono text-[11px]">
                <div class="font-bold text-slate-700">Formula Evaluation:</div>
                <div>Actual Charge = (Actual Weight / 100) × Current Rate</div>
                <div>Deficit Charge = (Next Break Min Weight / 100) × Next Break Rate</div>
                <div>Billable Rate = MIN(Actual Charge, Deficit Charge) ≥ Minimum Floor Charge</div>
              </div>
            </div>

            <div id="doc-pane-tariffs" class="hidden space-y-3">
              <h4 class="text-sm font-bold text-slate-900">Tariff Spreadsheet Structuring (.xlsx / .csv)</h4>
              <p>Quotelytics auto-detects header rows and column mappings. Recommended column titles include:</p>
              <ul class="list-disc pl-5 space-y-1 text-slate-600">
                <li><strong>Origin / Origin FSA</strong>: 3-digit Canadian Postal FSA (e.g. M5V, T2P) or city/province.</li>
                <li><strong>Destination / Dest FSA</strong>: Destination location code.</li>
                <li><strong>Weight Breaks</strong>: Standard Canadian LTL weight breaks (Min, L5C, M5C, M1M, M2M, M5M, M10M).</li>
                <li><strong>Accessorials & Minimums</strong>: Minimum carrier floor charges and surcharge additions.</li>
              </ul>
              <p class="text-slate-500">During upload, the Human Confirmation Gate previews cell coordinates and allows row-by-row overrides.</p>
            </div>

            <div id="doc-pane-fsa" class="hidden space-y-3">
              <h4 class="text-sm font-bold text-slate-900">Canadian Postal FSA Resolution</h4>
              <p>Canada Post utilizes Forward Sortation Areas (FSAs) — the first three characters of a postal code. Quotelytics resolves all 1,600+ Canadian FSAs into major carrier delivery zones (e.g., M = Toronto Urban Hub, H = Montreal Hub, V = Vancouver Hub, T = Calgary/Edmonton).</p>
              <p>Rural FSAs (containing a '0' as the second digit, like A0A or T0E) are automatically flagged with rural beyond charge alerts.</p>
            </div>

            <div id="doc-pane-privacy" class="hidden space-y-3">
              <h4 class="text-sm font-bold text-slate-900">Complete Tenant Data Quarantine</h4>
              <p>In accordance with Canadian PIPEDA sovereignty, Quotelytics enforces a zero-knowledge tariff boundary. Accounts only have access to tariffs they directly upload. No benchmark sample rates from other carriers or competitors are shared, ensuring your private rates and negotiated customer discounts remain 100% confidential.</p>
            </div>
          </div>

          <div class="p-4 border-t border-slate-200 bg-slate-50 flex justify-between items-center text-xs">
            <span class="text-slate-500">Need direct integration assistance?</span>
            <button type="button" onclick="closeDocsModal(); openSupportModal();" class="text-red-600 font-bold hover:underline">Contact Dispatch Engineering →</button>
          </div>
        </div>
      </div>

      <!-- SUPPORT & HOTLINE DRAWER -->
      <div id="rs-modal-support" class="hidden fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-3 sm:p-6 overflow-y-auto">
        <div class="bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-xl max-h-[92vh] flex flex-col overflow-hidden text-slate-800 animate-in fade-in zoom-in-95 duration-150">
          <div class="p-4 sm:p-5 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <div>
              <h3 class="text-base font-bold text-slate-900">Quotelytics Support Desk & Dispatch Hotline</h3>
              <p class="text-xs text-slate-500">Fast assistance for quoting discrepancies, sheet parsing, and enterprise routing</p>
            </div>
            <button type="button" onclick="closeSupportModal()" class="p-1.5 rounded-lg hover:bg-slate-200 text-slate-400 hover:text-slate-700 transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Hotline Callout Banner -->
          <div class="p-4 bg-red-50 border-b border-red-100 flex items-center justify-between gap-3 text-xs">
            <div class="flex items-center gap-3">
              <div class="w-9 h-9 rounded-full bg-red-600 text-white flex items-center justify-center font-bold">
                <svg class="w-4 h-4 fill-current" viewBox="0 0 24 24"><path d="M6.62 10.79a15.05 15.05 0 006.59 6.59l2.2-2.2a1 1 0 011.02-.24c1.12.37 2.33.57 3.57.57a1 1 0 011 1V20a1 1 0 01-1 1A17 17 0 013 4a1 1 0 011-1h3.5a1 1 0 011 1c0 1.25.2 2.45.57 3.57a1 1 0 01-.24 1.02l-2.21 2.2z"/></svg>
              </div>
              <div>
                <div class="font-bold text-red-900 text-sm">Urgent Dispatch Hotline: <a href="tel:2899298565" class="underline hover:text-red-700">289-929-8565</a></div>
                <div class="text-[11px] text-red-700">Mon - Fri • 8:00 AM - 6:00 PM EST • Emergency Routing Support</div>
              </div>
            </div>
          </div>

          <form id="rs-support-form" onsubmit="handleSupportSubmit(event)" class="p-5 space-y-3.5 text-xs overflow-y-auto flex-1">
            <div>
              <label for="rs-support-email" class="block font-semibold text-slate-700 mb-1">Your Work Email</label>
              <input id="rs-support-email" type="email" required placeholder="dispatcher@logistics.ca" class="w-full bg-slate-50 border border-slate-300 rounded-lg px-3 py-2 text-xs focus:outline-none">
            </div>

            <div class="grid grid-cols-2 gap-3">
              <div>
                <label for="rs-support-cat" class="block font-semibold text-slate-700 mb-1">Category</label>
                <select id="rs-support-cat" aria-label="Support Category" class="w-full bg-slate-50 border border-slate-300 rounded-lg px-2.5 py-2 text-xs focus:outline-none">
                  <option value="QUOTING">Quoting Engine / Rating</option>
                  <option value="TARIFF_INGESTION">Spreadsheet Parsing / Ingestion</option>
                  <option value="ACCOUNT_SEATS">Account Limits & Seats</option>
                  <option value="API_INTEGRATION">Embedded API Integration</option>
                  <option value="GENERAL">General Inquiry</option>
                </select>
              </div>
              <div>
                <label for="rs-support-sev" class="block font-semibold text-slate-700 mb-1">Severity</label>
                <select id="rs-support-sev" aria-label="Support Severity" class="w-full bg-slate-50 border border-slate-300 rounded-lg px-2.5 py-2 text-xs focus:outline-none">
                  <option value="NORMAL">Normal (Within 4 hours)</option>
                  <option value="URGENT">Urgent Dispatch Halt</option>
                </select>
              </div>
            </div>

            <div>
              <label for="rs-support-subj" class="block font-semibold text-slate-700 mb-1">Subject</label>
              <input id="rs-support-subj" type="text" required placeholder="Issue with deficit rate on Toronto-Montreal lane" class="w-full bg-slate-50 border border-slate-300 rounded-lg px-3 py-2 text-xs focus:outline-none">
            </div>

            <div>
              <label for="rs-support-msg" class="block font-semibold text-slate-700 mb-1">Message Details</label>
              <textarea id="rs-support-msg" rows="3" required placeholder="Describe the lane, shipment weight, or sheet row coordinate..." class="w-full bg-slate-50 border border-slate-300 rounded-lg px-3 py-2 text-xs focus:outline-none"></textarea>
            </div>

            <div class="p-2.5 bg-slate-50 rounded-lg border border-slate-200 text-[11px] text-slate-500">
              Your browser diagnostics and tenant ID will be automatically attached to help resolve this quickly.
            </div>

            <div class="pt-2 flex justify-end gap-2">
              <button type="button" onclick="closeSupportModal()" class="px-3.5 py-2 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-100 font-semibold text-xs">Cancel</button>
              <button type="submit" id="rs-btn-submit-support" class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg font-bold text-xs shadow-xs transition-colors">Submit Support Ticket</button>
            </div>
          </form>
        </div>
      </div>

      <!-- DEVELOPER API MODAL -->
      <div id="rs-modal-api" class="hidden fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-3 sm:p-6 overflow-y-auto">
        <div class="bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden text-slate-800 animate-in fade-in zoom-in-95 duration-150">
          <div class="p-4 sm:p-5 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <div>
              <h3 class="text-base font-bold text-slate-900">Quotelytics Business Embedded Quoting API</h3>
              <p class="text-xs text-slate-500">Integrate sub-second deterministic freight quotes into your TMS, WMS, or ERP</p>
            </div>
            <button type="button" onclick="closeApiModal()" class="p-1.5 rounded-lg hover:bg-slate-200 text-slate-400 hover:text-slate-700 transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <div class="p-5 sm:p-6 overflow-y-auto space-y-4 text-xs flex-1">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div class="flex items-center justify-between bg-slate-900 text-white p-3 rounded-xl font-mono text-xs">
                <div>
                  <span class="text-emerald-400 font-bold">POST</span>
                  <span class="ml-1.5 text-slate-200">/api/quotelytics/quotes/calculate</span>
                </div>
                <span class="text-[10px] bg-slate-800 px-2 py-0.5 rounded text-slate-300">Single LTL</span>
              </div>
              <div class="flex items-center justify-between bg-slate-900 text-white p-3 rounded-xl font-mono text-xs">
                <div>
                  <span class="text-emerald-400 font-bold">POST</span>
                  <span class="ml-1.5 text-slate-200">/api/v1/quotes/batch</span>
                </div>
                <span class="text-[10px] bg-slate-800 px-2 py-0.5 rounded text-slate-300">Up to 100 LTL</span>
              </div>
            </div>

            <div class="space-y-2">
              <h4 class="font-bold text-slate-900 text-xs">Python LTL Batch Integration Example (https://quotelytics.ca):</h4>
              <pre class="bg-slate-950 text-slate-200 p-3.5 rounded-xl font-mono text-[11px] overflow-x-auto leading-relaxed">import requests

url = "https://quotelytics.ca/api/v1/quotes/batch"
headers = {"X-API-Key": "ql_live_YOUR_PRODUCTION_KEY"}
payload = {
    "apply_markup": True,
    "shipments": [
        {
            "origin": "TORONTO, ON",
            "destination": "MONTREAL, QC",
            "actual_weight": 1850.0,
            "skid_count": 2,
            "accessorials": ["TAILGATE"]
        },
        {
            "origin": "TORONTO, ON",
            "destination": "CALGARY, AB",
            "actual_weight": 4200.0,
            "skid_count": 4
        }
    ]
}

response = requests.post(url, json=payload, headers=headers, timeout=10)
print(response.json())</pre>
            </div>

            <div class="bg-blue-50 border border-blue-200 rounded-xl p-3 text-xs text-blue-900 space-y-1">
              <div class="font-bold">API Key &amp; Signed Webhook Provisioning</div>
              <p>Business Tier accounts can generate SHA-256 hashed production API keys and register HMAC-SHA256 signed <code class="font-mono">batch.quote.completed</code> webhooks directly in the <a href="/console/account#api" class="underline font-bold">Account Center &rarr; Developer API</a> tab.</p>
            </div>
          </div>

          <div class="p-4 border-t border-slate-200 bg-slate-50 flex items-center justify-between text-xs">
            <a href="/docs" target="_blank" class="text-slate-600 hover:text-slate-900 font-semibold flex items-center gap-1.5">
              <span>Interactive Swagger UI Documentation</span>
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
            </a>
            <button type="button" onclick="closeApiModal()" class="px-4 py-1.5 bg-slate-900 text-white rounded-lg font-bold">Close</button>
          </div>
        </div>
      </div>

      <!-- PIPEDA & PRIVACY MODAL -->
      <div id="rs-modal-privacy" class="hidden fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-3 sm:p-6 overflow-y-auto">
        <div class="bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden text-slate-800 animate-in fade-in zoom-in-95 duration-150">
          <div class="p-4 sm:p-5 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-50 text-red-700 border border-red-200">CA</span>
              <div>
                <h3 class="text-base font-bold text-slate-900">Canadian Data Residency & Privacy Policy</h3>
                <p class="text-xs text-slate-500">PIPEDA Compliance, WHC Cloud Infrastructure & Commercial Data Protection</p>
              </div>
            </div>
            <button type="button" onclick="closePrivacyModal()" class="p-1.5 rounded-lg hover:bg-slate-200 text-slate-400 hover:text-slate-700 transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <div class="p-5 sm:p-6 overflow-y-auto space-y-4 text-xs leading-relaxed flex-1">
            <section class="space-y-1.5">
              <h4 class="font-bold text-slate-900 text-sm">1. Sovereign Canadian Hosting (WHC)</h4>
              <p class="text-slate-600">Quotelytics infrastructure is exclusively provisioned across Web Hosting Canada (WHC) Tier-III data centres located in Montreal, QC and Halifax, NS. All tariff spreadsheets, rate cards, and historical quote items are physically stored on Canadian soil in full compliance with Canadian provincial and federal data protection regulations.</p>
            </section>

            <section class="space-y-1.5">
              <h4 class="font-bold text-slate-900 text-sm">2. PIPEDA Strict Tenant Isolation</h4>
              <p class="text-slate-600">Under the Personal Information Protection and Electronic Documents Act (PIPEDA), your commercial tariffs are treated as strictly confidential proprietary assets. No freight rates or carrier agreements uploaded by your organization are ever shared, pooled, or benchmarked with any third party.</p>
            </section>

            <section class="space-y-1.5">
              <h4 class="font-bold text-slate-900 text-sm">3. Client-Side Tariff Redaction</h4>
              <p class="text-slate-600">Before sharing files, our built-in redaction tools automatically scrub account numbers, client names, and confidential contacts to guarantee privacy across external audits.</p>
            </section>

            <section class="space-y-1.5">
              <h4 class="font-bold text-slate-900 text-sm">4. Data Retention & Deletion Rights</h4>
              <p class="text-slate-600">Tenants may permanently purge their quote history and uploaded rate sheets at any time with immediate effect. Contact <a href="mailto:privacy@quotelytics.ca" class="underline font-bold text-red-600">privacy@quotelytics.ca</a> for formal audit certifications.</p>
            </section>
          </div>

          <div class="p-4 border-t border-slate-200 bg-slate-50 flex justify-between items-center text-xs">
            <a href="/privacy" class="text-red-600 font-bold hover:underline">Read Full PIPEDA Privacy Policy →</a>
            <button type="button" onclick="closePrivacyModal()" class="px-4 py-1.5 bg-slate-900 text-white rounded-lg font-bold">Close</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(container);
  }

  // 2. Global Modal Open / Close Functions
  window.openDocsModal = function (e) {
    if (e && e.preventDefault) e.preventDefault();
    injectModals();
    document.getElementById('rs-modal-docs')?.classList.remove('hidden');
  };
  window.closeDocsModal = function () {
    document.getElementById('rs-modal-docs')?.classList.add('hidden');
  };

  window.switchDocTab = function (tab) {
    const tabs = ['engine', 'tariffs', 'fsa', 'privacy'];
    tabs.forEach(t => {
      const btn = document.getElementById(`doc-tab-btn-${t}`);
      const pane = document.getElementById(`doc-pane-${t}`);
      if (btn && pane) {
        if (t === tab) {
          btn.className = "pb-2.5 text-red-600 border-b-2 border-red-600 font-bold";
          pane.classList.remove('hidden');
        } else {
          btn.className = "pb-2.5 hover:text-slate-900";
          pane.classList.add('hidden');
        }
      }
    });
  };

  let _authSession = { authenticated: false, user: null };

  window.openSupportModal = function (e) {
    if (e && e.preventDefault) e.preventDefault();
    injectModals();
    const modal = document.getElementById('rs-modal-support');
    if (modal) modal.classList.remove('hidden');

    if (!_authSession.authenticated) return;

    // Pre-fill email only when authenticated and response is OK
    fetch('/api/user/profile')
      .then(r => (r.ok ? r.json() : null))
      .then(p => {
        if (p && p.email && document.getElementById('rs-support-email')) {
          document.getElementById('rs-support-email').value = p.email;
        }
      })
      .catch(() => {});
  };
  window.closeSupportModal = function () {
    document.getElementById('rs-modal-support')?.classList.add('hidden');
  };

  window.handleSupportSubmit = async function (e) {
    if (e) e.preventDefault();
    const email = document.getElementById('rs-support-email').value;
    const category = document.getElementById('rs-support-cat').value;
    const severity = document.getElementById('rs-support-sev').value;
    const subject = document.getElementById('rs-support-subj').value;
    const message = document.getElementById('rs-support-msg').value;
    const submitBtn = document.getElementById('rs-btn-submit-support');

    const browserInfo = `${navigator.userAgent} | Screen: ${window.innerWidth}x${window.innerHeight} | Severity: ${severity}`;

    submitBtn.disabled = true;
    submitBtn.textContent = "Submitting...";

    try {
      const res = await fetch('/api/support/ticket', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, category, subject, message, browser_info: browserInfo })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to submit ticket");

      alert(`${data.message || "Support ticket created successfully!"}\nReference ID: ${data.ticket_id || "Received"}\nHotline: 289-929-8565`);
      closeSupportModal();
      document.getElementById('rs-support-form').reset();
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Submit Support Ticket";
    }
  };

  window.openApiModal = function (e) {
    if (e && e.preventDefault) e.preventDefault();
    injectModals();
    document.getElementById('rs-modal-api')?.classList.remove('hidden');
  };
  window.closeApiModal = function () {
    document.getElementById('rs-modal-api')?.classList.add('hidden');
  };

  window.openPrivacyModal = function (e) {
    if (e && e.preventDefault) e.preventDefault();
    injectModals();
    document.getElementById('rs-modal-privacy')?.classList.remove('hidden');
  };
  window.closePrivacyModal = function () {
    document.getElementById('rs-modal-privacy')?.classList.add('hidden');
  };

  // 3. Notification Bell Popover & Header Setup
  function setupHeaderNotifications() {
    const bellBtn = document.querySelector('button[aria-label="Notifications"]');
    if (!bellBtn) return;

    // Check if popover container exists; if not, create it
    let popover = document.getElementById('rs-notification-popover');
    if (!popover) {
      popover = document.createElement('div');
      popover.id = 'rs-notification-popover';
      popover.className = "hidden absolute right-4 top-14 w-80 sm:w-96 bg-white border border-slate-200 rounded-xl shadow-2xl z-50 text-xs overflow-hidden animate-in fade-in duration-100";
      popover.innerHTML = `
        <div class="p-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between font-bold text-slate-800">
          <div class="flex items-center gap-2">
            <span>System Notifications</span>
            <span id="rs-notif-count-badge" class="px-1.5 py-0.2 bg-red-600 text-white rounded-full text-[10px] font-mono">0</span>
          </div>
          <button type="button" onclick="markAllNotificationsRead()" class="text-[11px] font-semibold text-red-600 hover:underline">Mark all read</button>
        </div>
        <div id="rs-notif-list" class="max-h-80 overflow-y-auto divide-y divide-slate-100">
          <div class="p-4 text-center text-slate-400">Loading alerts...</div>
        </div>
      `;
      bellBtn.parentElement.style.position = 'relative';
      bellBtn.parentElement.appendChild(popover);
    }

    bellBtn.onclick = function (e) {
      e.stopPropagation();
      popover.classList.toggle('hidden');
      loadNotificationsList();
    };

    // Close on outside click
    window.addEventListener('click', function (e) {
      if (!popover.contains(e.target) && !bellBtn.contains(e.target)) {
        popover.classList.add('hidden');
      }
    });

    // Initial badge load only when authenticated
    if (_authSession.authenticated) {
      loadNotificationsBadge();
    }
  }

  function loadNotificationsBadge() {
    if (!_authSession.authenticated) return;
    fetch('/api/notifications?limit=5')
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (!data) return;
        const bellBtn = document.querySelector('button[aria-label="Notifications"]');
        if (!bellBtn) return;

        let badge = document.getElementById('rs-bell-unread-dot');
        if (data.unread_count > 0) {
          if (!badge) {
            badge = document.createElement('span');
            badge.id = 'rs-bell-unread-dot';
            badge.className = "absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-red-600 ring-2 ring-white";
            bellBtn.style.position = 'relative';
            bellBtn.appendChild(badge);
          }
        } else if (badge) {
          badge.remove();
        }
      })
      .catch(() => {});
  }

  function loadNotificationsList() {
    if (!_authSession.authenticated) return;
    fetch('/api/notifications?limit=10')
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (!data) return;
        const listEl = document.getElementById('rs-notif-list');
        const badgeEl = document.getElementById('rs-notif-count-badge');
        if (badgeEl) badgeEl.textContent = data.unread_count || 0;

        if (!listEl) return;
        if (!data.notifications || data.notifications.length === 0) {
          listEl.innerHTML = '<div class="p-4 text-center text-slate-400">No active notifications</div>';
          return;
        }

        listEl.innerHTML = data.notifications.map(n => {
          const typeBadge = n.alert_type === 'FUEL' 
            ? '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-100 text-amber-800">FUEL INDEX</span>'
            : (n.alert_type === 'SECURITY' 
              ? '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-100 text-emerald-800">SECURITY</span>'
              : '<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-blue-100 text-blue-800">FEATURE</span>');
          
          return `
            <div class="p-3 hover:bg-slate-50 transition-colors ${n.is_read ? 'opacity-70' : 'bg-red-50/20'}">
              <div class="flex items-center justify-between mb-1">
                ${typeBadge}
                <span class="text-[10px] text-slate-400">${(n.created_at || '').substring(0, 10)}</span>
              </div>
              <div class="font-bold text-slate-900 mb-0.5">${n.title}</div>
              <p class="text-[11px] text-slate-600">${n.message}</p>
              ${n.link_url ? `<a href="${n.link_url}" class="mt-1.5 inline-block text-[11px] text-red-600 font-semibold hover:underline">View Details →</a>` : ''}
            </div>
          `;
        }).join('');
      })
      .catch(() => {});
  }

  window.markAllNotificationsRead = function () {
    if (!_authSession.authenticated) return;
    fetch('/api/notifications/read-all', { method: 'POST' })
      .then(r => {
        if (!r.ok) return;
        loadNotificationsList();
        loadNotificationsBadge();
      })
      .catch(() => {});
  };

  // 4. Check Auth Status & Adapt Public Headers / Notifications
  function adaptPublicHeader() {
    fetch('/api/auth/status')
      .then(r => (r.ok ? r.json() : null))
      .then(sess => {
        _authSession = {
          authenticated: Boolean(sess && sess.authenticated && sess.user),
          user: (sess && sess.user) || null
        };
        if (_authSession.authenticated) {
          setupHeaderNotifications();
          const userRole = String((_authSession.user && _authSession.user.role) || '').toUpperCase();
          if (userRole === 'ADMIN' && window.location.pathname.startsWith('/console/')) {
            const mainNav = document.querySelector('header nav[aria-label="Main Navigation"]');
            if (mainNav && !mainNav.querySelector('a[href="/console/admin"]')) {
              const adminLink = document.createElement('a');
              adminLink.href = '/console/admin';
              adminLink.className = 'flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors whitespace-nowrap';
              adminLink.innerHTML = '<svg class="w-3.5 h-3.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg><span>Sales &amp; API Onboarding</span>';
              mainNav.appendChild(adminLink);
            }
            const mobileNav = document.querySelector('header nav.sm\\:hidden');
            if (mobileNav && !mobileNav.querySelector('a[href="/console/admin"]')) {
              const mobileAdminLink = document.createElement('a');
              mobileAdminLink.href = '/console/admin';
              mobileAdminLink.className = 'px-3 py-1 rounded-full text-slate-600 whitespace-nowrap';
              mobileAdminLink.textContent = 'Sales & API Onboarding';
              mobileNav.appendChild(mobileAdminLink);
            }
          }
          const loginLink = document.querySelector('header a[href="/login"]');
          if (loginLink) {
            const ctaContainer = loginLink.parentElement;
            const userName = (_authSession.user && _authSession.user.name) || '';
            const initials = userName ? userName.substring(0, 2).toUpperCase() : '--';
            if (ctaContainer) {
              ctaContainer.innerHTML = `
                <a href="/console/new-quote" class="bg-red-600 hover:bg-red-700 text-white font-semibold text-xs px-3.5 py-1.5 rounded-lg transition-colors shadow-xs flex items-center gap-1.5">
                  <span>Go to Console</span>
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/></svg>
                </a>
                <a href="/console/account" class="w-7 h-7 rounded-full bg-red-100 text-red-700 border border-red-200 flex items-center justify-center font-bold text-xs" title="${userName}">
                  ${initials}
                </a>
              `;
            }
          }
        }
      })
      .catch(() => {});
  }

  // Cookie Notice Banner (PIPEDA & ePrivacy Transparency)
  function initCookieNotice() {
    try {
      if (localStorage.getItem('quotelytics_cookie_acknowledged')) return;
    } catch (e) {
      return;
    }
    if (document.getElementById('quotelytics-cookie-notice')) return;

    const banner = document.createElement('div');
    banner.id = 'quotelytics-cookie-notice';
    banner.className = 'fixed bottom-4 inset-x-4 max-w-xl mx-auto z-50 p-4 bg-slate-900 text-white rounded-xl shadow-2xl border border-slate-700 text-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 animate-in fade-in slide-in-from-bottom-3 duration-200';
    banner.innerHTML = `
      <div class="flex items-start gap-2.5">
        <svg class="w-4 h-4 text-slate-500 inline-block" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/></svg>
        <p class="text-slate-300 leading-relaxed text-[11px] sm:text-xs">
          Quotelytics uses only essential, secure session cookies (<code>quotelytics_session</code>) to maintain your login state. We never use third-party advertising or cross-site tracking cookies.
          <a href="/privacy" class="text-red-400 hover:text-red-300 underline ml-1 font-semibold">Privacy Policy</a>
        </p>
      </div>
      <button type="button" id="cookie-notice-dismiss" class="self-end sm:self-center px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white font-bold rounded-lg text-xs whitespace-nowrap transition-colors cursor-pointer shadow-xs">
        Got it
      </button>
    `;
    document.body.appendChild(banner);

    document.getElementById('cookie-notice-dismiss')?.addEventListener('click', function () {
      try {
        localStorage.setItem('quotelytics_cookie_acknowledged', '1');
      } catch (e) {}
      banner.remove();
    });
  }

  // 5. Wire All Footer Links on Page Load
  function wireFooterLinks() {
    injectModals();
    initCookieNotice();

    // Map any footer link text to its respective action
    document.querySelectorAll('footer a').forEach(a => {
      const txt = (a.textContent || '').trim().toLowerCase();
      if (txt === 'documentation') {
        a.href = '/docs';
        a.addEventListener('click', (e) => {
          if (typeof window.openDocsModal === 'function') {
            e.preventDefault();
            window.openDocsModal(e);
          }
        });
      } else if (txt === 'support') {
        a.href = '#support';
        a.addEventListener('click', (e) => {
          if (typeof window.openSupportModal === 'function') {
            e.preventDefault();
            window.openSupportModal(e);
          }
        });
      } else if (txt === 'api') {
        a.href = '/docs';
        a.addEventListener('click', (e) => {
          if (typeof window.openApiModal === 'function') {
            e.preventDefault();
            window.openApiModal(e);
          }
        });
      } else if (txt === 'privacy') {
        a.href = '/privacy';
        a.addEventListener('click', (e) => {
          if (typeof window.openPrivacyModal === 'function') {
            e.preventDefault();
            window.openPrivacyModal(e);
          }
        });
      } else if (txt === 'terms') {
        a.href = '/terms';
      }
    });
  }

  // Escape key dismisses open modals
  window.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      closeDocsModal();
      closeSupportModal();
      closeApiModal();
      closePrivacyModal();
      document.getElementById('rs-notification-popover')?.classList.add('hidden');
    }
  });

  // ==========================================
  // Modern Accessible Toast Notification System
  // Replaces blocking alert() popups across the platform
  // ==========================================
  function ensureToastContainer() {
    let container = document.getElementById('quotelytics-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'quotelytics-toast-container';
      container.setAttribute('aria-live', 'polite');
      container.setAttribute('role', 'status');
      container.className = 'fixed bottom-5 right-5 z-[9999] flex flex-col gap-2.5 max-w-sm w-full pointer-events-none px-4 sm:px-0';
      document.body.appendChild(container);
    }
    return container;
  }

  window.showToast = function (message, type, duration) {
    if (!message) return;
    type = type || 'info';
    duration = duration || 4000;
    const container = ensureToastContainer();
    const toast = document.createElement('div');
    toast.className = 'pointer-events-auto transform transition-all duration-200 ease-out translate-y-2 opacity-0 flex items-start gap-3 p-3.5 rounded-xl shadow-lg border text-xs leading-relaxed backdrop-blur-md';

    let icon = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
    let typeClasses = 'bg-slate-900/95 text-white border-slate-700/80';

    if (type === 'success') {
      icon = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg>';
      typeClasses = 'bg-emerald-900/95 text-emerald-50 border-emerald-700/80';
    } else if (type === 'error') {
      icon = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12"/></svg>';
      typeClasses = 'bg-red-900/95 text-red-50 border-red-700/80';
    } else if (type === 'warning') {
      icon = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/></svg>';
      typeClasses = 'bg-amber-900/95 text-amber-50 border-amber-700/80';
    }

    toast.className += ' ' + typeClasses;
    toast.innerHTML = `
      <span class="w-5 h-5 rounded-full flex items-center justify-center font-bold text-[11px] shrink-0 bg-white/20">${icon}</span>
      <div class="flex-1 font-medium pt-0.5">${message}</div>
      <button type="button" aria-label="Close notification" class="text-white/60 hover:text-white transition-colors cursor-pointer leading-none pl-1" onclick="this.parentElement.remove()"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
    `;

    container.appendChild(toast);

    requestAnimationFrame(function () {
      toast.classList.remove('translate-y-2', 'opacity-0');
      toast.classList.add('translate-y-0', 'opacity-100');
    });

    setTimeout(function () {
      toast.classList.add('opacity-0', 'translate-y-2');
      setTimeout(function () {
        if (toast.parentElement) toast.remove();
      }, 250);
    }, duration);
  };

  // Safe global fallback for any direct alert() calls
  window.nativeAlert = window.alert;
  window.alert = function (msg) {
    const text = String(msg || '');
    let type = 'info';
    if (/error|failed|invalid|exception/i.test(text)) {
      type = 'error';
    } else if (/success|allocated|saved|switched|verified/i.test(text)) {
      type = 'success';
    } else if (/warning|caution|required|notice/i.test(text)) {
      type = 'warning';
    }
    window.showToast(text, type);
  };

  // Run on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      wireFooterLinks();
      adaptPublicHeader();
    });
  } else {
    wireFooterLinks();
    adaptPublicHeader();
  }
})();
