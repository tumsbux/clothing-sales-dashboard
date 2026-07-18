# -*- coding: utf-8 -*-
"""
Refresh embedded sales data in index.html / dashboard_เสื้อผ้า.html from MySQL "data-lake",
then leave the files ready for the workflow to commit & push.

Category: เสื้อผ้า (clothing)
Product filter: dim_product.igrcode = '08015'

Required environment variables (set as GitHub Actions repo secrets):
  DB_HOST, DB_PORT (default 3306), DB_USER, DB_PASSWORD, DB_NAME (default "data-lake")
"""
import os, re, json, datetime
import pymysql

DB_HOST = os.environ['DB_HOST']
DB_PORT = int(os.environ.get('DB_PORT', '3306'))
DB_USER = os.environ['DB_USER']
DB_PASSWORD = os.environ['DB_PASSWORD']
DB_NAME = os.environ.get('DB_NAME', 'data-lake')

DASHBOARD_FILE = 'dashboard_เสื้อผ้า.html'
PRODUCT_FILTER_SQL = "p.igrcode = '08015'"
START_YM = '2025-01'

conn = pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
                        database=DB_NAME, charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)


def month_range(start_ym):
    today = datetime.date.today()
    y, m = int(start_ym[:4]), int(start_ym[5:7])
    out = []
    while (y, m) <= (today.year, today.month):
        out.append(f'{y:04d}-{m:02d}')
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def month_bounds(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    start = f'{y:04d}-{m:02d}-01'
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    end = f'{ny:04d}-{nm:02d}-01'
    return start, end


months = month_range(START_YM)
latest_ym = months[-1]
n_months = len(months)

prod_desc = {}
branch_meta = {}
stock = {}
prod_monthly = {}      # iprod -> {ym: {qty, sales}}
branch_monthly = {}    # code  -> {ym: {qty, sales}}
branch_bills = {}      # code  -> {ym: bills}
monthly_totals = {}    # ym -> {qty, sales, bills}

with conn.cursor() as cur:
    cur.execute(f"SELECT iprod, idesc FROM dim_product WHERE {PRODUCT_FILTER_SQL}")
    for r in cur.fetchall():
        prod_desc[r['iprod']] = r['idesc']

    cur.execute("SELECT code, name, dm_code, dm, rm_code, rm FROM dim_branch")
    for r in cur.fetchall():
        branch_meta[r['code']] = r

    iprod_list = list(prod_desc.keys())
    if iprod_list:
        placeholders = ','.join(['%s'] * len(iprod_list))
        cur.execute(
            f"SELECT iprod, positive_qty_balance_total, negative_qty_balance_total, unit_cost "
            f"FROM product_stock_summary WHERE iprod IN ({placeholders})",
            iprod_list,
        )
        for r in cur.fetchall():
            stock[r['iprod']] = r

    for ym in months:
        start, end = month_bounds(ym)

        cur.execute(
            f"SELECT f.iprod, SUM(f.net_qty) qty, SUM(f.net_sales_amt) sales "
            f"FROM fact_sales f INNER JOIN dim_product p ON p.iprod=f.iprod AND {PRODUCT_FILTER_SQL} "
            f"WHERE f.sodate >= %s AND f.sodate < %s GROUP BY f.iprod",
            (start, end),
        )
        for r in cur.fetchall():
            prod_monthly.setdefault(r['iprod'], {})[ym] = {
                'qty': float(r['qty'] or 0), 'sales': round(float(r['sales'] or 0), 2)
            }

        cur.execute(
            f"SELECT f.sotowhs, SUM(f.net_qty) qty, SUM(f.net_sales_amt) sales, COUNT(DISTINCT f.sono) bills "
            f"FROM fact_sales f INNER JOIN dim_product p ON p.iprod=f.iprod AND {PRODUCT_FILTER_SQL} "
            f"WHERE f.sodate >= %s AND f.sodate < %s GROUP BY f.sotowhs",
            (start, end),
        )
        m_qty = m_sales = 0.0
        for r in cur.fetchall():
            code = r['sotowhs']
            branch_monthly.setdefault(code, {})[ym] = {
                'qty': float(r['qty'] or 0), 'sales': round(float(r['sales'] or 0), 2)
            }
            branch_bills.setdefault(code, {})[ym] = r['bills']
            m_qty += float(r['qty'] or 0)
            m_sales += float(r['sales'] or 0)

        cur.execute(
            f"SELECT COUNT(DISTINCT f.sono) bills FROM fact_sales f "
            f"INNER JOIN dim_product p ON p.iprod=f.iprod AND {PRODUCT_FILTER_SQL} "
            f"WHERE f.sodate >= %s AND f.sodate < %s",
            (start, end),
        )
        m_bills = cur.fetchone()['bills']
        monthly_totals[ym] = {'qty': round(m_qty, 2), 'sales': round(m_sales, 2), 'bills': m_bills}

conn.close()

products = []
for iprod, idesc in prod_desc.items():
    m = prod_monthly.get(iprod, {})
    qty_ytd = round(sum(v['qty'] for v in m.values()), 2)
    sales_ytd = round(sum(v['sales'] for v in m.values()), 2)
    s = stock.get(iprod, {})
    onhand = float(s.get('positive_qty_balance_total', 0) or 0) - float(s.get('negative_qty_balance_total', 0) or 0)
    unit_cost = float(s.get('unit_cost', 0) or 0)
    cover = round(onhand / (qty_ytd / n_months), 2) if qty_ytd else None
    latest = m.get(latest_ym, {})
    products.append({
        'iprod': iprod, 'idesc': idesc,
        'qty_jul': latest.get('qty', 0), 'sales_jul': latest.get('sales', 0),
        'qty_ytd': qty_ytd, 'sales_ytd': sales_ytd,
        'onhand': onhand, 'unit_cost': unit_cost, 'cover_months': cover,
        'monthly': m,
    })

branches = []
for code, m in branch_monthly.items():
    meta = branch_meta.get(code)
    if not meta or not meta.get('name'):
        continue  # unmapped / non-retail channel code — drop
    qty_ytd = round(sum(v['qty'] for v in m.values()), 2)
    sales_ytd = round(sum(v['sales'] for v in m.values()), 2)
    bills_ytd = sum(branch_bills.get(code, {}).values())
    latest = m.get(latest_ym, {})
    branches.append({
        'code': code, 'name': meta['name'], 'dm': meta['dm'], 'dm_code': meta['dm_code'],
        'rm': meta['rm'], 'rm_code': meta['rm_code'],
        'qty_jul': latest.get('qty', 0), 'sales_jul': latest.get('sales', 0),
        'qty_ytd': qty_ytd, 'sales_ytd': sales_ytd, 'bills_ytd': bills_ytd,
        'monthly': m,
    })

dm_roll, rm_roll = {}, {}
for b in branches:
    dk = (b['dm_code'], b['dm'])
    d = dm_roll.setdefault(dk, {'dm_code': b['dm_code'], 'dm': b['dm'], 'qty_jul': 0, 'sales_jul': 0, 'qty_ytd': 0, 'sales_ytd': 0})
    d['qty_jul'] += b['qty_jul']; d['sales_jul'] += b['sales_jul']
    d['qty_ytd'] += b['qty_ytd']; d['sales_ytd'] += b['sales_ytd']
    rk = (b['rm_code'], b['rm'])
    r = rm_roll.setdefault(rk, {'rm_code': b['rm_code'], 'rm': b['rm'], 'qty_jul': 0, 'sales_jul': 0, 'qty_ytd': 0, 'sales_ytd': 0})
    r['qty_jul'] += b['qty_jul']; r['sales_jul'] += b['sales_jul']
    r['qty_ytd'] += b['qty_ytd']; r['sales_ytd'] += b['sales_ytd']

for r in list(dm_roll.values()) + list(rm_roll.values()):
    for k in ('qty_jul', 'sales_jul', 'qty_ytd', 'sales_ytd'):
        r[k] = round(r[k], 2)

data = {
    'monthly': [{'ym': ym, **monthly_totals[ym]} for ym in months],
    'products': products,
    'branches': branches,
    'dm': list(dm_roll.values()),
    'rm': list(rm_roll.values()),
}

compact = json.dumps(data, ensure_ascii=False, separators=(',', ':'))

pattern = re.compile(r'(<script id="dashboard-data" type="application/json">)(.*?)(</script>)', re.S)
tpl = open('index.html', encoding='utf-8').read()
m = pattern.search(tpl)
assert m, 'dashboard-data script tag not found in index.html'
final = pattern.sub(lambda mo: mo.group(1) + compact + mo.group(3), tpl, count=1)

open('index.html', 'w', encoding='utf-8').write(final)
open(DASHBOARD_FILE, 'w', encoding='utf-8').write(final)

print(f"Refreshed {len(products)} products, {len(branches)} branches, "
      f"{len(months)} months ({months[0]}..{months[-1]}).")
print(f"YTD sales check: products={sum(p['sales_ytd'] for p in products):.2f} "
      f"monthly_series={sum(x['sales'] for x in data['monthly']):.2f}")
