import os
import sys
import time
import shutil
import tarfile
import sqlite3
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backup_production_data import (
    run_backup_process,
    verify_latest_backup_archive,
    enforce_retention_policy,
    calculate_file_sha256,
    backup_sqlite_database,
    collect_json_data_files
)


class TestDisasterRecoveryBackup(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="fnbops_backup_test_"))
        self.mock_root = self.test_dir / "project"
        self.mock_root.mkdir(parents=True, exist_ok=True)

        # Mock source database
        self.backend_data = self.mock_root / "backend" / "data"
        self.backend_data.mkdir(parents=True, exist_ok=True)
        self.db_path = self.backend_data / "wfm.db"

        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("CREATE TABLE mock_staff (id TEXT PRIMARY KEY, name TEXT, balance REAL);")
        conn.execute("INSERT INTO mock_staff VALUES ('nv01', 'Nguyen Van A', 5000000);")
        conn.commit()
        conn.close()

        # Mock JSON data
        self.data_dir = self.mock_root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for jname in ["data.json", "staff_auth.json", "roster_data.json", "shift_approvals.json", "pos_heartbeat.json"]:
            with open(self.data_dir / jname, "w", encoding="utf-8") as f:
                f.write(f'{{"file": "{jname}", "status": "active"}}')

        self.backups_dir = self.mock_root / "data" / "backups"

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_backup_run_now_creates_archive_and_sha256(self):
        """Kiểm tra sao lưu --run-now tạo đầy đủ archive .tar.gz và checksum .sha256"""
        result = run_backup_process(
            project_root=self.mock_root,
            backups_dir=self.backups_dir,
            dry_run=False,
            timestamp_override="20260915_120000"
        )
        self.assertTrue(result["success"], "Backup phải thành công")
        self.assertTrue(result["sqlite_backed_up"], "SQLite phải được backup")
        self.assertGreater(result["copied_json_count"], 0, "Phải copy ít nhất 1 file JSON")

        archive = self.backups_dir / "backup_20260915_120000.tar.gz"
        sha_file = self.backups_dir / "backup_20260915_120000.tar.gz.sha256"

        self.assertTrue(archive.exists(), "File .tar.gz phải tồn tại")
        self.assertTrue(sha_file.exists(), "File .sha256 phải tồn tại")

        with open(sha_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
        recorded_hash = content.split()[0]
        actual_hash = calculate_file_sha256(archive)
        self.assertEqual(recorded_hash, actual_hash, "Checksum ghi nhận phải khớp mã băm SHA256 thực tế")

    def test_02_sqlite_vacuum_into_integrity(self):
        """Kiểm tra SQLite VACUUM INTO tạo cơ sở dữ liệu toàn vẹn, query được dữ liệu"""
        run_backup_process(
            project_root=self.mock_root,
            backups_dir=self.backups_dir,
            dry_run=False,
            timestamp_override="20260915_120001"
        )
        archive = self.backups_dir / "backup_20260915_120001.tar.gz"

        extract_dir = self.test_dir / "extract_check"
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(path=extract_dir)

        extracted_db = extract_dir / "backup_20260915_120001" / "sqlite" / "wfm.db"
        self.assertTrue(extracted_db.exists(), "wfm.db phải nằm trong thư mục giải nén")

        # Kiểm tra tính toàn vẹn với SQLite connection
        conn = sqlite3.connect(str(extracted_db))
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        row = cur.fetchone()
        self.assertEqual(row[0], "ok", "PRAGMA integrity_check phải trả về 'ok'")

        cur.execute("SELECT name, balance FROM mock_staff WHERE id='nv01';")
        staff_row = cur.fetchone()
        self.assertIsNotNone(staff_row)
        self.assertEqual(staff_row[0], "Nguyen Van A")
        self.assertEqual(staff_row[1], 5000000)
        conn.close()

    def test_03_json_business_data_collected(self):
        """Kiểm tra toàn bộ 5 tệp JSON nghiệp vụ được thu thập đầy đủ"""
        run_backup_process(
            project_root=self.mock_root,
            backups_dir=self.backups_dir,
            dry_run=False,
            timestamp_override="20260915_120002"
        )
        archive = self.backups_dir / "backup_20260915_120002.tar.gz"

        with tarfile.open(archive, "r:gz") as tar:
            members = [m.name for m in tar.getmembers()]

        for expected in ["data.json", "staff_auth.json", "roster_data.json", "shift_approvals.json", "pos_heartbeat.json"]:
            matched = any(expected in m for m in members)
            self.assertTrue(matched, f"Archive phải chứa {expected}")

    def test_04_verify_latest_backup_success(self):
        """Kiểm tra hàm verify_latest_backup_archive xác thực thành công bản backup hợp lệ"""
        run_backup_process(
            project_root=self.mock_root,
            backups_dir=self.backups_dir,
            dry_run=False,
            timestamp_override="20260915_120003"
        )
        ok, msg = verify_latest_backup_archive(backups_dir=self.backups_dir)
        self.assertTrue(ok, f"Xác thực toàn vẹn phải thành công: {msg}")
        self.assertIn("ĐẠT CHUẨN", msg)

    def test_05_verify_latest_detects_tampering(self):
        """Kiểm tra hàm verify phát hiện ngay lập tức khi file bị sửa đổi (tampered)"""
        run_backup_process(
            project_root=self.mock_root,
            backups_dir=self.backups_dir,
            dry_run=False,
            timestamp_override="20260915_120004"
        )
        archive = self.backups_dir / "backup_20260915_120004.tar.gz"

        # Tamper: Thêm dữ liệu rác vào cuối file archive
        with open(archive, "ab") as f:
            f.write(b"CORRUPTED_BYTES_HERE")

        ok, msg = verify_latest_backup_archive(backups_dir=self.backups_dir)
        self.assertFalse(ok, "File bị sửa đổi phải bị từ chối")
        self.assertIn("LỖI TOÀN VẸN", msg)

    def test_06_retention_policy_cleans_older_than_30_days(self):
        """Kiểm tra chính sách Retention: Xoá backup cũ hơn 30 ngày, giữ lại backup mới"""
        self.backups_dir.mkdir(parents=True, exist_ok=True)

        old_archive = self.backups_dir / "backup_20260701_000000.tar.gz"
        old_sha = self.backups_dir / "backup_20260701_000000.tar.gz.sha256"
        with open(old_archive, "wb") as f:
            f.write(b"old backup content")
        with open(old_sha, "w", encoding="utf-8") as f:
            f.write("oldhash  backup_20260701_000000.tar.gz\n")

        # Đặt thời gian sửa đổi cũ hơn 35 ngày
        thirty_five_days_ago = time.time() - (35 * 86400)
        os.utime(str(old_archive), (thirty_five_days_ago, thirty_five_days_ago))
        os.utime(str(old_sha), (thirty_five_days_ago, thirty_five_days_ago))

        # Tạo file mới (hôm nay)
        new_archive = self.backups_dir / "backup_20260915_000000.tar.gz"
        new_sha = self.backups_dir / "backup_20260915_000000.tar.gz.sha256"
        with open(new_archive, "wb") as f:
            f.write(b"new backup content")
        with open(new_sha, "w", encoding="utf-8") as f:
            f.write("newhash  backup_20260915_000000.tar.gz\n")

        removed = enforce_retention_policy(self.backups_dir, retention_days=30, dry_run=False)

        self.assertEqual(len(removed), 1, "Chỉ có 1 archive cũ bị xoá")
        self.assertFalse(old_archive.exists(), "Archive cũ phải bị xoá")
        self.assertFalse(old_sha.exists(), "Sha256 cũ phải bị xoá")
        self.assertTrue(new_archive.exists(), "Archive mới phải được giữ lại")
        self.assertTrue(new_sha.exists(), "Sha256 mới phải được giữ lại")

    def test_07_dry_run_creates_no_files(self):
        """Kiểm tra chế độ --dry-run không tạo bất kỳ file nào lên đĩa"""
        clean_backups_dir = self.mock_root / "dry_run_backups"
        result = run_backup_process(
            project_root=self.mock_root,
            backups_dir=clean_backups_dir,
            dry_run=True,
            timestamp_override="20260915_999999"
        )
        self.assertTrue(result["success"])
        self.assertFalse(clean_backups_dir.exists(), "Thư mục backup không được tạo khi chạy dry-run")


if __name__ == "__main__":
    unittest.main()
