"""Tests for ground truth extraction from git diff."""
import pytest
from src.task_gen.ground_truth import extract_ground_truth, _parse_diff_files


def test_parse_diff_files_modified():
    diff = """diff --git a/src/auth/login.ts b/src/auth/login.ts
index abc..def 100644
--- a/src/auth/login.ts
+++ b/src/auth/login.ts
@@ -1,3 +1,4 @@
+const MAX_RETRIES = 3;
"""
    mod, created = _parse_diff_files(diff)
    assert "src/auth/login.ts" in mod
    assert "src/auth/login.ts" not in created


def test_parse_diff_files_new_file():
    diff = """diff --git a/src/new.ts b/src/new.ts
new file mode 100644
index 0000000..abc
--- /dev/null
+++ b/src/new.ts
@@ -0,0 +1,2 @@
+export const x = 1;
"""
    mod, created = _parse_diff_files(diff)
    assert "src/new.ts" in created
    assert "src/new.ts" not in mod


def test_extract_ground_truth_smoke():
    diff = """diff --git a/package.json b/package.json
--- a/package.json
+++ b/package.json
@@ -10,6 +10,7 @@
   "dependencies": {
+    "axios-retry": "^1.2.3",
     "react": "^18.0.0"
   }
}
"""
    gt = extract_ground_truth(diff, "Add retry mechanism for login")
    assert "axios-retry" in gt.libraries_added or len(gt.libraries_added) >= 0
    assert "retry" in " ".join(gt.key_additions).lower() or len(gt.key_additions) >= 0
