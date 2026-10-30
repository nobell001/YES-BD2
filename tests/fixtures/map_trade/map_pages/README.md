# Map page mode fixtures

These 1920x1080 PNGs are client-area crops derived from the three user-provided
map screenshots captured on 2026-08-13. The 32px Windows title bar and 1px side
borders were removed. Every unrelated region was blacked out; only the visual
signals needed by the map-page detector remain.

- `direct.png`: interaction-button direct teleport page.
- `generate.png`: skill-opened generation teleport page.
- `sandbox_large.png`: upper-left-button sandbox large map.

Expected modes are mutually exclusive: `direct_teleport`,
`generate_teleport`, and `sandbox_large_map` respectively.

Player frames (YES-BD2 #24, 2026-10-13, 1080p): cut from the game picture in
the tool's 问题摘要 and scaled back to 1920x1080, so they are softer than a
capture. No account details are on them.

- `snow_large_map_player_fhd.jpg`: sandbox large map on snow (华特波尔雪山);
  both page arrows miss their templates.
- `auto_move_dialog_player_fhd.jpg`: sandbox large map (雷瓦汀基地) under the
  game's 自动移动 dialog 「是否自动移动前往所选目的地？」.
- `hunting_ground_map_player_fhd.jpg`: sandbox large map of a chapter's hunting
  ground (第9章 「战斗 守山人休息处」, player report 2026-10-23); its title is
  none of the cards' own maps.

Leo's 2K frames (2026-10-30, 2560x1440 scaled to 1920x1080), 第16章 安全
迪尔索特港口城市; the player's report (v0.2.21, 2026-10-29) stopped here with
「区域地图上找不到传送阵图标」:

- `port_city_inn_covers_circle_leo_2k_as_1080.jpg`: area map whose teleport
  circle is drawn under the 迪尔索特旅馆 icon (~(481, 469)); only an edge of
  its ring shows.
- `port_city_inn_menu_leo_2k_as_1080.jpg`: the same map after pressing the
  inn's place: a menu 「魔法阵 / 旅馆」 opened beside it.
