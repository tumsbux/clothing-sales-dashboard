# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Three static, single-file HTML sales dashboards (clothing / เสื้อผ้า, agriculture / เกษตร, herbal medicine / ยาสมุนไพร), each built from the same MySQL "data-lake" source and deployed to its own GitHub Pages site:

| Category | Build dir | Live repo | Pages URL |
|---|---|---|---|
| Clothing (เสื้อผ้า) | `build/` | `tumsbux/clothing-sales-dashboard` | https://tumsbux.github.io/clothing-sales-dashboard/ |
| Agriculture (เกษตร) | `build_agri/` | `tumsbux/agri-sales-dashboard` | https://tumsbux.github.io/agri-sales-dashboard/ |
| Herbal (ยาสมุนไพร) | `build_herb/` | `tumsbux/herb-sales-dashboard` | https://tumsbux.github.io/herb-sales-dashboard/ |

There is no local git repo here — each `build*/` folder is a scratch pipeline dir, and the deployed artifact is uploaded straight to GitHub's web UI (no API token in this environment). `dashboard_<category>.html` / `index_<category>.html` / `index.html` at the top level are copies of the final built dashboard staged for (re-)upload; `agri_reup/` and `herb_reup/` are one-off staging dirs used during renaming-on-upload.

## Build pipeline (per category)

Each `build*/` dir follows the identical pattern:

1. Query the MySQL "data-lake" DB (`fact_sales`, `dim_product`, `dim_branch`, `product_stock_summary`) and dump results to CSVs: `monthly.csv`, `product_desc.csv`, `product_sales.csv`, `product_stock.csv`, `product_monthly.csv`, `dim_branch.csv`, `branch_sales.csv`, `branch_monthly.csv`, `dm_rollup.csv`, `rm_rollup.csv`.
2. `python3 build.py` — reads the CSVs, joins them in-memory, computes `cover_months = onhand / (qty_ytd/19)`, nests `product_monthly.csv`/`branch_monthly.csv` into a per-item `monthly: {ym: {qty, sales}}` map on each product/branch, and writes `data.json`. It also prints verification sums (`sum_branch_sales_ytd`, `sum_product_sales_ytd`, `sum_dm_sales_ytd`, `sum_rm_sales_ytd`, `sum_monthly_sales`) — **these four sums must match** (DM/RM sums are expected to be slightly lower, by exactly the sales total of branches whose code isn't in `dim_branch.csv`, i.e. rows named `(ไม่พบ...)`).
3. `python3 make_html.py` — embeds `data.json` verbatim into a `<script id="dashboard-data" type="application/json">` tag inside a large HTML template string, producing `dashboard.html`. Run in the same directory as `data.json`.
4. Copy `dashboard.html` to `index.html` (GitHub Pages serves `index.html`), then upload both to the repo's `main` branch.

Rebuilding one category from scratch: `cd build_<category> && python3 build.py && python3 make_html.py`. After running `make_html.py`, sanity-check the output before shipping: extract the last `<script>...</script>` block with a small Python regex, write it to a temp `.js` file, and run `node --check` on it — a broken template-string edit will still "build" silently otherwise.

### Category product-set definitions (source of truth: Google Sheet, not igrcode)

As of the month-filter rebuild, agriculture and herbal product lists are sourced from the **Google Sheet** "Project 2026" (`https://docs.google.com/spreadsheets/d/1iuNX8Gu5p0PUnZgfzAJItHUIGjOH-FHFS8rrCFGJjIs`), tab **"สินค้า"**, column **G "กลุ่มย่อย"** (subgroup) — filter rows where `กลุ่มย่อย = เกษตร` or `ยาสมุนไพร`, take column B ("สินค้า") as the barcode. Both subgroups fall under column A "หัวข้อ" = **"2.New category"**. This is NOT the same as filtering MySQL `dim_product.igrcode` — the sheet's "เกษตร" tag spans many different underlying igrcodes (pots, hoses, rope, tanks, socks, lighters, etc.), not just igrcode `18038`. Clothing was intentionally left on the old igrcode-based list (no sheet tag change requested for it).

- Clothing: `dim_product.igrcode = '08015'` — **70 SKUs**, unchanged, still igrcode-based. (User separately listed 16 "new" barcodes for clothing in a later request — all 16 were already present in this 70-SKU list under matching `idesc` values, e.g. `0801500000464` = กางเกงขา6ส่วนผู้หญิง(100). No data change was needed; this was just the user re-tagging them in the Sheet.)
- Agriculture: sheet's กลุ่มย่อย="เกษตร" — **120 SKUs** (116 from the original sheet cross-check, dropping duplicates and 4 unresolvable typo barcodes: `8858874515407`, `8859226800910`, `8859796620600`, `1988321504348`; **+4 more added later** — `1401400000693`, `8852198079113`, `8852198079106`, `8859830695526` — after the user added them to the Sheet and asked for an update. See "Adding individual SKUs incrementally" below for how that was done without a full sheet re-pull.)
- Herbal: sheet's กลุ่มย่อย="ยาสมุนไพร" — **52 SKUs** (all confirmed `igrcode='02038'` in MySQL; one sheet entry, `0900300029`, was missing its leading zero in the raw sheet value `900300029`).

### Adding individual SKUs incrementally (without a full sheet re-pull)

When the user adds a handful of new barcodes to the Sheet and asks to update the live dashboard (rather than a full rebuild), do NOT just append to `product_desc.csv`/`product_sales.csv`/`product_stock.csv`/`product_monthly.csv` and re-run `build.py` — the aggregate CSVs (`monthly.csv`, `branch_sales.csv`, `branch_monthly.csv`, `dm_rollup.csv`, `rm_rollup.csv`) are **pre-aggregated snapshots**, not derived from the product-level files inside `build.py`. Appending only the product-level rows makes `data.json`'s per-product view correct but leaves the branch/DM/RM/monthly rollup totals under-counting the new SKUs' contribution. The correct incremental procedure:

1. Query MySQL for the new `iprod` list only (always with the `sodate >= '2025-01-01'` bound): per-product monthly (`GROUP BY iprod, ym`), per-branch monthly (`GROUP BY sotowhs, ym`), per-branch bill counts (`COUNT(DISTINCT sono) GROUP BY sotowhs`), and per-ym bill counts (`COUNT(DISTINCT sono) GROUP BY ym`) — all filtered to just the new barcodes. Also pull `product_stock_summary` for onhand (`positive_qty_balance_total`) and `unit_cost`, and `dim_product` for `idesc`.
2. Append new rows to `product_desc.csv`, `product_stock.csv`, `product_monthly.csv` (simple appends — these are per-iprod keyed).
3. Compute each new product's `qty_jul`/`sales_jul` (= the latest `ym`'s row) and `qty_ytd`/`sales_ytd` (= sum across all 19 months) and append to `product_sales.csv`.
4. **Merge** (not append) the new per-branch-per-month deltas into `branch_monthly.csv`: for each `(code, ym)` in the delta, add to the existing row if present, else insert a new row.
5. **Increment** `branch_sales.csv`: for each branch code, add the summed delta (`qty_jul`/`sales_jul`/`qty_ytd`/`sales_ytd` from step 1's per-branch-monthly data, plus the delta bill count from step 1) onto the existing branch's row.
6. **Increment** `dm_rollup.csv`/`rm_rollup.csv`: join each branch's delta to `dim_branch.csv` to get its `dm_code`/`rm_code`, then sum deltas per DM/RM and add onto the existing rollup rows. Branches missing from `dim_branch.csv` (shown elsewhere as `(ไม่พบชื่อสาขา ...)`) are silently excluded from DM/RM totals — this is pre-existing pipeline behavior (not a new bug) and only affects a small fraction of total sales.
7. **Increment** `monthly.csv`: add the new products' summed qty/sales per `ym`, plus the delta bill count per `ym` from step 1 (note: bill counts aren't strictly additive across product sets if the same bill contains both an old and new product, but this overlap is negligible in practice and matches the pipeline's existing approximation).
8. Re-run `build.py`, confirm the five verification sums still reconcile (`sum_product_sales_ytd` ≈ `sum_branch_sales_ytd` ≈ `sum_monthly_sales`, with DM/RM slightly lower per the `dim_branch` gotcha).
9. **Do NOT re-run `make_html.py` and ship its output directly** — see the gotcha below, its template has drifted from the live premium dashboard. Instead, patch just the embedded JSON into the existing live-quality `dashboard_<category>.html`.
10. Manually rewrite the affected paragraphs of the AI analysis text (`analysisContent` innerHTML template literal) to cite the new SKU count and updated Top-3/stock-cover/branch-DM-RM figures — this text is static prose, not auto-generated from `data.json`, so it goes stale silently if left untouched (this exact failure mode is what prompted the "SKU ไม่เท่ากัน" bug report after the original 116/52-SKU rebuild).

**Gotcha — `make_html.py`'s template has drifted from the live dashboard:** at least for agriculture, `build_agri/make_html.py` still generates a plain dark-theme shell (no pastel CSS, no month-filter dropdowns, no analysis text, no export buttons) — the actual live `dashboard_เกษตร.html` was hand-patched on top of an older `make_html.py` output and the two have since diverged. **Before regenerating a dashboard from `make_html.py`, diff its output against the live file** (e.g. `grep -c "monthSelectProd\|pastel\|analysisContent"` on both) — if the counts differ, do NOT ship the fresh `make_html.py` output; instead extract just the new `data.json` and splice it into the existing live HTML's `<script id="dashboard-data" type="application/json">` block via a Python regex substitution, leaving everything else untouched.

When re-pulling these lists from the sheet, watch for leading-zero inconsistencies (`0304000006` vs `304000006` — same product, sheet has both forms) and outright typos (extra/missing digits) — cross-check every candidate against `dim_product.iprod` with `SELECT iprod, idesc, igrcode, igrdesc FROM dim_product WHERE iprod IN (...)` and treat unmatched codes as suspect rather than assuming they're valid-but-unsold.

### Known-good MySQL columns (verified against actual schema — don't trust older assumptions)

- `fact_sales`: `sono, soserlno, iprod, sodate, cstcode, soqty, retqty, net_qty, sopricunit, sopricamt, sopricdisc, solineamt, socstunit, total_cost, untcode, sotowhs, soretflag, ...`. Composite index `idx_optimize_sales_report` on `(sodate, sotowhs, iprod)` — a 40M+ row table, so **always** include a `sodate >= '2025-01-01'` bound in WHERE clauses that also filter by `iprod IN (...)`, or the query will likely time out even for read-only aggregates.
- `dim_branch`: `code, name, dm_code, dm, rm_code, rm`
- `product_stock_summary`: has no `onhand` column directly — compute as `positive_qty_balance_total - negative_qty_balance_total`.

**Gotcha — MySQL tool timeouts:** even with the `sodate` bound, `mcp__mysql__execute_sql` occasionally times out on heavier `GROUP BY` aggregates (e.g. product-month or branch-month rollups over 100+ `iprod` values) for no obvious reason — just retry the identical query once or twice, it usually goes through. If a result is too large to return inline, the tool auto-saves it to a local file and tells you the path; that path is readable via the `Read` tool in chunks (~2222 lines at a time via offset/limit) — use that instead of re-querying with `LIMIT`.

## Dashboard HTML structure (all 3 files are structurally identical)

Each `dashboard.html` has one `<script>` JS block driving render functions off the embedded `DATA` object: `renderKPI()`, `renderTrend()` (Chart.js line chart), `renderProdTable()`, `renderBranchTable()`, and `renderRollupTable(elId, list, nameKey)` (shared by DM/RM tables). Sort/filter state is plain JS globals (`prodSort`, `branchSort`) wired via `attachSort()`.

**Month filter:** the product and branch table sections each have a `<select id="monthSelectProd">` / `<select id="monthSelectBranch">` (populated from all `ym` keys present in `DATA.monthly`, labeled in Thai Buddhist-year format e.g. "ม.ค. 2568", defaulting to the latest month) sitting alongside the existing "สะสม YTD" toggle button. Selecting a month reads `product.monthly[ym]` / `branch.monthly[ym]` (0 if that item had no sales that month); the YTD button still sums across all months as before. DM/RM rollup tables were deliberately left without a month selector — they only ever show jul(latest)+ytd columns side by side, no toggle, so there was nothing to wire up there.

Every dashboard has export functionality on each section (product/branch/DM/RM/analysis): `exportExcel(tableId, filename)` (SheetJS `XLSX.utils.table_to_book` + `writeFile`) and `exportPDF(sectionId)` (adds a `.print-target` class + `window.print()`, gated by an `@media print` rule that hides everything else). Each section's outer `<div class="section">` needs a matching `id` (`prodSection`, `branchSection`, `dmSection`, `rmSection`, `analysisSection`) for `exportPDF()` to find it.

**Gotcha:** the clothing dashboard was originally built before the export feature existed and needed retrofitting (SheetJS `<script>` include, `.btn-export`/`@media print` CSS, section `id`s, button markup, and the two JS functions) to reach parity with agri/herb. When touching any dashboard, verify all three still have matching export functionality — 9 buttons total: Excel+PDF on 4 sections + PDF-only on analysis.

**Gotcha:** the `<script id="dashboard-data">` line containing the embedded JSON is enormous (tens of thousands of chars on one line) and will blow up token-limited line-range reads. When inspecting a dashboard file, first run `awk '{print NR": "length($0)}' file | sort -t: -k2 -nr | head -5` to find that line number and explicitly avoid it in any `sed -n` range.

**Gotcha:** Chart.js colors are hardcoded hex strings inside the JS (`borderColor`, `ticks.color`, `grid.color`, etc.) — they are **not** derived from the `:root` CSS variables. Changing the CSS theme alone does not reskin the chart; the JS block's hex literals must be edited too.

### Pastel theme (all 3 already applied)

Each dashboard keeps the same CSS variable names but different pastel values:

- Clothing (rose): `--bg:#fdf7f9; --accent:#e08bab; --border:#f3dde6;` etc.
- Agriculture (sage): `--bg:#f7faf5; --accent:#7cae6b; --border:#dfeed8;` etc.
- Herbal (teal/mint): `--bg:#faf8fc; --accent:#5eb8a7; --border:#e6dff0;` etc.

`--green`, `--red`, `--yellow` (`#74c69d` / `#e8879a` / `#e8c468`) and badge rgba backgrounds are shared across all three.

## Deploying to GitHub (no API token — browser automation only)

Upload via `https://github.com/<owner>/<repo>/upload/main`, drop/select both `dashboard_<category>.html` and `index.html`, then commit. **Check the repo's file listing first** (e.g. `github.com/<owner>/<repo>` root) — some repos (agri) also carry a same-content `index_<category>.html` (e.g. `index_agri.html`) as a separate tracked file from an earlier rename-on-upload step; if present, it must be uploaded/committed alongside the other two or it'll silently keep serving stale content to anyone who links to it directly.

**Commit button bug:** clicking the "Commit changes" submit button by screen coordinates is unreliable — it can land on the "Create a new branch for this commit" radio instead (silently flipping the button to "Propose changes" / opening a PR flow instead of committing to main). Reliable sequence:
1. `find` the "Commit directly to the main branch" radio and click it **by element ref**, not coordinates.
2. `find` the "Commit changes" submit button fresh and click **by ref**.
3. If it still doesn't navigate away, fall back to JS: `document.querySelectorAll('button[type="submit"]')`, find the one whose `textContent.trim() === 'Commit changes'`, and call `.click()` directly.

To rename an uploaded file (e.g. `index_herb.html` → `index.html`) without overwriting, use GitHub's web editor at `/edit/main/<filename>`, change the filename field, then commit.

GitHub Pages source is already configured on all 3 repos: Settings → Pages → Deploy from a branch → `main` / `(root)`. No further config needed unless a new repo is created.

After pushing, GitHub Pages/CDN can lag behind the raw file by several seconds — if a live check via `tumsbux.github.io/...` doesn't show a change, confirm the change actually landed by checking `raw.githubusercontent.com/<owner>/<repo>/main/<file>` first, then retry the Pages URL with a cache-busting `?v=` query param.

## Formatting conventions used throughout

- Dates: `dd-mm-yyyy`.
- Numbers: right-aligned, thousands-comma-separated.
- Text: left-aligned.
- Product identifier: `dim_product.iprod` (= `fact_sales.iprod`) is the canonical barcode field, labeled **"Parcode"** in all UI/table headers — not "barcode" or "iprod".

## Scheduled auto-refresh

A daily 9am refresh (`sales-dashboards-daily-refresh`, cron `0 9 * * *`) re-queries MySQL and patches only the embedded `<script id="dashboard-data">` JSON in each live dashboard (fetched via raw.githubusercontent.com) rather than regenerating the whole HTML file, then re-pushes using the commit-button workflow above. It's defined to run fully unattended (no clarifying questions), fail loudly on any mismatch rather than partially update, and never create new repos.

**Note:** this Claude-scheduled task is now DISABLED — it was replaced by a real **GitHub Actions workflow** (`.github/workflows/refresh.yml` + `scripts/refresh_dashboard.py`) committed independently into each of the 3 repos, which runs on GitHub's infrastructure (cron `10 2 * * *` = 09:10 Bangkok daily) regardless of whether this laptop/session is open. That workflow is the one actually keeping the dashboards fresh day-to-day.

### GitHub Actions auto-refresh (`scripts/refresh_dashboard.py`) — how it works and a gotcha found 2026-07-21

Each repo's script connects to MySQL directly (via `pymysql`, using `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASSWORD`/`DB_NAME` repo secrets), re-queries sales, and **only replaces the `<script id="dashboard-data">` JSON block** inside the existing `index.html` template (then also writes the result to `dashboard_<category>.html`) — it does not touch CSS, JS, or the analysis text, so those stay whatever was last hand-patched.

- `PRODUCT_FILTER_SQL` is the single source of truth for which products a category includes. Clothing's is `p.igrcode = '08015'` (correct — clothing is intentionally igrcode-based). Herb and agri's should be a **fixed `p.iprod IN (...)` allowlist** matching the current Sheet-derived product list, not an igrcode filter (the Sheet's subgroup tags span many different igrcodes).
- **Bug found and fixed 2026-07-21:** agri's `PRODUCT_FILTER_SQL` had drifted back to the old `p.igrcode = '18038'` filter (a leftover from before the Sheet-based rebuild) even though the live dashboard had already been manually updated to the correct 120-SKU list. Left alone, the next scheduled run (09:10 Bangkok) would have silently overwritten the live dashboard's data with the old ~32-SKU igrcode-filtered dataset. Fixed by editing `scripts/refresh_dashboard.py` in the agri repo to use the same fixed-IN-list pattern as herb's script, with all 120 current agri barcodes.
- **Whenever the product list for agri or herb changes (Sheet re-pull, or individual SKUs added per the incremental workflow above), the corresponding `PRODUCT_FILTER_SQL` inside `scripts/refresh_dashboard.py` in that repo must be updated to match** — the dashboard's `data.json`/embedded JSON and the refresh script's product filter are two independent sources that can silently diverge if only one is updated. Check this any time the product list changes.

**Incremental cache gotcha — `data_archive.json`:** to keep each run fast, the script only live-queries the current month + `FRESH_MONTH_COUNT` (2) prior months; everything older is cached in `data_archive.json` (committed to the repo) and never re-queried once archived. This means **if `PRODUCT_FILTER_SQL` changes (or the product list grows/shrinks), the archive still holds the OLD product set's numbers for all older months** — the next run merges correct fresh months with stale archived months, silently under-reporting history for any newly added product and for the trend chart / YTD sums. Found this exact problem 2026-07-21: agri's archive only had 32 products cached (missing the current top-seller and all 4 newly-added SKUs), herb's had 46 of 52, and even clothing's (which never changed its igrcode filter) had only 52 of 70 — all three were stale. **Fix: reset `data_archive.json` to `{"prod_monthly":{},"branch_monthly":{},"branch_bills":{},"monthly_totals":{}}` (upload via the browser workflow, same as any other file) any time the product filter changes, or as a periodic sanity check** — an empty/missing archive just makes the next run do a full clean 19-month requery instead of an incremental one (slower that one run, but correct), and the script re-populates the archive with correct data from then on. To check whether an archive is stale without waiting for a bad dashboard render: fetch `data_archive.json` raw, `Object.keys(d.prod_monthly).length` and compare to the live dashboard's actual product count.
