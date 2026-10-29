<p align="center">
  <img src="icons/icon.png" alt="YES-BD2" width="140">
</p>

<h1 align="center">YES-BD2</h1>

<p align="center"><b>打開工具，按一下，棕色塵埃2 的日常就跑完了。</b></p>

<p align="center">
  <a href="README.md">简体中文</a> · <b>繁體中文</b> · <a href="README.en.md">English</a> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a>
</p>

<p align="center">
  <a href="https://github.com/nobell001/YES-BD2/releases/latest"><img src="https://img.shields.io/github/v/release/nobell001/YES-BD2?label=%E4%B8%8B%E8%BC%89&color=8b7fd6" alt="下載"></a>
  <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-8b7fd6" alt="Windows">
  <img src="https://img.shields.io/badge/1080p%20%7C%202K%20%7C%204K-8b7fd6" alt="1080p 2K 4K">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/GPL--3.0-8b7fd6" alt="GPL-3.0"></a>
</p>

> [!IMPORTANT]
> **玩家請到 [Releases](https://github.com/nobell001/YES-BD2/releases/latest) 下載 `yes-bd2-win32-online-setup.exe` 安裝。** 頁面上的 `Source code` 和綠色「Code → Download ZIP」是原始碼，不是安裝檔。
>
> **只支援電腦版（桌面應用程式）的棕色塵埃2**，不支援手機和模擬器。
>
> **遊戲語言請先切成簡體中文。** 工具是看遊戲畫面上的字來操作的，目前只認得簡體中文，**很快會支援更多語言**。
> 工具自己的介面有 5 種語言，在工具的「設定 → 語言」切換。

## 免責宣告

- **免費、開源**：個人學習 Python、影像識別、OCR 與介面自動化的作品，不收任何費用。
- **只看畫面、模擬滑鼠**：不讀取、不修改遊戲記憶體和遊戲檔案。
- **風險自負**：自動化工具可能違反遊戲或平台的服務條款，帳號被限制、封禁或獎勵被回收，由使用者自行承擔。
- **非官方**：和棕色塵埃2 的開發商、發行商及平台沒有任何關係。
- **禁止營利**：不接受代練、賣腳本、付費代掛等任何營利用途。

<p align="center"><img src="docs/images/home.jpg" alt="首頁" width="760"></p>

## 功能

- **一鍵日常**：公會、小屋、酒館、常客聖石、快速狩獵、免費抽抽樂、爛裝分解、精煉、女神像、鏡中之戰、活動戰鬥、救贖之塔、親密度談心、任務獎勵、通行證、郵件、活動獎勵，按一下按順序跑完。週常（街機選單、小屋人氣、製作裝備、末日之書）也在裡面。
- **每週跑圖**：故事遊戲卡帶的吸收、召集、壓制自動放，一週的量分到每天跑。
- **每日跑商**：買進、做料理、照出售日曆賣出，要留多少自己定。
- **塔洛斯教材**：每月 9 關照內建的打法自動打，打過的跳過。
- **魔獸追蹤者**：先用 F8 錄一場自己的打法，之後每回合的順序、站位和技能都照錄好的自動排好再開打。
- **定時啟動**：設定幾點，時間到了自動跑日常，工具沒開也會自己打開。
- **桌面分身**：遊戲在另一個獨立的桌面視窗裡跑，你照常用電腦，滑鼠鍵盤不會被搶。
- **遊戲裡顯示進度**：跑的時候遊戲上方顯示正在跑什麼，有暫停、停止按鈕，不擋點擊。
- **今日報表**：今天跑了什麼、哪一項失敗、為什麼失敗，一眼看完。

## 特點

- **認不準就不按**：畫面沒認清楚就不點，卡住會回主頁或停下來，不會亂點。
- **不花錢**：付費體力、鑽石、付費道具一律不碰，免費次數用完就停。
- **不用盯著**：跑完會在 Windows 右下角通知你。
- **會自己更新**：每次打開工具都會檢查新版本，不用重新下載。
- **1080p、2K、4K 都能用**：只要是 16:9。

## 三步開始

1. 到 [Releases](https://github.com/nobell001/YES-BD2/releases/latest) 下載 **`yes-bd2-win32-online-setup.exe`**（約 5 MB），安裝。安裝時會連網下載其餘部分，請保持網路連線。如果 Windows 跳出「已保護您的電腦」，按「其他資訊 → 仍要執行」（安裝檔沒有付費簽章，新發布的檔案都會這樣）。
2. 把遊戲語言切成**簡體中文**，畫質選 FHD。
3. 打開工具，按「**一鍵完成日常**」。遊戲沒開的話，工具會先問你要不要幫你開。

> 想邊跑邊用電腦？按「**在桌面分身跑**」（需要 Windows 專業版，第一次要設定一下）。

## 更多畫面

<table>
  <tr>
    <td><img src="docs/images/daily.jpg" alt="任務設定"></td>
    <td><img src="docs/images/trade.jpg" alt="跑商"></td>
    <td><img src="docs/images/maps.jpg" alt="跑圖"></td>
  </tr>
  <tr>
    <td align="center">任務設定：要跑哪些自己勾</td>
    <td align="center">跑商：買、做、賣</td>
    <td align="center">跑圖：一週進度一目瞭然</td>
  </tr>
  <tr>
    <td><img src="docs/images/talos.jpg" alt="塔洛斯教材"></td>
    <td><img src="docs/images/fiend.jpg" alt="魔獸追蹤者"></td>
    <td><img src="docs/images/clone.jpg" alt="桌面分身"></td>
  </tr>
  <tr>
    <td align="center">塔洛斯教材：每月 9 關一鍵打</td>
    <td align="center">魔獸追蹤者：照自己錄的打法排</td>
    <td align="center">桌面分身：邊跑邊用電腦</td>
  </tr>
</table>

## 跑之前注意

- 不要鎖定螢幕、關螢幕或讓電腦睡眠，遊戲視窗不要最小化。
- 關掉顯示卡濾鏡、銳化、FPS 顯示、錄影浮動視窗這類蓋在畫面上的東西。
- 一般模式會用你的滑鼠，跑的時候別動電腦；要同時用電腦就用桌面分身。
- 工具每次開啟會要系統管理員權限（Windows 會問一次），點「是」就好。

## 遇到問題

| 狀況 | 怎麼辦 |
|---|---|
| 找不到遊戲 | 先把遊戲打開；裝在特別的位置的話，見下面「從原始碼執行」的路徑設定 |
| 認不出畫面 | 檢查遊戲語言是不是簡體中文、是不是 16:9、有沒有東西擋住遊戲 |
| 某一項一直失敗 | 打開「今日報表」看失敗原因和截圖，到 [Issues](https://github.com/nobell001/YES-BD2/issues) 告訴我們 |

回報時附上今日報表的截圖最有幫助。截圖可能看得到遊戲帳號資訊，貼之前先看一下。

<details>
<summary><b>桌面分身怎麼設定</b></summary>

桌面分身讓遊戲在另一個獨立的桌面視窗裡跑，你照常用電腦，滑鼠鍵盤不會被搶。

**需要**

- Windows 10/11 專業版、企業版或教育版。家用版不能用。
- Windows 的「遠端桌面服務」還在、沒被停用。分身是這台電腦用遠端桌面連自己，用過系統優化／精簡工具或精簡版 Windows 的電腦常會動到它；工具會先檢查，被停用時可以按「幫我打開」（不會讓別的電腦連進來）。
- 知道 Windows 帳號的密碼（Microsoft 帳號就是微軟帳號密碼）。PIN 不行。

**第一次**

1. 首頁按「在桌面分身跑」→「第一次設定」，Windows 確認按「是」。
2. 用 Microsoft 帳號、而且只允許 Windows Hello 登入的電腦，工具會請你按「幫我關掉」。
3. 再按一次「在桌面分身跑」→「前往」，Windows 確認按「是」。
4. 登入框打 Windows 帳號密碼（不是 PIN），勾「記住我的認證」，之後就不用再打。
5. 分身視窗打開後，遊戲和日常會自己開始，進度在工具裡看。分身視窗縮小也照跑；按 X 會結束分身，裡面的遊戲和工具一起關。

不想用了：「設定」→「還原桌面分身」→「還原」。

**常見問題**

| 狀況 | 怎麼辦 |
|---|---|
| 登入失敗、密碼不對 | 打帳號密碼不是 PIN；Microsoft 帳號要打微軟帳號密碼；只允許 Windows Hello 的話先按「幫我關掉」 |
| 出現「516」或「未啟用對伺服器的遠端存取／遠端電腦已關閉」 | 這是連不上分身，不是密碼問題。依序試：重開工具再按一次 → 重新開機再試（剛設定完常要重開機）→ 用過系統優化／精簡工具或裝過 RDP Wrapper 的電腦可能不能用。還不行請到 [Issues](https://github.com/nobell001/YES-BD2/issues) 附上 `%LOCALAPPDATA%\bd2-auto\clone-desktop\viewer.log` |
| 分身程式不見了 | 防毒軟體（例如 360、火絨）可能刪掉了：把 `%LOCALAPPDATA%\bd2-auto\clone-desktop` 設為信任，再按「第一次設定」 |
| 電腦關不了機 | 先按 X 關掉分身視窗；或在工作管理員 →「使用者」裡登出處理程序較少的同名使用者 |

</details>

## 下載哪個檔案

| 檔案 | 說明 |
|---|---|
| `yes-bd2-win32-online-setup.exe` | **選這個**。約 5 MB，安裝時再連網下載其餘部分，通常比較快 |
| `yes-bd2-win32-Full-setup.exe` | 完整離線安裝包，檔案很大；安裝時不能連網才用 |

GitHub 自動附的 `Source code` 壓縮包和 `yes-bd2-win32.zip` 不是安裝包，一般玩家不用下載。

<details>
<summary><b>從原始碼執行（開發者）</b></summary>

原始碼方式**不會自動更新**，需要自己 `git pull`。

```powershell
git clone https://github.com/nobell001/YES-BD2.git
cd YES-BD2
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\start.bat
```

遊戲不在預設位置時，啟動前先設定：

```powershell
$env:OK_BD2_LAUNCHER_PATH = "C:\Path\To\Browndust2Starter.exe"
$env:OK_BD2_GAME_PATH = "D:\Path\To\BrownDust II.exe"
```

依賴以 `pyproject.toml` 和 `uv.lock` 為準，`requirements*.txt` 由 uv 匯出，不要手改。

```powershell
.\scripts\run_checks.ps1 -Mode Focused -Tests tests.test_pvp_task   # 只跑受影響的測試
.\scripts\run_checks.ps1 -Mode Final                                # 提交前完整檢查
```

更多：[架構說明](docs/architecture.md) · [發布檢查清單](docs/release-checklist.md) · [PyAppify 發布流程](docs/pyappify-release-flow.md)

</details>

## 致謝

YES-BD2 基於 [GodRaymond233/ok-bd2](https://github.com/GodRaymond233/ok-bd2) 製作，框架和一鍵更新來自 [ok-script](https://github.com/ok-oldking/ok-script)。也謝謝：

- [BD2DB 圖鑑](https://browndust2-db.souseha.com/)：遊戲名稱與資料
- B站 [時樂淵](https://space.bilibili.com/14949646)：跑商售賣物品表
- [BetterGI](https://github.com/babalae/better-genshin-impact)、[ChildStream](https://github.com/mattxslv/childstream)：桌面分身的做法與畫面視窗
- [JZPPP/MaaBD2](https://github.com/JZPPP/MaaBD2)：地圖採集路線參考

工具「關於」頁有完整致謝；第三方依賴與素材見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 授權

程式碼以 [GPL-3.0](LICENSE) 發布（與 ok-bd2 相同）。遊戲名稱、截圖、圖示與介面素材的權利屬於各自的權利方。
