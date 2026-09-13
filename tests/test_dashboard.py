"""Layout rules the Ruijie page depends on to look right under argon.

Both checks here guard against a regression that is invisible to every other
test: the page renders, the buttons work, and only the rendering is wrong.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / 'package/ruijie-auth/files/usr/lib/lua/luci/view/ruijie'
STATIC = ROOT / 'package/ruijie-auth/files/www/luci-static/resources/ruijie'

# Elements argon styles globally, so a page cannot use them as plain containers.
# header carries the worst of it: argon hangs a 2rem header::after band off the
# bare element, which lands on top of whatever the page put inside it.
HIJACKED = ('header', 'nav', 'main', 'footer')


class DashboardMarkupTests(unittest.TestCase):
    def test_views_avoid_elements_the_theme_styles(self):
        for path in sorted(VIEWS.glob('*.htm')):
            # Only the literal markup: a tag named inside a <% %> block is
            # server-side code and never reaches the browser.
            body = re.sub(r'<%.*?%>', ' ', path.read_text(encoding='utf-8'), flags=re.S)
            for tag in HIJACKED:
                self.assertIsNone(re.search(r'<%s[\s>]' % tag, body),
                                  '%s uses a bare <%s> element' % (path.name, tag))


class DashboardStylesheetTests(unittest.TestCase):
    def test_button_toolbars_do_not_need_a_script(self):
        # The grid used to key on a class the page script injected. Anything
        # that stopped the script -- a cached copy, an error, JS off -- left
        # every button in a column of its own, which is what the theme's
        # .cbi-section-node{flex-direction:column} does by default.
        css = (STATIC / 'dashboard.css').read_text(encoding='utf-8')
        self.assertIn(':has(> .cbi-section-node > .cbi-value > .btn)', css)
        self.assertNotIn('ruijie-actions', css)
        self.assertNotIn('ruijie-actions',
                         (STATIC / 'dashboard.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
