# Trade shop recognition fixtures

These masked fixtures come from the user-provided 2026-08-12 trade recording.
Only the production relative shop item/status ROI is retained. Its 1920x1080
reference bounds `(360, 140)-(1620, 510)` scale to `(270, 105)-(1215, 383)`
in the recorded 1440x810 game client; every other pixel is black. Account,
desktop, notification, and Codex UI regions are excluded.

| Fixture | Source time | Expected `soled-out.png` result |
| --- | ---: | --- |
| `before_purchase.png` | 42.0s | Rejected before the purchase result appears. |
| `after_purchase.png` | 43.0s | Accepted after the sold-out labels appear. |
| `sell_page.png` | 61.5s | Rejected after switching to the sell page. |

`sale_120_markers_fhd.png` is a privacy-minimized 2026-08-16 live sell-page
frame. Only three exact `52x14` rendered `↑120%` marker ROIs at
`(493,563)`, `(825,563)`, and `(1157,563)` are retained; every other pixel is
black. It regression-tests the real marker rendering without retaining the
shop page, account information, or surrounding game state.

The source recording was supplied by the repository owner for diagnosing and
regression-testing this automation flow.

`price_list_owned_only_leo_2k_as_1080.jpg` is Leo's 2560x1440 upload of the
出售 page with the 价目表 open (仅显示已拥有的道具 ticked), resized to
1920x1080.  The account's gold total and status at the top right are blacked
out.  tests/test_page_lookalikes.py checks that the 价目表 title read says yes
on it and on no other page, because 跑商 presses its ✕ again, then Esc, only
while that title reads.

`no_favorites_fhd.png` is a privacy-minimized 2026-10-25 player frame
(v0.2.13 问题摘要, 1920x1080 shop page with nothing favourited). Only the
fifteen star ROIs around `SHOP_FAVORITE_POINTS` are retained; every other
pixel is black. Slots 1-7 read gray: the buy stops with the reason instead of
pressing the fixed 确认.
