# CLAUDE.md

## What this repo is
Static, single-file GitHub Pages sales dashboard for the **เสื้อผ้า** (clothing) product category. No backend, no build step. All data lives inline in `<script id="dashboard-data" type="application/json">...</script>` inside `index.html`; the page's own JS reads `DATA` from that tag at load time and renders KPIs, a trend chart, a product table, a branch table, and DM/RM rollups.

`index.html` and `dashboard_เสื้อผ้า.html` must always be **byte-identical** — both get overwritten on every refresh.

## Data source
MySQL database `data-lake`, table `fact_sales` (~41M rows), filtered to this category via ``dim_product.igrcode = '08015'``.

### CRITICAL: query fact_sales one month at a time
Any query against `fact_sales` spanning more than ~1 calendar month of `sodate` range times out (proven repeatedly). Always scope `WHERE sodate >= 'YYYY-MM-01' AND sodate < 'next-month-01'` and loop month by month. Also **never batch multiple `mysql.execute_sql` calls in one message** — parallel/batched calls contend against each other and time out even when each individual query would be fast alone. One call, wait for the result, then the next.

## JSON shape the dashboard actually needs
```json
{
  "monthly": [{"ym":"2025-01","qty":0,"sales":0,"bills":0}, ...19 months, used by the trend chart and top KPI cards...],
  "products": [{"iprod":"...","idesc":"...","qty_jul":0,"sales_jul":0,"qty_ytd":0,"sales_ytd":0,"onhand":0,"unit_cost":0,"cover_months":0,
                 "monthly": {"2025-01":{"qty":0,"sales":0}, ... one entry per month ...}}],
  "branches": [{"code":"...","name":"...","dm":"...","dm_code":"...","rm":"...","rm_code":"...","qty_jul":0,"sales_jul":0,"qty_ytd":0,"sales_ytd":0,"bills_ytd":0,
                 "monthly": {"2025-01":{"qty":0,"sales":0}, ...}}],
  "dm": [...], "rm": [...]
}
```

### CRITICAL — do not skip the `monthly` breakdown on products/branches
The product table and branch table both default to a **"month" view** (the "ก.ค. 2569 (ล่าสุด)" dropdown, NOT the YTD toggle). That view is driven by `p.monthly[selectedYm]` / `b.monthly[selectedYm]` in the page JS (`prodValue()` / `branchValue()`). If a product or branch object is missing the `monthly` map, the JS silently falls back to `{qty:0, sales:0}` — every row in the default table view renders as 0.00 even though YTD/KPI totals look correct. **This exact bug shipped on 2026-07-18** because the JSON only carried aggregate `qty_jul`/`qty_ytd` fields, not a per-month breakdown. Root cause + fix: see commit history around that date.

To avoid re-breaking this: always derive `qty_ytd` / `sales_ytd` / `qty_jul` / `sales_jul` **from** the `monthly` map (sum across months / look up the latest month) rather than computing them independently — this guarantees the KPI cards, the YTD table view, and the month table view can never disagree.

## Date labels are computed dynamically — never hardcode
The subtitle line, the "ยอดขาย ก.ค. 2569 (ถึง N ก.ค.)" KPI label, the growth-YoY label, and the `.note` div under the trend chart are all computed in `renderKPI()` from `new Date()` minus one day ("current − 1", since `fact_sales` is loaded through yesterday). **Do not hand-edit a literal date string into these** — that caused a second bug (a permanently stuck "15-07-2026" label) also fixed on 2026-07-18. If you need to change the wording, edit the template-literal logic in `renderKPI()`, not a static string.

## Refresh workflow
1. **Fetch the current live template.** `raw.githubusercontent.com` and `api.github.com` are blocked by this sandbox's outbound proxy — only `github.com` itself is reachable. Fetch `https://github.com/tumsbux/clothing-sales-dashboard/blob/main/index.html?plain=1` via curl/bash, then extract `payload["codeViewBlobLayoutRoute.StyledBlob"]["rawLines"]` from the `<script type="application/json" data-target="react-app.embeddedData">` tag and join with `\n` — that's the exact live file content, no auth needed (repo is public).
2. **Splice, don't rewrite.** Replace only the contents of `<script id="dashboard-data" type="application/json">...</script>` with the new JSON. Every other byte (CSS, chart config, table renderers, export buttons, AI analysis prose) stays untouched.
3. Save the result locally as **both** `dashboard_เสื้อผ้า.html` and `index.html` (identical content, both filenames).
4. **Push via GitHub's web upload UI** (Claude-in-Chrome browser tools), not git/API:
   - Navigate to `https://github.com/tumsbux/clothing-sales-dashboard/upload/main`.
   - Find the "Choose your files" file input and use the `file_upload` MCP tool with both local file paths. Do **not** try to attach files via JS `DataTransfer` + setting `input.files` — GitHub's upload input has a framework-managed setter that silently no-ops on programmatic assignment; only the CDP-level `file_upload` tool actually works.
   - **Before committing, screenshot and count the staged files** — the input is `multiple`, and repeated `file_upload` calls (e.g. after a retry) can accumulate duplicates instead of replacing the selection. You need exactly 2 files staged; remove extras with the × button.
   - Find "Commit changes" **fresh** each time via the `find` tool and click by `ref` — raw x/y coordinate clicks have previously mis-hit the "create a new branch" radio button instead of the commit button.
   - Confirm the tab title changes from `"Upload files · tumsbux/clothing-sales-dashboard"` to the repo's default title — that's the signal the commit landed on `main`.
5. **GitHub Pages can lag 15–30+ seconds** after a commit before the new build is live, longer than it might seem. Wait, then verify at `https://tumsbux.github.io/clothing-sales-dashboard/?v=<cache-busting-string>`. Check not just the KPI cards but **scroll down and check the product/branch tables in their default "month" view** — that's where the `monthly`-breakdown bug hid on 2026-07-18 while the KPIs looked fine.

## Known environment gotchas
- `mcp__workspace__web_fetch` refuses any URL not already present in the conversation (its "provenance set") — use the Claude-in-Chrome browser or the blob-page-scraping curl trick above instead of fighting it.
- Do not attempt to route around `web_fetch`/proxy restrictions with raw `curl`/`requests` to blocked domains — respect the block and use the sanctioned paths above.
