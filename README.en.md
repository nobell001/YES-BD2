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

- **Run All Dailies**: Guild, House, Tavern, Regulars' Magic Crystals, Quick Hunt, free Draw, junk gear, Refine, Goddess Statue, Mirror Wars, Event battles, Tower of Redemption, Affinity Counseling, quest rewards, Pass, Mail and Event rewards, in order with one press. The weeklies (Arcade menu, House popularity, Craft Gear, Last Night) are in it too.
- **Weekly Farming**: uses Absorb, Assemble and Overpower on the Story Packs for you, spread over the days of the week.
- **Daily Trade Run**: buys, cooks and sells by the sale calendar; you choose how much to keep.
- **Talos textbook**: the month's 9 stages, fought with built-in plans; cleared ones are skipped.
- **Fiend Hunter**: record your own fight once with F8; after that the tool sets each turn's order, positions and skills the same way, then fights.
- **Scheduled Start**: pick a time and the dailies run by themselves, even if the tool was closed.
- **Clone Desktop**: the game runs on a separate desktop in its own window, so your mouse and keyboard stay yours.
- **Run status in the game**: a bar over the game shows what is running, with Pause and Stop; clicks go through it.
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
    <td><img src="docs/images/daily.jpg" alt="Task Setup"></td>
    <td><img src="docs/images/trade.jpg" alt="Trade Run"></td>
    <td><img src="docs/images/maps.jpg" alt="Farming"></td>
  </tr>
  <tr>
    <td align="center">Task Setup: tick what to run</td>
    <td align="center">Trade Run: buy, cook, sell</td>
    <td align="center">Farming: the week's progress at a glance</td>
  </tr>
  <tr>
    <td><img src="docs/images/talos.jpg" alt="Talos textbook"></td>
    <td><img src="docs/images/fiend.jpg" alt="Fiend Hunter"></td>
    <td><img src="docs/images/clone.jpg" alt="Clone Desktop"></td>
  </tr>
  <tr>
    <td align="center">Talos textbook: 9 stages in one press</td>
    <td align="center">Fiend Hunter: follows your own recording</td>
    <td align="center">Clone Desktop: use your PC while it runs</td>
  </tr>
</table>

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

<details>
<summary><b>Setting up the clone desktop</b></summary>

The clone desktop runs the game in a separate desktop window, so you can keep using your PC and your mouse and keyboard are never taken.

**You need**

- Windows 10/11 Pro, Enterprise or Education. Home doesn't work.
- Windows' "Remote Desktop Services" present and not disabled. The clone is this PC connecting to itself over Remote Desktop, and system optimizer/cleanup tools or trimmed Windows builds often touch it. The tool checks first; if it is disabled, press "Turn it on for me" (other PCs still can't connect).
- Your Windows account password (for a Microsoft account, your Microsoft password). A PIN won't work.

**First time**

1. On Home press "Run on Clone Desktop" → "First-time setup", and click "Yes" when Windows asks.
2. On a PC with a Microsoft account limited to Windows Hello sign-in, the tool asks you to press "Turn it off for me".
3. Press "Run on Clone Desktop" again → "Go", and click "Yes" when Windows asks.
4. In the sign-in box type your Windows account password (not the PIN) and tick "Remember my credentials" so you don't have to type it again.
5. When the clone window opens, the game and dailies start by themselves; follow progress in the tool. It keeps running when minimized; closing it with X ends the clone and closes the game and tool inside.

To undo: Settings → "Undo Clone Desktop setup" → "Undo".

**Common problems**

| Problem | What to do |
|---|---|
| Sign-in fails, password rejected | Type the account password, not the PIN; for a Microsoft account use the Microsoft password; if only Windows Hello is allowed, press "Turn it off for me" first |
| "516" or "Remote access to the server is not enabled / the remote computer is turned off" | The clone couldn't be reached; it's not a password problem. Try in order: reopen the tool and press again → restart the PC and try again (often needed right after setup) → PCs that used optimizer/cleanup tools or RDP Wrapper may not support it. If it still fails, open an [issue](https://github.com/nobell001/YES-BD2/issues) with `%LOCALAPPDATA%\bd2-auto\clone-desktop\viewer.log` |
| The clone program is gone | An antivirus may have deleted it: add `%LOCALAPPDATA%\bd2-auto\clone-desktop` to its trusted list, then press "First-time setup" again |
| The PC won't shut down | Close the clone window with X first, or in Task Manager → Users, sign out the same-named user with fewer processes |

</details>

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
