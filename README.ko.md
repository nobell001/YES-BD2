<p align="center">
  <img src="icons/icon.png" alt="YES-BD2" width="140">
</p>

<h1 align="center">YES-BD2</h1>

<p align="center"><b>도구를 열고 버튼 하나만 누르면 브라운더스트2 일일 콘텐츠가 끝납니다.</b></p>

<p align="center">
  <a href="README.md">简体中文</a> · <a href="README.zh-TW.md">繁體中文</a> · <a href="README.en.md">English</a> · <a href="README.ja.md">日本語</a> · <b>한국어</b>
</p>

<p align="center">
  <a href="https://github.com/nobell001/YES-BD2/releases/latest"><img src="https://img.shields.io/github/v/release/nobell001/YES-BD2?label=%EB%8B%A4%EC%9A%B4%EB%A1%9C%EB%93%9C&color=8b7fd6" alt="다운로드"></a>
  <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-8b7fd6" alt="Windows">
  <img src="https://img.shields.io/badge/1080p%20%7C%202K%20%7C%204K-8b7fd6" alt="1080p 2K 4K">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/GPL--3.0-8b7fd6" alt="GPL-3.0"></a>
</p>

> [!IMPORTANT]
> **플레이어는 [Releases](https://github.com/nobell001/YES-BD2/releases/latest)에서 `yes-bd2-win32-online-setup.exe`를 내려받아 설치하세요.** `Source code`와 초록색 **Code → Download ZIP**은 소스 코드이며 설치 파일이 아닙니다.
>
> **브라운더스트2 PC 버전(데스크톱 앱) 전용입니다.** 모바일과 에뮬레이터는 지원하지 않습니다.
>
> **먼저 게임 언어를 중국어 간체(简体中文)로 바꿔 주세요.** 도구는 게임 화면의 글자를 읽어서 동작하기 때문에 지금은 중국어 간체만 읽을 수 있습니다. **다른 언어도 곧 지원합니다.**
> 도구 자체 화면은 5개 언어를 지원하며, 도구의 **설정 → 언어**에서 바꿀 수 있습니다.

## 면책 조항

- **무료·오픈소스**: Python, 이미지 인식, OCR, UI 자동화를 배우기 위한 개인 프로젝트이며 비용이 들지 않습니다.
- **화면을 보고 마우스만 움직임**: 게임 메모리나 게임 파일을 읽거나 바꾸지 않습니다.
- **본인 책임**: 자동화 도구는 게임이나 플랫폼의 이용 약관을 위반할 수 있습니다. 계정 제한·정지·보상 회수의 위험은 사용자가 집니다.
- **비공식**: 브라운더스트2의 개발사, 운영사, 플랫폼과 아무런 관계가 없습니다.
- **영리 이용 금지**: 대리 진행, 스크립트 판매, 유료 대행 등 영리 목적의 이용을 허용하지 않습니다.

<p align="center"><img src="docs/images/home.jpg" alt="홈" width="760"></p>

## 기능

- **일일 일괄 실행**: 길드, 마이홈, 주점, 단골 성석, 빠른 사냥, 무료 뽑기, 쓰지 않는 장비, 재련, 여신상, 거울전쟁, 이벤트 전투, 퀘스트 보상, 패스, 우편, 이벤트 보상을 버튼 하나로 순서대로.
- **주간 파밍**: 스토리팩에서 흡수·소집·제압을 자동으로 쓰고, 한 주 분량을 매일 나눠서 진행.
- **일일 교역 파밍**: 구매, 요리, 판매 달력에 따른 판매. 남길 수량은 직접 정합니다.
- **주간 일괄 실행**: 아케이드 메뉴, 마이홈 인기도, 장비 제작, 종말의 서.
- **분신 데스크톱**: 게임이 보이지 않는 다른 데스크톱에서 실행되어 마우스와 키보드를 그대로 쓸 수 있습니다.
- **마물 추적자**: F8로 내 전투를 한 번 녹화하면, 이후 매 턴의 순서·배치·스킬을 녹화한 대로 맞춘 뒤 싸웁니다.
- **오늘 리포트**: 오늘 무엇을 실행했는지, 무엇이 왜 실패했는지 한눈에.

## 특징

- **확실하지 않으면 누르지 않음**: 화면을 확실히 인식했을 때만 클릭합니다. 막히면 홈으로 돌아가거나 멈춥니다.
- **과금 없음**: 유료 스태미나, 다이아, 유료 아이템은 절대 건드리지 않습니다. 무료 횟수를 다 쓰면 멈춥니다.
- **지켜볼 필요 없음**: 끝나면 Windows 알림으로 알려 줍니다.
- **자동 업데이트**: 실행할 때마다 새 버전을 확인하므로 다시 받을 필요가 없습니다.
- **1080p·2K·4K**: 16:9라면 모두 사용할 수 있습니다.

## 3단계로 시작

1. [Releases](https://github.com/nobell001/YES-BD2/releases/latest)에서 **`yes-bd2-win32-online-setup.exe`**(약 5 MB)를 받아 설치합니다. 설치 중에 나머지를 내려받으므로 인터넷에 연결해 두세요. "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누르세요(설치 파일에 코드 서명이 없어 새 버전에서는 이 경고가 나옵니다).
2. 게임 언어를 **중국어 간체**로, 그래픽을 FHD로 설정합니다.
3. 도구를 열고 **일일 일괄 실행**을 누릅니다. 게임이 꺼져 있으면 켤지 먼저 물어봅니다.

> 실행 중에도 PC를 쓰고 싶다면 **분신 데스크톱에서 실행**을 누르세요(Windows Pro 필요, 처음 한 번 설정).

## 다른 화면

<table>
  <tr>
    <td><img src="docs/images/daily.jpg" alt="일일 설정"></td>
    <td><img src="docs/images/trade.jpg" alt="교역 파밍"></td>
    <td><img src="docs/images/maps.jpg" alt="파밍"></td>
  </tr>
  <tr>
    <td align="center">일일 설정: 실행할 항목을 체크</td>
    <td align="center">교역 파밍: 사고, 만들고, 팔기</td>
    <td align="center">파밍: 한 주 진행 상황을 한눈에</td>
  </tr>
</table>

<p align="center"><img src="docs/images/fiend.jpg" alt="마물 추적자" width="760"><br><sub>마물 추적자: 매 턴의 순서·배치·스킬을 내가 녹화한 대로</sub></p>

<sub>스크린샷은 중국어 간체 화면입니다.</sub>

## 실행 전 주의

- 화면 잠금, 화면 끄기, 절전 모드를 쓰지 말고 게임 창도 최소화하지 마세요.
- GPU 필터, 샤프닝, FPS 표시, 녹화 오버레이 등 화면 위에 겹치는 것은 끄세요.
- 일반 모드는 마우스를 사용하므로 실행 중에는 PC를 조작하지 마세요. 함께 쓰려면 분신 데스크톱을 사용하세요.
- 실행할 때마다 관리자 권한을 요청합니다(Windows가 한 번 묻습니다). "예"를 누르세요.

## 문제가 생기면

| 상황 | 해결 방법 |
|---|---|
| 게임을 찾지 못함 | 먼저 게임을 켜세요. 기본 위치가 아닌 곳에 설치했다면 아래 "소스로 실행"의 경로 설정을 참고하세요 |
| 화면을 인식하지 못함 | 게임 언어가 중국어 간체인지, 16:9인지, 게임을 가리는 것이 없는지 확인하세요 |
| 특정 항목이 계속 실패함 | 오늘 리포트에서 실패 원인과 스크린샷을 확인하고 [Issues](https://github.com/nobell001/YES-BD2/issues)에 알려 주세요 |

오늘 리포트의 스크린샷이 가장 도움이 됩니다. 게임 계정 정보가 보일 수 있으니 올리기 전에 확인하세요.

## 어떤 파일을 받나요

| 파일 | 설명 |
|---|---|
| `yes-bd2-win32-online-setup.exe` | **이 파일을 고르세요**. 약 5 MB, 나머지는 설치 중에 내려받으며 보통 더 빠름 |
| `yes-bd2-win32-Full-setup.exe` | 오프라인용 전체 설치 파일, 용량이 큼. 설치 중에 인터넷을 쓸 수 없을 때만 |

GitHub가 자동으로 붙이는 `Source code` 압축 파일과 `yes-bd2-win32.zip`은 설치 파일이 아니므로 받지 않아도 됩니다.

<details>
<summary><b>소스로 실행(개발자용)</b></summary>

소스로 실행하면 **자동 업데이트되지 않습니다**. `git pull`로 직접 업데이트하세요.

```powershell
git clone https://github.com/nobell001/YES-BD2.git
cd YES-BD2
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\start.bat
```

게임이 기본 위치에 없으면 실행 전에 다음을 설정합니다.

```powershell
$env:OK_BD2_LAUNCHER_PATH = "C:\Path\To\Browndust2Starter.exe"
$env:OK_BD2_GAME_PATH = "D:\Path\To\BrownDust II.exe"
```

의존성은 `pyproject.toml`과 `uv.lock`이 기준이며, `requirements*.txt`는 uv로 내보낸 파일이니 직접 수정하지 마세요.

```powershell
.\scripts\run_checks.ps1 -Mode Focused -Tests tests.test_pvp_task   # 영향받는 테스트만
.\scripts\run_checks.ps1 -Mode Final                                # 커밋 전 전체 검사
```

자세한 내용(중국어): [아키텍처](docs/architecture.md) · [릴리스 체크리스트](docs/release-checklist.md) · [PyAppify 릴리스 과정](docs/pyappify-release-flow.md)

</details>

## 감사의 말

YES-BD2는 [GodRaymond233/ok-bd2](https://github.com/GodRaymond233/ok-bd2)를 바탕으로 만들었고, 프레임워크와 원클릭 업데이트는 [ok-script](https://github.com/ok-oldking/ok-script)에서 왔습니다. 다음 분들께도 감사드립니다.

- [BD2DB](https://browndust2-db.souseha.com/): 게임 내 명칭과 데이터
- bilibili의 [時樂淵](https://space.bilibili.com/14949646)님: 교역 파밍 판매표
- [BetterGI](https://github.com/babalae/better-genshin-impact), [ChildStream](https://github.com/mattxslv/childstream): 분신 데스크톱 방식과 화면 창
- [JZPPP/MaaBD2](https://github.com/JZPPP/MaaBD2): 맵 채집 경로 참고

도구의 "정보" 페이지에 모든 감사의 말이 있습니다. 서드파티 의존성과 소재는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 참고하세요.

## 라이선스

코드는 [GPL-3.0](LICENSE)(ok-bd2와 동일)으로 공개합니다. 게임 이름, 스크린샷, 아이콘, UI 소재의 권리는 각 권리자에게 있습니다.
