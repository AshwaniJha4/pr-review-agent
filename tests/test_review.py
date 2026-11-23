from review import Finding, annotate_diff, keep_valid

DIFF = """diff --git a/calc.py b/calc.py
index 111..222 100644
--- a/calc.py
+++ b/calc.py
@@ -1,3 +1,4 @@
 def area(w, h):
-    return w * h
+    # metres to mm by mistake
+    return w * h * 1000
""" + " \n"  # context line: a single space, kept explicit so editors don't strip it


def test_annotate_numbers_new_file_lines():
    text, lines = annotate_diff(DIFF)
    assert lines == {"calc.py": {1, 2, 3, 4}}
    assert "    3  +    return w * h * 1000" in text
    assert "    -  -    return w * h" in text


def test_keep_valid_drops_lines_outside_diff():
    _, lines = annotate_diff(DIFF)
    findings = [
        Finding(file="calc.py", line=3, severity="high", message="unit error"),
        Finding(file="calc.py", line=40, severity="low", message="not in diff"),
        Finding(file="other.py", line=1, severity="low", message="wrong file"),
    ]
    assert [f.line for f in keep_valid(findings, lines)] == [3]
