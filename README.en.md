<p align="center">
  <img src="icons/icon.png" alt="YES-BD2" width="140">
</p>

<h1 align="center">YES-BD2</h1>

<p align="center"><b>Open the tool, press one button, and your Brown Dust 2 dailies are done.</b></p>

<p align="center">
  <a href="README.md">简体中文</a> · <a href="README.zh-TW.md">繁體中文</a> · <b>English</b> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a>
</p>

<p align="center">
  <a href="https://github.com/nobell001/YES-BD2/releases/latest"><img src="https://img.shields.io/github/v/release/nobell001/YES-BD2?label=download&color=8b7fd6" alt="Download"></a>
  <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-8b7fd6" alt="Windows">
  <img src="https://img.shields.io/badge/1080p%20%7C%202K%20%7C%204K-8b7fd6" alt="1080p 2K 4K">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/GPL--3.0-8b7fd6" alt="GPL-3.0"></a>
</p>

> [!IMPORTANT]
> **Players: download `yes-bd2-win32-online-setup.exe` from [Releases](https://github.com/nobell001/YES-BD2/releases/latest) and install it.** The `Source code` archives and the green **Code → Download ZIP** are the source code, not the installer.
>
> **For the PC (desktop app) version of Brown Dust 2 only**; phones and emulators are not supported.
>
> **Switch the game language to Simplified Chinese first.** The tool reads the text on the game screen, and for now it only reads Simplified Chinese. **More game languages are coming soon.**
> The tool's own interface has 5 languages; change it under **Settings → Language** in the tool.

## Disclaimer

- **Free and open source**: a personal learning project in Python, image recognition, OCR and UI automation. It costs nothing.
- **Screen and mouse only**: it never reads or changes game memory or game files.
- **Your own risk**: automation tools may break the game's or platform's terms of service. Restrictions, bans or reward rollbacks are on the user.
- **Unofficial**: not related to the developers, publishers or platforms of Brown Dust 2.
- **No profit use**: boosting, selling scripts, paid hosting or any other for-profit use is not allowed.

<p align="center"><img src="docs/images/home.jpg" alt="Home" width="760"></p>

## Features

- **Run All Dailies**: Guild, House, Tavern, Regulars' Magic Crystals, Quick Hunt, free Draw, junk gear, Refine, Goddess Statue, Mirror Wars, Event battles, quest rewards, Pass, Mail and Event rewards, in order with one press.
- **Weekly Farming**: uses Absorb, Assemble and Overpower on the Story Packs for you, spread over the days of the week.
- **Daily Trade Run**: buys, cooks and sells by the sale calendar; you choose how much to keep.
- **Run All Weeklies**: Arcade menu, House popularity, Craft Gear, Last Night.
- **Clone Desktop**: the game runs on a separate, invisible desktop, so your mouse and keyboard stay yours.
- **Fiend Hunter**: record your own fight once with F8; after that the tool sets each turn's order, positions and skills the same way, then fights.
- **Today's Report**: what ran today, what failed and why, at a glance.

## Highlights

- **No guessing**: it only clicks once the screen is clearly recognised. When stuck it goes back Home or stops.
- **No spending**: paid stamina, diamonds and paid items are never touched. It stops when the free attempts run out.
- **No babysitting**: a Windows notification tells you when it's done.
- **Updates itself**: every time it opens it checks for a new version, so there is nothing to download again.
- **1080p, 2K and 4K**: any 16:9 resolution.

## Start in three steps

1. Download **`yes-bd2-win32-online-setup.exe`** (about 5 MB) from [Releases](https://github.com/nobell001/YES-BD2/releases/latest) and install it. It downloads the rest while installing, so stay online. If Windows shows "Windows protected your PC", click **More info → Run anyway** (the installer isn't code-signed, so new releases get this warning).
2. Set the game language to **Simplified Chinese** and the graphics preset to FHD.
3. Open the tool and press **Run All Dailies**. If the game isn't open, the tool asks whether to start it for you.

> Want to use your PC while it runs? Press **Run on Clone Desktop** (needs Windows Pro; a one-time setup the first time).

## More screens

<table>
  <tr>
    <td><img src="docs/images/daily.jpg" alt="Daily Setup"></td>
    <td><img src="docs/images/trade.jpg" alt="Trade Run"></td>
    <td><img src="docs/images/maps.jpg" alt="Farming"></td>
  </tr>
  <tr>
    <td align="center">Daily Setup: tick what to run</td>
    <td align="center">Trade Run: buy, cook, sell</td>
    <td align="center">Farming: the week's progress at a glance</td>
  </tr>
</table>

<p align="center"><img src="docs/images/fiend.jpg" alt="Fiend Hunter" width="760"><br><sub>Fiend Hunter: each turn's order, positions and skills follow your own recording</sub></p>

<sub>Screenshots show the Simplified Chinese interface.</sub>

## Before you run it

- Don't lock the screen, turn it off or let the PC sleep, and don't minimise the game window.
- Turn off GPU filters, sharpening, FPS counters, recording overlays and anything else drawn over the game.
- The normal mode uses your mouse, so leave the PC alone while it runs. To keep working, use Clone Desktop.
- The tool asks for administrator rights each time it opens (Windows asks once); click "Yes".

## Something wrong?

| Problem | What to do |
|---|---|
| Can't find the game | Open the game first. If it is installed somewhere unusual, see the path settings under "Run from source" below |
| Can't recognise the screen | Check the game language is Simplified Chinese, the resolution is 16:9, and nothing covers the game |
| One item keeps failing | Open Today's Report for the reason and screenshot, then tell us in [Issues](https://github.com/nobell001/YES-BD2/issues) |

A screenshot of Today's Report helps most. It may show your in-game account details, so check before posting.

## Which file to download

| File | Notes |
|---|---|
| `yes-bd2-win32-online-setup.exe` | **Pick this one.** About 5 MB; fetches the rest while installing, usually faster |
| `yes-bd2-win32-Full-setup.exe` | Full offline installer, a large file; only if you can't be online while installing |

The `Source code` archives GitHub adds and `yes-bd2-win32.zip` are not installers; players don't need them.

<details>
<summary><b>Run from source (developers)</b></summary>

Running from source **does not update automatically**; use `git pull`.

```powershell
git clone https://github.com/nobell001/YES-BD2.git
cd YES-BD2
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\start.bat
```

If the game is not in the default location, set these before starting:

```powershell
$env:OK_BD2_LAUNCHER_PATH = "C:\Path\To\Browndust2Starter.exe"
$env:OK_BD2_GAME_PATH = "D:\Path\To\BrownDust II.exe"
```

Dependencies come from `pyproject.toml` and `uv.lock`; `requirements*.txt` are exported by uv, so don't edit them by hand.

```powershell
.\scripts\run_checks.ps1 -Mode Focused -Tests tests.test_pvp_task   # only the affected tests
.\scripts\run_checks.ps1 -Mode Final                                # full check before committing
```

More: [Architecture](docs/architecture.md) · [Release checklist](docs/release-checklist.md) · [PyAppify release flow](docs/pyappify-release-flow.md) (in Chinese)

</details>

## Thanks

YES-BD2 is built on [GodRaymond233/ok-bd2](https://github.com/GodRaymond233/ok-bd2); the framework and one-click updates come from [ok-script](https://github.com/ok-oldking/ok-script). Thanks also to:

- [BD2DB](https://browndust2-db.souseha.com/): game names and data
- [時樂淵](https://space.bilibili.com/14949646) on bilibili: the trade-run selling sheet
- [BetterGI](https://github.com/babalae/better-genshin-impact), [ChildStream](https://github.com/mattxslv/childstream): the Clone Desktop approach and viewer window
- [JZPPP/MaaBD2](https://github.com/JZPPP/MaaBD2): map collection routes

The tool's About page lists every credit; third-party dependencies and assets are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

The code is released under [GPL-3.0](LICENSE), the same as ok-bd2. Game names, screenshots, icons and UI assets belong to their respective owners.
