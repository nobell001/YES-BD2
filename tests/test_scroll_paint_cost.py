"""Pages stuttered while scrolling (Leo 2026-11-25 「UI页面滑动的时候很卡」).

Every scroll step repaints the whole page.  Each card blended 8 see-through
card-sized shadow layers on every repaint (about 70 % of a frame on 首页),
and pictures were re-filtered on every repaint.  Cards now draw a picture
made once per size and colours; pictures already at screen resolution are
copied as they are.  The look stays the same.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from src.ui.shell import theme, widgets
from src.ui.shell.widgets import Card


def _grab(widget) -> QImage:
    """The widget's own paint on a see-through image (no window background)."""
    image = QImage(widget.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    widget.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return image.convertToFormat(QImage.Format_ARGB32)


def _max_difference(a: QImage, b: QImage) -> int:
    worst = 0
    for y in range(a.height()):
        for x in range(a.width()):
            pa, pb = a.pixelColor(x, y), b.pixelColor(x, y)
            worst = max(
                worst,
                abs(pa.red() - pb.red()),
                abs(pa.green() - pb.green()),
                abs(pa.blue() - pb.blue()),
                abs(pa.alpha() - pb.alpha()),
            )
    return worst


class CardPictureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        widgets._CARDS.clear()
        widgets._cards_bytes[0] = 0

    def test_cards_of_one_size_share_one_picture(self):
        cards = [Card() for _ in range(5)]
        for card in cards:
            card.resize(180, 90)
            _grab(card)
        self.assertEqual(len(widgets._CARDS), 1)

    def test_card_looks_the_same_as_drawing_it_directly(self):
        card = Card()
        card.resize(160, 80)
        cached = _grab(card)
        direct = QImage(cached.size(), QImage.Format_ARGB32_Premultiplied)
        direct.fill(Qt.transparent)
        painter = QPainter(direct)
        widgets.paint_card(painter, QRectF(0, 0, 160, 80), card.edge_colour())
        painter.end()
        direct = direct.convertToFormat(QImage.Format_ARGB32)
        self.assertLessEqual(_max_difference(cached, direct), 3)

    def test_new_colours_after_a_theme_switch(self):
        card = Card()
        card.resize(120, 60)
        try:
            theme.set_theme_mode("light")
            light = _grab(card)
            theme.set_theme_mode("dark")
            dark = _grab(card)
        finally:
            theme.set_theme_mode("light")
        self.assertEqual(len(widgets._CARDS), 2)
        self.assertNotEqual(light.pixelColor(60, 30), dark.pixelColor(60, 30))

    def test_a_fading_edge_is_drawn_over_the_resting_picture(self):
        class Fading(Card):
            edge_fades = True

            def edge_colour(self):
                return QColor("#FF0000")

        card = Fading()
        card.resize(120, 60)
        image = _grab(card)
        # Only the resting picture is kept: hover fades do not fill the cache.
        self.assertEqual(len(widgets._CARDS), 1)
        self.assertEqual(next(iter(widgets._CARDS))[-1], Card.edge_colour(card).rgba())
        left, top, _right, bottom = widgets.SHADOW_MARGINS
        edge = image.pixelColor(left, top + (60 - top - bottom) // 2)
        self.assertGreater(edge.red(), edge.blue())

    def test_a_card_with_its_own_fixed_edge_keeps_it_in_the_picture(self):
        class Outlined(Card):
            def edge_colour(self):
                return QColor("#FF0000")

        card = Outlined()
        card.resize(120, 60)
        _grab(card)
        self.assertEqual(next(iter(widgets._CARDS))[-1], QColor("#FF0000").rgba())

    def test_memory_budget_drops_the_oldest(self):
        saved = widgets._CARDS_BUDGET
        widgets._CARDS_BUDGET = 100 * 100 * 4 * 2
        try:
            for width in (100, 101, 102, 103):
                widgets.card_picture(QSize(width, 100), 1.0, QColor("#FFFFFF"))
            self.assertLessEqual(widgets._cards_bytes[0], widgets._CARDS_BUDGET)
            self.assertLessEqual(len(widgets._CARDS), 2)
        finally:
            widgets._CARDS_BUDGET = saved


class FittedPictureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_picture_is_copied_without_refiltering(self):
        source = QImage(40, 40, QImage.Format_ARGB32)
        for y in range(40):
            for x in range(40):
                source.setPixelColor(x, y, QColor(255, 0, 0) if (x + y) % 2 else QColor(0, 0, 255))
        pixmap = QPixmap.fromImage(source)
        target = QImage(40, 40, QImage.Format_ARGB32_Premultiplied)
        target.fill(Qt.white)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        # Half a pixel off the grid: smoothing would blend each pixel with
        # its neighbours into purple.
        widgets.draw_fitted(painter, QRectF(0.5, 0.5, 40, 40), pixmap, 1.0)
        self.assertTrue(painter.testRenderHint(QPainter.SmoothPixmapTransform))
        painter.end()
        centre = target.pixelColor(20, 20)
        self.assertTrue(centre.red() == 255 or centre.blue() == 255, centre.name())


if __name__ == "__main__":
    unittest.main()
