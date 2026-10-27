import os
import sys
import sqlite3
import pytest
import tempfile
import threading

# Ensure backend and project root are in sys.path
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)
_backend_dir = os.path.join(_project_root, "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from services.db import (
    init_db,
    get_db_connection,
    upsert_staff_account,
    get_staff_by_username,
    list_staff_accounts,
    insert_evaluation,
    list_evaluations,
    DEFAULT_TENANT_ID
)


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    init_db(db_path)
    yield db_path

    for ext in ["", "-wal", "-shm"]:
        p = f"{db_path}{ext}"
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


# ==========================================
# 1. WAL MODE & INTEGRITY TESTS
# ==========================================
def test_sqlite_wal_mode_and_foreign_keys(temp_db):
    conn = get_db_connection(temp_db)
    cur = conn.cursor()

    # Verify WAL mode
    cur.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0]
    assert mode.lower() == "wal"

    # Verify Foreign keys enabled
    cur.execute("PRAGMA foreign_keys;")
    fk = cur.fetchone()[0]
    assert fk == 1

    conn.close()


# ==========================================
# 2. MULTI-TENANCY ISOLATION TESTS
# ==========================================
def test_multi_tenancy_data_isolation(temp_db):
    conn = get_db_connection(temp_db)
    with conn:
        conn.execute("INSERT INTO tenants (id, code, name) VALUES ('tenant_a', 'TA', 'Branch A')")
        conn.execute("INSERT INTO tenants (id, code, name) VALUES ('tenant_b', 'TB', 'Branch B')")

    # Insert staff in Tenant A
    upsert_staff_account(
        username="user_a",
        full_name="User In Tenant A",
        pin_hash="hash_a",
        tenant_id="tenant_a",
        db_path=temp_db
    )

    # Insert staff in Tenant B
    upsert_staff_account(
        username="user_b",
        full_name="User In Tenant B",
        pin_hash="hash_b",
        tenant_id="tenant_b",
        db_path=temp_db
    )

    # Query Tenant A: Must only see user_a
    staff_a = list_staff_accounts(tenant_id="tenant_a", db_path=temp_db)
    assert len(staff_a) == 1
    assert staff_a[0]["username"] == "user_a"
    assert staff_a[0]["full_name"] == "User In Tenant A"

    # Query Tenant B: Must only see user_b
    staff_b = list_staff_accounts(tenant_id="tenant_b", db_path=temp_db)
    assert len(staff_b) == 1
    assert staff_b[0]["username"] == "user_b"

    # Isolation check: Tenant A cannot fetch user_b
    lookup_b_from_a = get_staff_by_username("user_b", tenant_id="tenant_a", db_path=temp_db)
    assert lookup_b_from_a is None

    conn.close()


# ==========================================
# 3. CONCURRENT READS & WRITES (WAL BENEFIT)
# ==========================================
def test_concurrent_reads_and_writes_wal(temp_db):
    """
    Demonstrates that in WAL mode, readers do not block writers and writers do not block readers.
    """
    errors = []

    def writer_worker():
        for i in range(20):
            try:
                upsert_staff_account(
                    username=f"worker_user_{i}",
                    full_name=f"Worker {i}",
                    pin_hash="test_hash",
                    db_path=temp_db
                )
            except Exception as e:
                errors.append(e)

    def reader_worker():
        for _ in range(30):
            try:
                accounts = list_staff_accounts(db_path=temp_db)
                assert isinstance(accounts, list)
            except Exception as e:
                errors.append(e)

    threads = [
        threading.Thread(target=writer_worker),
        threading.Thread(target=reader_worker),
        threading.Thread(target=reader_worker)
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0


# ==========================================
# 4. ACID TRANSACTION ROLLBACK TEST
# ==========================================
def test_acid_transaction_rollback(temp_db):
    conn = get_db_connection(temp_db)

    # Begin transaction and deliberately raise error
    try:
        with conn:
            conn.execute("""
                INSERT INTO staff_accounts (username, tenant_id, full_name, pin_hash, role)
                VALUES ('rollback_user', 'fnbop_main', 'Rollback User', 'hash', 'STAFF')
            """)
            # Force integrity error by inserting duplicated username in same transaction
            conn.execute("""
                INSERT INTO staff_accounts (username, tenant_id, full_name, pin_hash, role)
                VALUES ('rollback_user', 'fnbop_main', 'Rollback User', 'hash', 'STAFF')
            """)
    except sqlite3.IntegrityError:
        pass

    # Verify that first insert was safely rolled back (Atomicity)
    cur = conn.cursor()
    cur.execute("SELECT * FROM staff_accounts WHERE username = 'rollback_user'")
    row = cur.fetchone()
    assert row is None, "Transaction should have rolled back completely!"
    conn.close()


# ==========================================
# 5. STAFF LEDGERS (SỔ PHỤ) CRUD TEST
# ==========================================
def test_staff_ledgers_crud(temp_db):
    from services.db import insert_staff_ledger, list_staff_ledgers, delete_staff_ledger

    # 1. Insert Bonus, Advance, Deduction
    b = insert_staff_ledger({
        "id": "LEDGER_001",
        "staff_name": "Nguyễn Văn Thiên",
        "month": "9",
        "type": "bonus",
        "amount": 100000,
        "payment_method": "bank",
        "reason": "Thưởng ca xuất sắc",
        "created_by": "admin"
    }, db_path=temp_db)
    assert b["id"] == "LEDGER_001"

    a = insert_staff_ledger({
        "id": "LEDGER_002",
        "staff_name": "Nguyễn Văn Thiên",
        "month": "9",
        "type": "advance",
        "amount": 200000,
        "payment_method": "cash",
        "reason": "Ứng tiền mặt giữa tháng",
        "created_by": "manager"
    }, db_path=temp_db)
    assert a["id"] == "LEDGER_002"

    d = insert_staff_ledger({
        "id": "LEDGER_003",
        "staff_name": "Nguyễn Văn Thiện",
        "month": "9",
        "type": "deduction",
        "amount": 50000,
        "payment_method": "cash",
        "reason": "Trễ ca > 30p",
        "created_by": "admin"
    }, db_path=temp_db)
    assert d["id"] == "LEDGER_003"

    # 2. List all for month 9
    all_m9 = list_staff_ledgers(month="9", db_path=temp_db)
    assert len(all_m9) == 3

    # 3. Filter by staff_name
    thien_ledgers = list_staff_ledgers(month="9", staff_name="Nguyễn Văn Thiên", db_path=temp_db)
    assert len(thien_ledgers) == 2
    types = [x["type"] for x in thien_ledgers]
    assert "bonus" in types
    assert "advance" in types

    # 4. Filter by type
    advances = list_staff_ledgers(month="9", ledger_type="advance", db_path=temp_db)
    assert len(advances) == 1
    assert advances[0]["amount"] == 200000

    # 5. Delete entry
    deleted = delete_staff_ledger("LEDGER_002", db_path=temp_db)
    assert deleted is True

    # Verify deletion
    thien_after = list_staff_ledgers(month="9", staff_name="Nguyễn Văn Thiên", db_path=temp_db)
    assert len(thien_after) == 1
    assert thien_after[0]["id"] == "LEDGER_001"

