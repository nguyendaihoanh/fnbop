import os
import json
import time
import tempfile
import threading
import unittest
from backend.services.storage import safe_json_read, safe_json_write, FallbackFileLock


class TestStorageConcurrency(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, "concurrency_test.json")
        with open(self.test_file, 'w', encoding='utf-8') as f:
            json.dump({"count": 0, "logs": []}, f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_concurrent_read_write(self):
        """Simulate 30 threads reading and updating the same JSON file simultaneously."""
        errors = []
        num_threads = 30

        def worker(thread_id):
            for i in range(5):
                try:
                    data = safe_json_read(self.test_file, default={"count": 0, "logs": []})
                    if not isinstance(data, dict):
                        errors.append(f"Thread {thread_id}: data is not dict (got {type(data)})")
                        continue
                    
                    data["count"] = data.get("count", 0) + 1
                    data["logs"].append(f"T{thread_id}_{i}")
                    
                    success = safe_json_write(self.test_file, data)
                    if not success:
                        errors.append(f"Thread {thread_id}: write failed at iteration {i}")
                    time.sleep(0.01)
                except Exception as e:
                    errors.append(f"Thread {thread_id}: exception {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrency errors occurred: {errors}")
        final_data = safe_json_read(self.test_file)
        self.assertIsNotNone(final_data)
        self.assertGreater(final_data["count"], 0)


if __name__ == "__main__":
    unittest.main()
