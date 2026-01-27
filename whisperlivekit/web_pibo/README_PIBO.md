# 파이보 프로젝트 - WhisperLiveKit 웹 UI

파이보 로봇 기반 실시간 토론 지원 시스템을 위한 수정된 웹 인터페이스입니다.

## 📋 주요 변경사항

### 1. 좌우 2분할 레이아웃

기존 WhisperLiveKit의 단일 패널을 좌우 2개 패널로 분할했습니다:

- **왼쪽 패널**: 실시간 대화 기록
  - 시간 정보 (HH:MM:SS)
  - 화자 정보 (SPEAKER_00, SPEAKER_01, ...)
  - 발언 내용
  - 실시간 스트리밍

- **오른쪽 패널**: 화자별 논지 요약
  - 화자별 발언 수 통계
  - 최근 3개 발언 표시
  - 새로고침 버튼 (🔄)
  - 나중에 LLM API 연동하여 실제 논지 요약 생성 가능

### 2. 기존 기능 유지

WhisperLiveKit의 모든 핵심 기능이 그대로 유지됩니다:

- ✅ 실시간 STT (Speech-to-Text)
- ✅ 화자 분리 (Speaker Diarization)
- ✅ MediaRecorder 모드
- ✅ AudioWorklet 모드 (--pcm-input)
- ✅ 마이크 선택
- ✅ WebSocket 연결
- ✅ 다크/라이트 모드
- ✅ 반응형 디자인

## 🚀 실행 방법

### 1. Python 모듈로 실행 (권장)

```bash
# 기본 실행 (한국어, 화자 분리 활성화)
python -m whisperlivekit.basic_server --model base --language ko --enable-diarization

# web_pibo 패키지 사용하려면 basic_server.py 수정 필요 (아래 참조)
```

### 2. basic_server.py 수정

`basic_server.py` 파일을 열어서 web 패키지를 web_pibo로 변경:

```python
# 기존 코드 (9-10줄):
from whisperlivekit.web.web_interface import get_inline_ui_html

# 변경 후:
from whisperlivekit.web_pibo.web_interface import get_inline_ui_html
```

또는 새로운 서버 파일 생성:

```python
# basic_server_pibo.py
import sys
sys.path.insert(0, '/mnt/c/Users/SEC/WhisperLiveKit-main')

from whisperlivekit.basic_server import *
from whisperlivekit.web_pibo.web_interface import get_inline_ui_html

# 기존 get() 엔드포인트 오버라이드
@app.get("/")
async def get():
    return HTMLResponse(get_inline_ui_html())

if __name__ == '__main__':
    main()
```

### 3. 직접 웹 서버 실행 (테스트용)

```bash
cd /mnt/c/Users/SEC/WhisperLiveKit-main/whisperlivekit/web_pibo
python web_interface.py
```

브라우저에서 `http://localhost:8000` 접속

## 📁 파일 구조

```
whisperlivekit/web_pibo/
├── __init__.py                  # 패키지 초기화
├── web_interface.py             # HTML 생성 (인라인 임베딩)
├── live_transcription.html      # 메인 HTML (2분할 레이아웃)
├── live_transcription.css       # 스타일시트 (2분할 스타일)
├── live_transcription.js        # JavaScript (화자별 요약 기능 추가)
├── pcm_worklet.js              # AudioWorklet (PCM 모드)
├── recorder_worker.js          # Web Worker (MediaRecorder 모드)
├── src/
│   ├── system_mode.svg         # 시스템 테마 아이콘
│   ├── light_mode.svg          # 라이트 모드 아이콘
│   ├── dark_mode.svg           # 다크 모드 아이콘
│   └── settings.svg            # 설정 아이콘
└── README_PIBO.md              # 이 파일
```

## 🎯 파이보 프로젝트 로드맵

### 현재 단계 (완료)

- ✅ STT 실시간 구현 (WhisperLiveKit 활용)
- ✅ 화자 분리 (Speaker Diarization)
- ✅ 웹 UI 2분할 레이아웃
- ✅ 실시간 대화 기록 표시
- ✅ 화자별 발언 그룹화

### 다음 단계 (계획)

#### 2주차: 실시간 문서화
- [ ] 메모리 버퍼에 대화 저장
- [ ] 일정 크기 도달 시 Vector DB로 이관
- [ ] 새 버퍼 시작

#### 3주차: Vector DB 연동
- [ ] Chroma/FAISS 선택
- [ ] 청크 단위 분할 저장
- [ ] 검색 기능 구현

#### 4주차: 화자별 요약 (LLM 연동)
- [ ] LLM API 연동 (OpenAI/Anthropic/Local)
- [ ] 프롬프트 설계:
  ```
  다음은 화자 A의 발언들입니다. 핵심 논지를 3개 이내로 요약해주세요:
  - 발언1
  - 발언2
  - ...
  ```
- [ ] 주기적 자동 요약 (30초마다)
- [ ] 사용자 요청 시 즉시 요약

#### 5주차: AI 중재 기능
- [ ] 백그라운드 루프 (10-30초 주기)
- [ ] 중재 필요 판단 로직
- [ ] TTS 음성 출력

#### 6주차: 웹앱 완성
- [ ] UI/UX 개선
- [ ] 반응형 디자인 최적화
- [ ] 에러 핸들링

#### 7주차+: 통합 및 테스트
- [ ] 파이보 로봇 탑재
- [ ] 실제 토론 환경 테스트
- [ ] 성능 최적화

## 💡 LLM API 연동 가이드

오른쪽 패널의 화자별 요약을 실제 LLM으로 생성하려면:

### 1. JavaScript에 API 호출 추가

```javascript
// live_transcription.js에 추가

async function generateSummaryWithLLM(speaker, messages) {
  const response = await fetch('/api/summarize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ speaker, messages })
  });

  const data = await response.json();
  return data.summary;  // ["주장1", "주장2", "주장3"]
}

// updateSpeakerSummary() 함수 수정
async function updateSpeakerSummary() {
  // ... (기존 코드)

  for (const [speaker, messages] of Object.entries(speakerMessages)) {
    // LLM으로 요약 생성
    const summary = await generateSummaryWithLLM(speaker, messages);

    summaryHTML += `
      <div class="speaker-summary-item">
        <h3>${speakerName}</h3>
        <ul>
          ${summary.map(point => `<li>${point}</li>`).join('')}
        </ul>
      </div>
    `;
  }
}
```

### 2. FastAPI 엔드포인트 추가

```python
# basic_server.py에 추가

from openai import AsyncOpenAI  # 또는 다른 LLM 클라이언트

client = AsyncOpenAI(api_key="your-api-key")

@app.post("/api/summarize")
async def summarize_speaker(data: dict):
    speaker = data["speaker"]
    messages = data["messages"]

    # 프롬프트 생성
    prompt = f"""
    다음은 {speaker}의 발언들입니다. 핵심 논지를 3개 이내로 요약해주세요.
    각 논지는 한 문장으로 작성하고, JSON 배열 형태로 반환해주세요.

    발언 목록:
    {chr(10).join(f"- {msg}" for msg in messages)}

    응답 형식: ["논지1", "논지2", "논지3"]
    """

    # LLM API 호출
    response = await client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )

    summary = json.loads(response.choices[0].message.content)
    return {"summary": summary}
```

## 🔧 디자인 수정 방법

### HTML 수정

```bash
nano /mnt/c/Users/SEC/WhisperLiveKit-main/whisperlivekit/web_pibo/live_transcription.html
```

### CSS 수정

```bash
nano /mnt/c/Users/SEC/WhisperLiveKit-main/whisperlivekit/web_pibo/live_transcription.css
```

### JavaScript 수정

```bash
nano /mnt/c/Users/SEC/WhisperLiveKit-main/whisperlivekit/web_pibo/live_transcription.js
```

수정 후 서버 재시작:

```bash
python -m whisperlivekit.basic_server --model base --language ko --enable-diarization
```

브라우저 새로고침 (Ctrl+F5)

## 📊 화면 구성 예시

```
┌─────────────────────────────────────────────────────────────────┐
│  [●] 녹음 버튼    [⚙️] 설정                                        │
├──────────────────────────────┬──────────────────────────────────┤
│  실시간 대화 기록                │  화자별 논지 요약                   │
├──────────────────────────────┼──────────────────────────────────┤
│                              │                                  │
│  10:01 화자 0                 │  ▶ 화자 0 (총 5개 발언)            │
│  저는 이렇게 생각합니다...       │  • 주장 1: ...                    │
│                              │  • 주장 2: ...                    │
│  10:02 화자 1                 │  • 주장 3: ...                    │
│  그건 좀 다른 관점에서...       │                                  │
│                              │  ▶ 화자 1 (총 4개 발언)            │
│  10:03 화자 0                 │  • 주장 1: ...                    │
│  네, 하지만 제 의견은...        │  • 반론: ...                      │
│                              │                                  │
│  [실시간 업데이트 중...]        │  [자동 요약 업데이트 중...] 🔄     │
│                              │                                  │
└──────────────────────────────┴──────────────────────────────────┘
```

## 🎨 커스터마이징

### 색상 테마 수정

`live_transcription.css`에서 CSS 변수 수정:

```css
:root {
  --bg: #ffffff;              /* 배경색 */
  --text: #111111;            /* 텍스트 색 */
  --border: #e5e5e5;          /* 테두리 색 */
  --panel-bg: #fafafa;        /* 패널 배경색 */
  --panel-border: #d0d0d0;    /* 패널 테두리 */
}
```

### 패널 비율 조정

`live_transcription.css`의 `.left-panel`, `.right-panel` 수정:

```css
.left-panel {
  flex: 2;  /* 왼쪽이 오른쪽보다 2배 넓음 */
}

.right-panel {
  flex: 1;
}
```

### 요약 표시 개수 변경

`live_transcription.js`의 `updateSpeakerSummary()` 함수 수정:

```javascript
// 최근 3개 → 5개로 변경
const recentMessages = messages.slice(-5);
```

## 🐛 트러블슈팅

### 1. 오른쪽 패널이 비어있음

**원인**: 화자 정보가 WebSocket으로 전달되지 않음

**해결**:
- `--enable-diarization` 옵션 사용
- WebSocket 메시지에 `speaker` 필드 포함 확인

### 2. 레이아웃이 깨짐

**원인**: 브라우저 캐시

**해결**:
- 강력 새로고침 (Ctrl+Shift+R 또는 Ctrl+F5)
- 브라우저 개발자 도구에서 캐시 비우기

### 3. JavaScript 에러

**원인**: 기존 코드와 충돌

**해결**:
- 브라우저 콘솔 확인 (F12)
- `displayTranscript` 함수가 정의되어 있는지 확인

## 📝 참고 자료

- [WhisperLiveKit GitHub](https://github.com/yonigottesman/whisperlivekit)
- [파이보 프로젝트 정리 문서](../파이보_프로젝트_정리.pdf)
- [FastAPI 공식 문서](https://fastapi.tiangolo.com/)
- [WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)

## 📧 문의

파이보 프로젝트 관련 문의: [프로젝트 담당자]

---

**버전**: 1.0.0
**최종 수정일**: 2026-01-26
**기반 프로젝트**: WhisperLiveKit
**수정 목적**: 파이보 로봇 실시간 토론 지원 시스템
