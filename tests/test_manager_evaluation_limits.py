import os
import sys
import unittest
import json
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from main import app
from services.auth import create_access_token
from routers.evaluation import load_evaluations, save_evaluations

class TestManagerEvaluationLimits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "user_type": "admin"})
        cls.manager_token = create_access_token({"sub": "manager", "role": "MANAGER", "user_type": "staff"})
        cls.staff_token = create_access_token({"sub": "nhanvien", "role": "STAFF", "user_type": "staff"})

    def setUp(self):
        # Reset evaluations to avoid state bleed
        self.original_evals = load_evaluations()
        save_evaluations([])

    def tearDown(self):
        save_evaluations(self.original_evals)

    def test_01_manager_cannot_exceed_1m_single_bonus(self):
        """Quản lý không được thưởng quá 1,000,000đ/lần (bị lỗi 400)"""
        headers = {"Authorization": f"Bearer {self.manager_token}"}
        res = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=headers, json={
            "staff_name": "Nhân Viên",
            "date": "2026-09-14",
            "type": "Thưởng",
            "amount": 1500000,
            "reason": "Hoàn thành xuất sắc chỉ tiêu"
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("1,000,000", res.json()["detail"])

    def test_02_manager_bonus_defaults_to_pending(self):
        """Đề xuất thưởng của Quản lý phải ở trạng thái PENDING chờ Chủ quán duyệt"""
        headers = {"Authorization": f"Bearer {self.manager_token}"}
        res = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=headers, json={
            "staff_name": "Nhân Viên",
            "date": "2026-09-14",
            "type": "Thưởng",
            "amount": 500000,
            "reason": "Pha chế nhanh và sạch sẽ"
        })
        self.assertEqual(res.status_code, 200)
        entry = res.json()["entry"]
        self.assertEqual(entry["status"], "PENDING")

    def test_03_manager_cannot_exceed_1m_monthly_per_staff(self):
        """Quản lý không được thưởng tích lũy quá 1,000,000đ/tháng cho cùng 1 nhân sự"""
        headers = {"Authorization": f"Bearer {self.manager_token}"}
        # Thưởng lần 1: 600k (OK)
        r1 = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=headers, json={
            "staff_name": "Nhân Viên",
            "date": "2026-09-14",
            "type": "Thưởng",
            "amount": 600000,
            "reason": "Thưởng ca sáng tốt"
        })
        self.assertEqual(r1.status_code, 200)

        # Thưởng lần 2: 500k -> Tổng 1.1M > 1M -> Bị 400
        r2 = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=headers, json={
            "staff_name": "Nhân Viên",
            "date": "2026-09-15",
            "type": "Thưởng",
            "amount": 500000,
            "reason": "Thưởng ca tối tốt"
        })
        self.assertEqual(r2.status_code, 400)
        self.assertIn("vượt hạn mức 1,000,000", r2.json()["detail"])

    def test_04_admin_review_workflow(self):
        """Chủ quán (Admin) duyệt đề xuất và chuyển trạng thái sang APPROVED hoặc REJECTED"""
        headers_mgr = {"Authorization": f"Bearer {self.manager_token}"}
        r_create = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=headers_mgr, json={
            "staff_name": "Nhân Viên",
            "date": "2026-09-14",
            "type": "Thưởng",
            "amount": 300000,
            "reason": "Hỗ trợ khách hàng nhiệt tình"
        })
        eval_id = r_create.json()["entry"]["id"]

        # Staff không được duyệt
        headers_staff = {"Authorization": f"Bearer {self.staff_token}"}
        r_fail = self.client.post("/api/v1/cc/admin/staff-evaluation/review", headers=headers_staff, json={
            "eval_id": eval_id,
            "action": "APPROVE"
        })
        self.assertEqual(r_fail.status_code, 403)

        # Admin duyệt
        headers_admin = {"Authorization": f"Bearer {self.admin_token}"}
        r_ok = self.client.post("/api/v1/cc/admin/staff-evaluation/review", headers=headers_admin, json={
            "eval_id": eval_id,
            "action": "APPROVE",
            "admin_note": "Chủ quán đồng ý duyệt"
        })
        self.assertEqual(r_ok.status_code, 200)
        self.assertEqual(r_ok.json()["evaluation"]["status"], "APPROVED")

    def test_05_pending_bonus_excluded_from_payroll(self):
        """Khoản thưởng PENDING không được tính vào bảng lương cho tới khi được duyệt APPROVED"""
        headers_mgr = {"Authorization": f"Bearer {self.manager_token}"}
        headers_admin = {"Authorization": f"Bearer {self.admin_token}"}

        # 1. Check payroll before evaluation
        r_pre = self.client.get("/api/v1/cc/payroll/summary?month=9&staff_name=Nhân Viên", headers=headers_admin)
        bonus_pre = r_pre.json()["breakdown"]["eval_bonus"]

        # 2. Manager creates 200k bonus (status = PENDING)
        r_create = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=headers_mgr, json={
            "staff_name": "Nhân Viên",
            "date": "2026-09-14",
            "type": "Thưởng",
            "amount": 200000,
            "reason": "Thưởng chuyên cần"
        })
        eval_id = r_create.json()["entry"]["id"]

        # 3. Check payroll while PENDING -> bonus must NOT increase
        r_mid = self.client.get("/api/v1/cc/payroll/summary?month=9&staff_name=Nhân Viên", headers=headers_admin)
        bonus_mid = r_mid.json()["breakdown"]["eval_bonus"]
        self.assertEqual(bonus_mid, bonus_pre)

        # 4. Admin approves
        self.client.post("/api/v1/cc/admin/staff-evaluation/review", headers=headers_admin, json={
            "eval_id": eval_id,
            "action": "APPROVE"
        })

        # 5. Check payroll after APPROVE -> bonus increased by 200k
        r_post = self.client.get("/api/v1/cc/payroll/summary?month=9&staff_name=Nhân Viên", headers=headers_admin)
        bonus_post = r_post.json()["breakdown"]["eval_bonus"]
        self.assertEqual(bonus_post, bonus_pre + 200000)

if __name__ == "__main__":
    unittest.main()
