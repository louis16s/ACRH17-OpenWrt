from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/verify-template.py'


class TemplateTests(unittest.TestCase):
    def compile(self, source):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'view.htm'
            path.write_text(source, encoding='utf-8')
            return subprocess.run([sys.executable, str(SCRIPT), str(path)],
                                  capture_output=True, text=True)

    def test_rejects_the_lua_comment_tag(self):
        # "<%--" is not a comment: luci reads the whitespace-stripping "<%-"
        # and then a bare "-", which is a syntax error on the running router.
        result = self.compile('<%-- note --%>\n')
        self.assertEqual(1, result.returncode)
        self.assertIn(':1: ', result.stderr)
        self.assertIn("unexpected symbol near '-'", result.stderr)

    def test_rejects_an_unterminated_tag(self):
        self.assertEqual(1, self.compile('<% if x then\n').returncode)

    def test_rejects_a_block_left_open(self):
        result = self.compile('<% if x then %>\ntext\n')
        self.assertEqual(1, result.returncode)
        self.assertIn("'end' expected", result.stderr)

    def test_keeps_markup_quotes_and_backslashes_inside_the_literal(self):
        result = self.compile('<div class="a">quote " and backslash \\ end</div>\n')
        self.assertEqual(0, result.returncode, result.stderr)

    def test_accepts_every_tag_type(self):
        result = self.compile('<% local x = 1 %>\n<%= x %>\n<%+ header %>\n'
                              '<%# comment %>\n<%: translate %>\n<%- x = 2 -%>\n')
        self.assertEqual(0, result.returncode, result.stderr)

    def test_reports_the_template_line_not_the_generated_one(self):
        result = self.compile('markup\nmarkup\nmarkup\n<%-- note --%>\n')
        self.assertIn(':4: ', result.stderr)

    def test_repository_templates_compile(self):
        templates = sorted((ROOT / 'package').rglob('*.htm'))
        self.assertTrue(templates)
        for path in templates:
            with self.subTest(template=str(path.relative_to(ROOT))):
                result = subprocess.run([sys.executable, str(SCRIPT), str(path)],
                                        capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main()
