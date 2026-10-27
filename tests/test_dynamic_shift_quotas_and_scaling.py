import pytest
import datetime
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.roster_engine import auto_assign_week_schedule
from backend.services.store_config import get_store_config, get_shift_role_requirements
from backend.services.auth import create_access_token, get_admin_token_version

client = TestClient(app)


class TestDynamicShiftQuotasAndScaling:
    def test_01_store_config_shift_role_requirements_helper(self):
        """Kiểm tra helper get_shift_role_requirements phân tách rõ ngày thường và cuối tuần"""
        shift_cfg = {
            "weekday_roles": {"manager": 1, "barista": 1, "service": 2},
            "weekend_roles": {"manager": 1, "barista": 3, "service": 6},
            "roles": {"manager": 1, "barista": 1, "service": 2}
        }
        weekday_req = get_shift_role_requirements(shift_cfg, is_weekend=False)
        assert weekday_req["barista"] == 1
        assert weekday_req["service"] == 2
        assert weekday_req["manager"] == 1

        weekend_req = get_shift_role_requirements(shift_cfg, is_weekend=True)
        assert weekend_req["barista"] == 3
        assert weekend_req["service"] == 6
        assert weekend_req["manager"] == 1

    def test_02_auto_assign_scales_to_custom_quota(self, monkeypatch):
        """Kiểm tra khi quán cấu hình 3 Barista và 4 Service, auto_assign lặp xếp đủ số lượng"""
        # Giả lập cấu hình ca sáng cần 2 Barista, 3 Service
        custom_store_cfg = {
            "shifts": {
                "sang": {
                    "official_start": "06:00",
                    "official_end": "11:30",
                    "weekday_roles": {"manager": 1, "barista": 2, "service": 3},
                    "weekend_roles": {"manager": 1, "barista": 3, "service": 5}
                },
                "toi": {
                    "official_start": "17:00",
                    "official_end": "23:00",
                    "weekday_roles": {"manager": 1, "barista": 1, "service": 3},
                    "weekend_roles": {"manager": 1, "barista": 2, "service": 4}
                }
            },
            "roster_rules": {
                "gender_constraints": {"enabled": False},
                "shifts_per_week": {"min": 1, "max": 10, "default_target": 5}
            }
        }
        monkeypatch.setattr("backend.services.roster_engine.get_store_config", lambda: custom_store_cfg)
        import sys
        for mod_name in ["services.roster_engine", "services.store_config", "backend.services.store_config"]:
            if mod_name in sys.modules:
                monkeypatch.setattr(f"{mod_name}.get_store_config", lambda: custom_store_cfg)

        # 4 Baristas, 6 Services
        staff_accounts = {
            "bar1": {"full_name": "Barista 1", "position": "BARISTA", "role": "STAFF", "status": "ACTIVE", "primary_role": "BAR"},
            "bar2": {"full_name": "Barista 2", "position": "BARISTA", "role": "STAFF", "status": "ACTIVE", "primary_role": "BAR"},
            "bar3": {"full_name": "Barista 3", "position": "BARISTA", "role": "STAFF", "status": "ACTIVE", "primary_role": "BAR"},
            "bar4": {"full_name": "Barista 4", "position": "BARISTA", "role": "STAFF", "status": "ACTIVE", "primary_role": "BAR"},
            "svc1": {"full_name": "Phục vụ 1", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE", "primary_role": "SVC"},
            "svc2": {"full_name": "Phục vụ 2", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE", "primary_role": "SVC"},
            "svc3": {"full_name": "Phục vụ 3", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE", "primary_role": "SVC"},
            "svc4": {"full_name": "Phục vụ 4", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE", "primary_role": "SVC"},
            "svc5": {"full_name": "Phục vụ 5", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE", "primary_role": "SVC"},
            "svc6": {"full_name": "Phục vụ 6", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE", "primary_role": "SVC"},
            "ql1": {"full_name": "Quản lý 1", "position": "MANAGER", "role": "MANAGER", "status": "ACTIVE"}
        }

        # Tất cả đều sẵn sàng làm MORNING và EVENING các ngày
        registrations = {
            u: {
                "full_name": a["full_name"],
                "target_shifts": 6,
                "preferences": {d: ["MORNING", "EVENING"] for d in ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]}
            }
            for u, a in staff_accounts.items() if a.get("role") == "STAFF"
        }

        res = auto_assign_week_schedule(
            week_key="2026-W42",
            registrations=registrations,
            staff_accounts=staff_accounts,
            save_to_disk=False
        )

        shifts = res["shifts"]
        for d_str, day_sh in shifts.items():
            dt = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
            is_weekend = (dt.isocalendar()[2] in [6, 7])

            m = day_sh["morning"]
            if is_weekend:
                assert len(m["baristas"]) == 3, f"Cuối tuần ca sáng phải có 3 Barista, thực tế: {len(m['baristas'])}"
                assert len(m["service"]) == 5, f"Cuối tuần ca sáng phải có 5 Phục vụ, thực tế: {len(m['service'])}"
            else:
                assert len(m["baristas"]) == 2, f"Ngày thường ca sáng phải có 2 Barista, thực tế: {len(m['baristas'])}"
                assert len(m["service"]) == 3, f"Ngày thường ca sáng phải có 3 Phục vụ, thực tế: {len(m['service'])}"

    def test_03_update_shift_slot_supports_multi_barista_and_service(self, monkeypatch):
        """Kiểm tra API update-shift cho phép gán và gỡ các slot động như barista_1, service_3, manager"""
        mock_auth = {
            "staff_accounts": {
                "phache01": {"full_name": "Pha Chế 01", "role": "STAFF", "status": "ACTIVE"},
                "nhanvien01": {"full_name": "Nhân Viên 01", "role": "STAFF", "status": "ACTIVE"}
            }
        }
        monkeypatch.setattr("backend.routers.roster.load_staff_auth", lambda: mock_auth)
        try:
            import routers.roster
            monkeypatch.setattr(routers.roster, "load_staff_auth", lambda: mock_auth)
        except Exception:
            pass
        admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "ver": get_admin_token_version()})
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Gán barista_1
        res = client.post("/api/v1/cc/roster/update-shift", headers=headers, json={
            "week_id": "current",
            "date": "2026-10-19",
            "shift_period": "morning",
            "slot_type": "barista_1",
            "username": "phache01"
        })
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["success"] is True
        m = data["day_shift"]["morning"]
        assert len(m["baristas"]) >= 2
        assert m["baristas"][1] == "phache01"

        # 2. Gán service_3
        res = client.post("/api/v1/cc/roster/update-shift", headers=headers, json={
            "week_id": "current",
            "date": "2026-10-19",
            "shift_period": "morning",
            "slot_type": "service_3",
            "username": "nhanvien01"
        })
        assert res.status_code == 200, res.text
        m = res.json()["day_shift"]["morning"]
        assert len(m["service"]) >= 4
        assert m["service"][3] == "nhanvien01"

        # 3. Gỡ slot barista_1 (username = None)
        res = client.post("/api/v1/cc/roster/update-shift", headers=headers, json={
            "week_id": "current",
            "date": "2026-10-19",
            "shift_period": "morning",
            "slot_type": "barista_1",
            "username": None
        })
        assert res.status_code == 200, res.text
        m = res.json()["day_shift"]["morning"]
        assert m["baristas"][1] is None

    def test_04_backtracking_swap_synchronizes_arrays_and_prevents_duplicate_assignment(self, monkeypatch):
        """
        Kiểm tra cơ chế 1-Step Backtracking Swap:
        Khi user_multi (biết cả Bar & Service) bị gán làm Barista trước, nhưng thiếu Service
        trong khi còn user_bar_only (chỉ biết Bar) chưa được gán, hệ thống tự động hoán vị:
        user_multi -> service, user_bar_only -> barista.
        Đảm bảo:
        1. assigned_m_bars đồng bộ chuẩn xác với barista đơn lẻ.
        2. Không có hiện tượng nhân sự phân thân (trùng ca vừa làm bar vừa làm service).
        """
        custom_store_cfg = {
            "shifts": {
                "sang": {
                    "official_start": "06:00",
                    "official_end": "11:30",
                    "weekday_roles": {"manager": 0, "barista": 1, "service": 1},
                    "weekend_roles": {"manager": 0, "barista": 1, "service": 1}
                },
                "toi": {
                    "official_start": "17:00",
                    "official_end": "23:00",
                    "weekday_roles": {"manager": 0, "barista": 0, "service": 0},
                    "weekend_roles": {"manager": 0, "barista": 0, "service": 0}
                }
            },
            "roster_rules": {
                "gender_constraints": {"enabled": False},
                "shifts_per_week": {"min": 1, "max": 10, "default_target": 5}
            }
        }
        monkeypatch.setattr("backend.services.roster_engine.get_store_config", lambda: custom_store_cfg)
        import sys
        for mod_name in ["services.roster_engine", "services.store_config", "backend.services.store_config"]:
            if mod_name in sys.modules:
                monkeypatch.setattr(f"{mod_name}.get_store_config", lambda: custom_store_cfg)

        staff_accounts = {
            "multi_user": {
                "full_name": "Multi User",
                "position": "BARISTA",
                "role": "STAFF",
                "status": "ACTIVE",
                "primary_role": "BAR",
                "allowed_roles": ["BAR", "SERVICE"]
            },
            "bar_only_user": {
                "full_name": "Bar Only User",
                "position": "BARISTA",
                "role": "STAFF",
                "status": "ACTIVE",
                "primary_role": "BAR",
                "allowed_roles": ["BAR"]
            }
        }

        # Cả 2 đều đăng ký làm sáng Thứ 2
        registrations = {
            "multi_user": {
                "full_name": "Multi User",
                "target_shifts": 5,
                "preferences": {"T2": ["MORNING"]}
            },
            "bar_only_user": {
                "full_name": "Bar Only User",
                "target_shifts": 5,
                "preferences": {"T2": ["MORNING"]}
            }
        }

        res = auto_assign_week_schedule(
            week_key="2026-W42",
            registrations=registrations,
            staff_accounts=staff_accounts,
            save_to_disk=False
        )

        shifts = res["shifts"]
        t2_date = "2026-10-12"  # Thứ 2 tuần W42/2026
        assert t2_date in shifts, f"Không tìm thấy ngày {t2_date} trong {list(shifts.keys())}"
        m = shifts[t2_date]["morning"]

        # Kiểm tra đã hoán vị thành công:
        # bar_only_user phải là Barista, multi_user phải là Service
        assert m["barista"] == "bar_only_user", f"Barista phải là bar_only_user, thực tế: {m['barista']}"
        assert m["baristas"] == ["bar_only_user"], f"Mảng baristas phải là ['bar_only_user'], thực tế: {m['baristas']}"
        assert "multi_user" in m["service"], f"multi_user phải nằm trong service, thực tế: {m['service']}"

        # ĐẢM BẢO TUYỆT ĐỐI: Không có nhân viên nào bị phân thân làm 2 vị trí!
        overlap = set(m["baristas"]) & set(m["service"])
        assert len(overlap) == 0, f"Phát hiện nhân sự bị trùng cả Barista và Service: {overlap}"

    def test_05_staff_registered_18h_is_never_forced_to_17h(self):
        """
        Nhân viên đăng ký EVENING_18 cho ca tối (kể cả có thêm tag sáng). Khi xếp ca:
        Nếu chỉ có người này đăng ký ca tối -> day_shifts["evening"]["service_18"] là nhân viên này,
        còn day_shifts["evening"]["service_17"] phải là None. Tuyệt đối không được ép sang 17h!
        """
        staff_accounts = {
            "m1": {"full_name": "Sáng 1", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE", "gender": "NAM"},
            "m2": {"full_name": "Sáng 2", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE", "gender": "NU"},
            "nv_18h": {
                "full_name": "Nhân Viên 18h",
                "position": "SERVICE",
                "role": "STAFF",
                "status": "ACTIVE",
                "gender": "NU",
                "primary_role": "SVC",
                "allowed_roles": ["SERVICE"]
            }
        }

        # T2: m1 và m2 đăng ký MORNING, nv_18h đăng ký cả MORNING và EVENING_18 (chỉ nv_18h đăng ký tối)
        # T3: m1 và m2 đăng ký MORNING, nv_18h chỉ đăng ký duy nhất EVENING_18 (không tag sáng)
        registrations = {
            "m1": {"full_name": "Sáng 1", "target_shifts": 5, "preferences": {"T2": ["MORNING"], "T3": ["MORNING"]}},
            "m2": {"full_name": "Sáng 2", "target_shifts": 5, "preferences": {"T2": ["MORNING"], "T3": ["MORNING"]}},
            "nv_18h": {
                "full_name": "Nhân Viên 18h",
                "target_shifts": 3,
                "preferences": {
                    "T2": ["MORNING", "EVENING_18"],
                    "T3": ["EVENING_18"]
                }
            }
        }

        res = auto_assign_week_schedule(
            week_key="2026-W42",
            registrations=registrations,
            staff_accounts=staff_accounts,
            save_to_disk=False
        )

        shifts = res["shifts"]
        days = res["days"]

        # 1. Kiểm tra ngày Thứ 2 (có thêm tag sáng, nhưng chỉ nv_18h đăng ký tối)
        t2_date = "2026-10-12"
        assert t2_date in shifts, f"Không tìm thấy ngày {t2_date} trong {list(shifts.keys())}"
        day_sh_t2 = shifts[t2_date]
        assert "m1" in day_sh_t2["morning"]["service"]
        assert "m2" in day_sh_t2["morning"]["service"]

        evening_t2 = day_sh_t2["evening"]
        assert evening_t2["service_18"] == "nv_18h", f"T2 service_18 phải là nv_18h, thực tế: {evening_t2['service_18']}"
        assert evening_t2["service_17"] is None, f"T2 service_17 phải là None, thực tế: {evening_t2['service_17']}"
        assert evening_t2["service"] == ["nv_18h"]
        assert days["t2"]["toi"]["service_18"] == ["nv_18h"]
        assert days["t2"]["toi"]["service_17"] == []
        assert days["t2"]["toi"]["service"] == ["nv_18h"]

        # 2. Kiểm tra ngày Thứ 3 (chỉ đăng ký duy nhất EVENING_18)
        t3_date = "2026-10-13"
        assert t3_date in shifts, f"Không tìm thấy ngày {t3_date} trong {list(shifts.keys())}"
        day_sh_t3 = shifts[t3_date]
        evening_t3 = day_sh_t3["evening"]
        assert evening_t3["service_18"] == "nv_18h", f"T3 service_18 phải là nv_18h, thực tế: {evening_t3['service_18']}"
        assert evening_t3["service_17"] is None, f"T3 service_17 phải là None, thực tế: {evening_t3['service_17']}"
        assert evening_t3["service"] == ["nv_18h"]
        assert days["t3"]["toi"]["service_18"] == ["nv_18h"]
        assert days["t3"]["toi"]["service_17"] == []
        assert days["t3"]["toi"]["service"] == ["nv_18h"]

    def test_06_staff_registered_only_evening_is_never_assigned_to_morning(self):
        """
        Nhân viên chỉ đăng ký Ca Tối (như Trí: EVENING_17 / EVENING_18) TUYỆT ĐỐI không bao giờ
        bị tự động bốc sang Ca Sáng, kể cả khi Ca Sáng thiếu người hoặc thiếu Nam.
        """
        staff_accounts = {
            "female_morning": {
                "full_name": "Nữ Ca Sáng",
                "position": "SERVICE",
                "role": "STAFF",
                "status": "ACTIVE",
                "gender": "NU"
            },
            "male_evening_only": {
                "full_name": "Nam Chỉ Ca Tối (Trí)",
                "position": "SERVICE",
                "role": "STAFF",
                "status": "ACTIVE",
                "gender": "NAM"
            }
        }

        registrations = {
            "female_morning": {
                "full_name": "Nữ Ca Sáng",
                "target_shifts": 5,
                "preferences": {"T2": ["MORNING"], "T3": ["MORNING"]}
            },
            "male_evening_only": {
                "full_name": "Nam Chỉ Ca Tối (Trí)",
                "target_shifts": 5,
                "preferences": {"T2": ["EVENING_18"], "T3": ["EVENING_18"]}
            }
        }

        res = auto_assign_week_schedule(
            week_key="2026-W42",
            registrations=registrations,
            staff_accounts=staff_accounts,
            save_to_disk=False
        )

        shifts = res["shifts"]
        for d_key in ["2026-10-12", "2026-10-13"]:
            sh = shifts[d_key]
            m_svc = sh["morning"]["service"]
            e_svc = sh["evening"]["service"]

            # Nam chỉ đăng ký ca tối TUYỆT ĐỐI không có trong ca sáng
            assert "male_evening_only" not in m_svc, f"Nam ca tối bị gán nhầm vào ca sáng: {m_svc}"
            # Ca sáng chỉ có nữ ca sáng
            assert "female_morning" in m_svc
            # Ca tối slot 18h phải là nam ca tối
            assert sh["evening"]["service_18"] == "male_evening_only"
            assert sh["evening"]["service_17"] is None



