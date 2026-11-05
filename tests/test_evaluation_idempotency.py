# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Unit Tests for Staff Evaluation (Bonus & Penalty) Idempotency Guard & Sổ Cái Deduplication
Verifies:
1. Double-tap / stacked-listener Bonus requests within 5s return dedup=True and do NOT create duplicate evaluations or duplicate so_cai_luong entries.
2. Double-tap / stacked-listener Penalty (Phạt) requests within 5s return dedup=True and do NOT double-deduct staff pay.
3. calculate_staff_payslip_breakdown does not double-count evaluations when both evaluations and so_cai_luong are provided (e.g. Excel export).
"""

import os
import sys
import tempfile
import unittest
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"
os.environ["MOCK_TELEGRAM"] = "1"
os.environ["DISABLE_OUTBOUND_TELEGRAM"] = "1"

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from main import app
from routers.fnb_ops import create_access_token
from routers.evaluation import load_evaluations, save_evaluations
from services.db import init_db, list_so_cai_luong
from services.payroll_calc import calculate_staff_payslip_breakdown


class TestEvaluationIdempotency(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Store Owner (Admin)"})
        self.headers = {"Authorization": f"Bearer {self.admin_token}"}

        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_path = self.temp_db.name
        self.temp_db.close()
        init_db(self.temp_db_path)

        self.temp_eval_json = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8")
        self.temp_eval_json.write("[]")
        self.temp_eval_path = self.temp_eval_json.name
        self.temp_eval_json.close()

        self.orig_db_env = os.environ.get("SQLITE_DB_PATH")
        self.orig_db_path_env = os.environ.get("DATABASE_PATH")
        self.orig_eval_env = os.environ.get("EVAL_LOGS_FILE")
        self.orig_evals_file_env = os.environ.get("EVALUATIONS_FILE")
        os.environ["SQLITE_DB_PATH"] = self.temp_db_path
        os.environ["DATABASE_PATH"] = self.temp_db_path
        os.environ["EVAL_LOGS_FILE"] = self.temp_eval_path
        os.environ["EVALUATIONS_FILE"] = self.temp_eval_path

        save_evaluations([])

    def tearDown(self):
        save_evaluations([])
        if self.orig_db_env is not None:
            os.environ["SQLITE_DB_PATH"] = self.orig_db_env
        else:
            os.environ.pop("SQLITE_DB_PATH", None)

        if self.orig_db_path_env is not None:
            os.environ["DATABASE_PATH"] = self.orig_db_path_env
        else:
            os.environ.pop("DATABASE_PATH", None)

        if self.orig_eval_env is not None:
            os.environ["EVAL_LOGS_FILE"] = self.orig_eval_env
        else:
            os.environ.pop("EVAL_LOGS_FILE", None)

        if self.orig_evals_file_env is not None:
            os.environ["EVALUATIONS_FILE"] = self.orig_evals_file_env
        else:
            os.environ.pop("EVALUATIONS_FILE", None)

        for p in [self.temp_db_path, self.temp_db_path + "-wal", self.temp_db_path + "-shm", self.temp_eval_path]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def test_01_double_tap_bonus_prevented_and_ledger_idempotent(self):
        """Gửi đúp 2 request Thưởng liên tiếp chỉ tạo 1 bản ghi evaluations và 1 dòng so_cai_luong."""
        payload = {
            "staff_name": "NHANVIEN",
            "date": "2026-11-04",
            "shift": "Ca Sáng",
            "type": "Thưởng",
            "amount": 10000,
            "reason": "KHÔNG THẤT THOÁT TÀI SẢN"
        }

        res1 = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=self.headers, json=payload)
        res2 = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=self.headers, json=payload)

        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res2.status_code, 200)

        data1 = res1.json()
        data2 = res2.json()
        self.assertTrue(data2.get("dedup"), "Lượt gọi thứ 2 liên tiếp phải được đánh dấu dedup=True")
        self.assertEqual(data1["entry"]["id"], data2["entry"]["id"], "Phải trả về cùng 1 mã EVAL ID")

        evals = load_evaluations()
        self.assertEqual(len(evals), 1, "Chỉ được phép có đúng 1 bản ghi trong evaluations")

        socai = list_so_cai_luong(staff_name="NHANVIEN", month="11", db_path=self.temp_db_path)
        self.assertEqual(len(socai), 1, "Chỉ được phép có đúng 1 bút toán trong so_cai_luong")
        self.assertEqual(socai[0]["so_tien_thay_doi"], 10000)
        self.assertEqual(socai[0]["idempotency_key"], f"EVAL_{data1['entry']['id']}")

        breakdown = calculate_staff_payslip_breakdown(
            staff_name="NHANVIEN",
            month="11",
            data_json={},
            evaluations=evals,
            so_cai_luong=socai
        )
        self.assertEqual(breakdown["eval_bonus"], 10000, "Không được cộng đúp giữa evaluations và so_cai_luong")

    def test_02_double_tap_penalty_prevented(self):
        """Gửi đúp 2 request Phạt liên tiếp chỉ tạo 1 bản ghi Phạt, không trừ tiền gấp đôi."""
        payload = {
            "staff_name": "PHACHE",
            "date": "2026-11-04",
            "shift": "Ca Sáng",
            "type": "Phạt",
            "amount": 20000,
            "reason": "Đi trễ không báo trước"
        }

        res1 = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=self.headers, json=payload)
        res2 = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=self.headers, json=payload)

        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.json().get("dedup"))

        evals = load_evaluations()
        self.assertEqual(len(evals), 1)

        socai = list_so_cai_luong(staff_name="PHACHE", month="11", db_path=self.temp_db_path)
        self.assertEqual(len(socai), 1)

        breakdown = calculate_staff_payslip_breakdown(
            staff_name="PHACHE",
            month="11",
            data_json={},
            evaluations=evals,
            so_cai_luong=socai
        )
        self.assertEqual(breakdown["eval_deductions"], 20000, "Chỉ trừ đúng 20,000đ tiền phạt")


if __name__ == "__main__":
    unittest.main()
