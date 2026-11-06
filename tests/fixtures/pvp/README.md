# PVP recognition fixtures

`recent_pvp_home_fhd.png` is a privacy-minimized 1920×1080 regression frame
derived from the 2026-08-12 live home capture. Only the exact recent-cartridge
template bounding box `(1659, 935, 94, 82)` is retained; every other pixel is
black. It verifies the real rendered PVP cover rather than a synthetic copy of
the template asset.

`pvp_hub_top_bar_shifted_fhd.png` (BUG-20260905-08, RPT-20260905-195025) is the
same kind of strip-only canvas for the live PVP-hub top bar whose whole bar sat
about 4 px higher than calibration. Only the medal-template search strip
`(793, 29, 340, 55)` is retained.

`home_bright_skin_cues_fhd.png` (2026-10-12 player report, v0.1.24) is a
player's 主页 with a bright angel skin, rebuilt from the 问题摘要 screenshot.
Only the 主页 checks' boxes are kept: the left icon column
`(110, 165, 430, 155)`, the 抽抽乐 label `(110, 993, 95, 54)` and the medal
strip `(793, 29, 340, 55)`, where a soft glow passed as the medal once its
contrast was stretched up to the template's.

## server_disconnect_6_over_home_1440.jpg

The game's 「與伺服器連接中斷。重新開始遊戲 (-6)」 notice over a dimmed 主页.
Live, 2560x1440 繁中 client, 2026-11-06 16:17 (the same account was logged in
on another PC). The account name and avatar are blurred.
