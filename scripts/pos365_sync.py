#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POS365 SYNC ENGINE — FNBOPS
Synchronizes sales orders, products, categories, users, and daily revenue
from POS365 into SQLite database.
"""

import sys
import os
import re
import json
import time
import sqlite3
import argparse
import urllib.request
import urllib.parse
import http.cookiejar
from datetime import datetime, timezone, timedelta

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.getenv("DATABASE_PATH", os.path.join(_ROOT_DIR, "data", "fnbop.db"))
EXPORT_DIR = os.getenv("POS365_EXPORT_DIR", os.path.join(_ROOT_DIR, "data", "pos365"))
BASE_URL = os.getenv("POS365_URL", "https://your-store.pos365.vn")
USERNAME = os.getenv("POS365_USER", "")
PASSWORD = os.getenv("POS365_PASS", "")

def get_opener():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    return opener

def login(opener):
    # 1. Fetch token
    req = urllib.request.Request(f"{BASE_URL}/Signin", headers={"User-Agent": "Mozilla/5.0"})
    with opener.open(req) as res:
        html = res.read().decode("utf-8", errors="ignore")
    
    m = re.search(r'name=\"__RequestVerificationToken\"\s+type=\"hidden\"\s+value=\"([^\"]+)\"', html)
    if not m:
        raise ValueError("Cannot extract __RequestVerificationToken from Signin page")
    token = m.group(1)

    # 2. Post login
    data = urllib.parse.urlencode({
        "Username": USERNAME,
        "Password": PASSWORD,
        "loginsButton": "Dashboard",
        "__RequestVerificationToken": token
    }).encode("utf-8")

    login_req = urllib.request.Request(
        f"{BASE_URL}/Signin",
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"{BASE_URL}/Signin",
            "Origin": BASE_URL
        }
    )
    with opener.open(login_req) as res:
        final_url = res.geturl()
    
    if "Signin" in final_url:
        raise PermissionError("Login failed — redirected back to Signin page.")
    return True

def fetch_json(opener, endpoint):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req) as res:
        return json.loads(res.read().decode("utf-8"))

def init_tables(conn):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pos_categories (
        id INTEGER PRIMARY KEY,
        name TEXT,
        sync_at TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pos_products (
        id INTEGER PRIMARY KEY,
        code TEXT,
        name TEXT,
        category_id INTEGER,
        price REAL,
        unit TEXT,
        sync_at TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pos_users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        name TEXT,
        sync_at TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pos_orders (
        id INTEGER PRIMARY KEY,
        code TEXT UNIQUE,
        purchase_date TEXT,
        purchase_date_vn TEXT,
        branch_id INTEGER,
        status INTEGER,
        total REAL,
        total_payment REAL,
        discount REAL,
        excess_cash REAL,
        sold_by_id INTEGER,
        cashier_name TEXT,
        created_by INTEGER,
        num_guests INTEGER,
        pos TEXT,
        cash_amount REAL,
        bank_amount REAL,
        raw_json TEXT,
        sync_at TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pos_order_items (
        id INTEGER PRIMARY KEY,
        order_id INTEGER,
        product_id INTEGER,
        product_code TEXT,
        product_name TEXT,
        category_id INTEGER,
        quantity REAL,
        price REAL,
        final_unit_price REAL,
        unit TEXT,
        sync_at TEXT,
        FOREIGN KEY (order_id) REFERENCES pos_orders(id)
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pos_daily_summary (
        date TEXT PRIMARY KEY,
        total_revenue REAL,
        total_orders INTEGER,
        total_guests INTEGER,
        avg_order_value REAL,
        cash_amount REAL,
        bank_amount REAL,
        cancelled_orders INTEGER,
        updated_at TEXT
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pos_orders_date ON pos_orders (purchase_date_vn);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pos_orders_soldby ON pos_orders (sold_by_id);")
    conn.commit()

def to_vn_time(utc_iso_str):
    if not utc_iso_str:
        return ""
    try:
        # e.g. 2026-09-21T05:54:01.4630000Z
        clean_str = utc_iso_str[:19]
        dt = datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        vn_dt = dt.astimezone(timezone(timedelta(hours=7)))
        return vn_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_iso_str

def parse_payment_methods(more_attr_str, total_payment):
    cash = 0.0
    bank = 0.0
    if not more_attr_str:
        return total_payment, 0.0
    try:
        data = json.loads(more_attr_str)
        pms = data.get("PaymentMethods", [])
        if not pms:
            return total_payment, 0.0
        for pm in pms:
            val = float(pm.get("Value", 0.0))
            aid = pm.get("AccountId")
            if aid is None or aid == 0:
                cash += val
            else:
                bank += val
        return cash, bank
    except Exception:
        return total_payment, 0.0

def sync_catalogs(opener, conn):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()

    # 1. Categories
    try:
        cats = fetch_json(opener, "/api/categories?format=json").get("results", [])
        for c in cats:
            cur.execute("""
            INSERT INTO pos_categories (id, name, sync_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name, sync_at=excluded.sync_at;
            """, (c.get("Id"), c.get("Name"), now_str))
    except Exception as e:
        print(f"[WARN] Failed to sync categories: {e}")

    # 2. Products
    try:
        prods = fetch_json(opener, "/api/products?format=json&top=500").get("results", [])
        for p in prods:
            cur.execute("""
            INSERT INTO pos_products (id, code, name, category_id, price, unit, sync_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                code=excluded.code, name=excluded.name, category_id=excluded.category_id,
                price=excluded.price, unit=excluded.unit, sync_at=excluded.sync_at;
            """, (p.get("Id"), p.get("Code"), p.get("Name"), p.get("CategoryId"), p.get("Price"), p.get("Unit"), now_str))
    except Exception as e:
        print(f"[WARN] Failed to sync products: {e}")

    # 3. Users / Cashiers
    user_map = {}
    try:
        usrs = fetch_json(opener, "/api/users?format=json").get("results", [])
        for u in usrs:
            uid = u.get("Id")
            uname = u.get("UserName", "")
            disp = u.get("Name") or uname
            user_map[uid] = disp
            cur.execute("""
            INSERT INTO pos_users (id, username, name, sync_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                username=excluded.username, name=excluded.name, sync_at=excluded.sync_at;
            """, (uid, uname, disp, now_str))
    except Exception as e:
        print(f"[WARN] Failed to sync users: {e}")

    conn.commit()
    return user_map

def sync_orders(opener, conn, user_map, backfill=False, fetch_items=False, items_limit=300):
    cur = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    skip = 0
    top = 100
    total_synced = 0
    cutoff_date_str = "2026-05-01"

    print(f"=== [START] Syncing POS365 Orders (Backfill: {backfill}, Items: {fetch_items}, Limit: {items_limit}) ===")

    while True:
        url = f"/api/orders?format=json&top={top}&skip={skip}"
        try:
            res = fetch_json(opener, url)
        except Exception as e:
            print(f"[ERROR] Fetch orders at skip={skip} failed: {e}")
            break

        results = res.get("results", [])
        if not results:
            break

        for o in results:
            oid = o.get("Id")
            code = o.get("Code")
            p_date_raw = o.get("PurchaseDate", "")
            p_date_vn = to_vn_time(p_date_raw)
            total_pay = float(o.get("TotalPayment", 0.0))
            cash, bank = parse_payment_methods(o.get("MoreAttributes"), total_pay)
            sold_by = o.get("SoldById")
            cashier = user_map.get(sold_by, str(sold_by))

            cur.execute("""
            INSERT INTO pos_orders (
                id, code, purchase_date, purchase_date_vn, branch_id, status,
                total, total_payment, discount, excess_cash, sold_by_id,
                cashier_name, created_by, num_guests, pos, cash_amount,
                bank_amount, raw_json, sync_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                total=excluded.total,
                total_payment=excluded.total_payment,
                discount=excluded.discount,
                cash_amount=excluded.cash_amount,
                bank_amount=excluded.bank_amount,
                cashier_name=excluded.cashier_name,
                sync_at=excluded.sync_at;
            """, (
                oid, code, p_date_raw, p_date_vn, o.get("BranchId"), o.get("Status"),
                float(o.get("Total", 0.0)), total_pay, float(o.get("Discount", 0.0)),
                float(o.get("ExcessCash", 0.0)), sold_by, cashier, o.get("CreatedBy"),
                int(o.get("NumberOfGuests") or 1), o.get("Pos"), cash, bank,
                json.dumps(o, ensure_ascii=False), now_str
            ))
            total_synced += 1

            if fetch_items and total_synced <= items_limit:
                cur.execute("SELECT 1 FROM pos_order_items WHERE order_id = ? LIMIT 1", (oid,))
                if not cur.fetchone():
                    try:
                        detail_url = f"/api/orders/detail?format=json&Includes=Product&IncludeSummary=false&OrderId={oid}"
                        dres = fetch_json(opener, detail_url)
                        d_items = dres.get("results", [])
                        for itm in d_items:
                            iid = itm.get("Id")
                            pid = itm.get("ProductId")
                            prod = itm.get("Product") or {}
                            pname = prod.get("Name", "")
                            pcode = prod.get("Code", "")
                            cid = prod.get("CategoryId", 0)
                            qty = float(itm.get("Quantity", 1.0))
                            price = float(itm.get("Price", 0.0))
                            fprice = float(itm.get("FinalUnitPrice", price))
                            unit = itm.get("Unit") or prod.get("Unit", "Ly")

                            cur.execute("""
                            INSERT INTO pos_order_items (
                                id, order_id, product_id, product_code, product_name,
                                category_id, quantity, price, final_unit_price, unit, sync_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(id) DO UPDATE SET
                                quantity=excluded.quantity,
                                price=excluded.price,
                                final_unit_price=excluded.final_unit_price,
                                sync_at=excluded.sync_at;
                            """, (iid, oid, pid, pcode, pname, cid, qty, price, fprice, unit, now_str))
                    except Exception as de:
                        pass

        conn.commit()
        last_date = results[-1].get("PurchaseDate", "")[:10]
        print(f"  -> Synced batch skip={skip}, items={len(results)}. Oldest in batch: {last_date}")

        if not backfill:
            if fetch_items:
                if total_synced >= items_limit:
                    print(f"  -> Reached items limit ({total_synced}/{items_limit}). Stopping order sync.")
                    break
            else:
                two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
                if last_date < two_days_ago:
                    break
        else:
            if last_date < cutoff_date_str:
                print(f"  -> Reached cutoff date {cutoff_date_str}. Stopping backfill.")
                break

        skip += top
        time.sleep(0.1)

    print(f"=== [DONE] Synced {total_synced} orders into pos_orders table. ===")

def update_daily_summary(conn):
    cur = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Aggregate by date (YYYY-MM-DD from purchase_date_vn)
    cur.execute("""
    INSERT INTO pos_daily_summary (
        date, total_revenue, total_orders, total_guests, avg_order_value,
        cash_amount, bank_amount, cancelled_orders, updated_at
    )
    SELECT 
        substr(purchase_date_vn, 1, 10) as dt,
        COALESCE(SUM(CASE WHEN status = 2 THEN total_payment ELSE 0 END), 0) as rev,
        COUNT(CASE WHEN status = 2 THEN 1 END) as valid_orders,
        COALESCE(SUM(CASE WHEN status = 2 THEN num_guests ELSE 0 END), 0) as guests,
        COALESCE(AVG(CASE WHEN status = 2 THEN total_payment END), 0) as aov,
        COALESCE(SUM(CASE WHEN status = 2 THEN cash_amount ELSE 0 END), 0) as cash,
        COALESCE(SUM(CASE WHEN status = 2 THEN bank_amount ELSE 0 END), 0) as bank,
        COUNT(CASE WHEN status = 3 THEN 1 END) as cancelled,
        ? as updated_at
    FROM pos_orders
    WHERE purchase_date_vn != '' AND substr(purchase_date_vn, 1, 10) >= '2026-05-01'
    GROUP BY dt
    ON CONFLICT(date) DO UPDATE SET
        total_revenue=excluded.total_revenue,
        total_orders=excluded.total_orders,
        total_guests=excluded.total_guests,
        avg_order_value=excluded.avg_order_value,
        cash_amount=excluded.cash_amount,
        bank_amount=excluded.bank_amount,
        cancelled_orders=excluded.cancelled_orders,
        updated_at=excluded.updated_at;
    """, (now_str,))
    conn.commit()
    print("=== [DONE] pos_daily_summary aggregated successfully. ===")

def export_today_json(conn):
    os.makedirs(EXPORT_DIR, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    out_file = os.path.join(EXPORT_DIR, f"daily_{today_str}.json")

    cur = conn.cursor()
    cur.execute("SELECT raw_json FROM pos_orders WHERE substr(purchase_date_vn, 1, 10) = ?", (today_str,))
    rows = cur.fetchall()
    orders = [json.loads(r[0]) for r in rows if r[0]]

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"date": today_str, "count": len(orders), "orders": orders}, f, ensure_ascii=False, indent=2)
    print(f"=== [EXPORT] Saved {len(orders)} orders of {today_str} to {out_file} ===")

def main():
    parser = argparse.ArgumentParser(description="Sync POS365 FnBOps Data")
    parser.add_argument("--backfill", action="store_true", help="Sync all orders since 2026-05-01")
    parser.add_argument("--items", action="store_true", help="Fetch detailed items per order (up to 300 recent orders)")
    parser.add_argument("--items-limit", type=int, default=300, help="Number of recent orders to fetch items for (default: 300)")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    init_tables(conn)

    opener = get_opener()
    print("[1/4] Logging into POS365...")
    login(opener)
    print("[1/4] Login successful.")

    print("[2/4] Syncing products, categories, cashiers...")
    user_map = sync_catalogs(opener, conn)

    print(f"[3/4] Syncing orders (Backfill={args.backfill}, Items={args.items}, Limit={args.items_limit})...")
    sync_orders(opener, conn, user_map, backfill=args.backfill, fetch_items=args.items, items_limit=args.items_limit)

    print("[4/4] Updating pos_daily_summary & exporting JSON...")
    update_daily_summary(conn)
    export_today_json(conn)
    conn.close()

    print("=== ALL SYNC OPERATIONS FINISHED SUCCESSFULLY ===")

if __name__ == "__main__":
    main()
