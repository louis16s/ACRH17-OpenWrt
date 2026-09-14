"""Layout rules the Ruijie page depends on to look right under argon.

The checks here guard against a regression that is invisible to every other
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

    def test_section_surfaces_follow_the_theme(self):
        # The sections were once painted with a fixed translucent navy. That
        # only looks right on a dark page: over argon's default light theme it
        # renders as grey mud on white, which is how the page looked until the
        # surface moved onto the theme's own variables. argon redefines
        # --bg-light in dark.css, so reading it keeps both modes working.
        css = (STATIC / 'dashboard.css').read_text(encoding='utf-8')
        self.assertIn('var(--bg-light', css)
        self.assertNotIn('rgba(17, 27, 45, .5)', css)

    def test_buttons_are_not_stretched_across_the_row(self):
        # A 1fr track grows the button until the row is full, which on a wide
        # screen throws three short labels to opposite corners. The track has
        # to stop growing instead.
        css = (STATIC / 'dashboard.css').read_text(encoding='utf-8')
        self.assertNotIn('minmax(9.5rem, 1fr)', css)
        self.assertIn('max-width: 14rem', css)


if __name__ == '__main__':
    unittest.main()
