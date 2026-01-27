# 파이보 프로젝트 - LocalAgreement 백엔드 버전

**텐서 크기 오류 해결을 위한 안정적 버전**

## 🆚 SimulStreaming vs LocalAgreement

### SimulStreaming (기본)
- **특징**: 낮은 지연시간, 실시간 스트리밍 최적화
- **장점**: 빠른 응답속도
- **단점**: 특정 모델/언어 조합에서 텐서 크기 오류 발생 가능
- **위치**: `/whisperlivekit/web_pibo/`

### LocalAgreement (이 버전)
- **특징**: 안정적인 전사, 가설 버퍼 사용
- **장점**:
  - ✅ 텐서 크기 오류 없음
  - ✅ 더 안정적인 전사 품질
  - ✅ medium/large 모델과 잘 작동
- **단점**: SimulStreaming보다 약간 느림 (무시할 수준)
- **위치**: `/whisperlivekit/web_pibo_localagreement/`

---

## 🚀 실행 방법

```bash
cd /mnt/c/Users/SEC/WhisperLiveKit-main

# LocalAgreement 백엔드로 실행
python -m whisperlivekit.basic_server_pibo_localagreement \
    --model medium \
    --language ko \
    --diarization \
    --device cuda
```

### 실행 옵션

```bash
# 기본 실행 (medium 모델, 한국어, 화자 분리)
python -m whisperlivekit.basic_server_pibo_localagreement \
    --model medium \
    --lan ko \
    --diarization

# large-v3 모델 (RTX 4090)
python -m whisperlivekit.basic_server_pibo_localagreement \
    --model large-v3 \
    --lan ko \
    --diarization \
    --device cuda

# 포트 변경
python -m whisperlivekit.basic_server_pibo_localagreement \
    --model medium \
    --lan ko \
    --diarization \
    --port 8001
```

브라우저에서 `http://localhost:8000` 접속

---

## ⚙️ 백엔드 정책 강제 설정

`basic_server_pibo_localagreement.py` 파일에서 자동으로 LocalAgreement를 사용하도록 설정되어 있습니다:

```python
# CLI 인자 파싱
args = parse_args()

# LocalAgreement 백엔드 강제 설정 (텐서 크기 오류 해결)
args.backend_policy = "localagreement"
logger.info(f"백엔드 정책: {args.backend_policy} (LocalAgreement - 안정적 버전)")
```

따라서 `--backend-policy` 옵션을 지정할 필요가 없습니다!

---

## 🐛 텐서 크기 오류 해결

### 에러 메시지

```
RuntimeError: The size of tensor a (4) must match the size of tensor b (2) at non-singleton dimension 1
```

### 원인

SimulStreaming 백엔드의 AlignAtt 정책에서 발생하는 내부 버그입니다.

### 해결책

LocalAgreement 백엔드를 사용하면 이 오류가 발생하지 않습니다!

```bash
# 이 서버를 사용하면 자동으로 LocalAgreement 사용
python -m whisperlivekit.basic_server_pibo_localagreement --model medium --lan ko --diarization
```

---

## 📁 파일 구조

```
whisperlivekit/
├── web_pibo/                              # SimulStreaming 버전 (기본)
│   ├── live_transcription.html
│   ├── live_transcription.css
│   ├── live_transcription.js
│   ├── web_interface.py
│   └── README_PIBO.md
│
├── web_pibo_localagreement/               # LocalAgreement 버전 (이 폴더)
│   ├── live_transcription.html            # (web_pibo와 동일)
│   ├── live_transcription.css             # (web_pibo와 동일)
│   ├── live_transcription.js              # (web_pibo와 동일)
│   ├── web_interface.py                   # (경로만 수정)
│   └── README_LOCALAGREEMENT.md           # (이 파일)
│
├── basic_server_pibo.py                   # SimulStreaming 서버
└── basic_server_pibo_localagreement.py    # LocalAgreement 서버 ⭐
```

---

## 🔄 버전 간 전환

### SimulStreaming으로 돌아가고 싶을 때

```bash
python -m whisperlivekit.basic_server_pibo \
    --model medium \
    --lan ko \
    --diarization
```

### LocalAgreement 사용 (안정적)

```bash
python -m whisperlivekit.basic_server_pibo_localagreement \
    --model medium \
    --lan ko \
    --diarization
```

---

## 💡 성능 비교

| 백엔드 | 지연시간 | 안정성 | GPU 메모리 | 전사 품질 |
|--------|---------|--------|-----------|----------|
| SimulStreaming | 매우 낮음 | 중간 | 중간 | 좋음 |
| LocalAgreement | 낮음 | **높음** | 중간 | **매우 좋음** |

**권장**: RTX 4090으로 `medium` 또는 `large-v3` 모델을 사용할 때는 **LocalAgreement**를 추천합니다.

---

## 📝 수정 사항 요약

1. **새 폴더 생성**: `web_pibo_localagreement/`
2. **새 서버 파일**: `basic_server_pibo_localagreement.py`
3. **백엔드 강제 설정**: `args.backend_policy = "localagreement"`
4. **Import 경로 수정**: `web_pibo` → `web_pibo_localagreement`
5. **UI는 동일**: 좌우 2분할 레이아웃 그대로 유지

---

## 🎯 다음 단계

1. **현재 단계 (완료)**
   - ✅ STT + 화자 분리 + 2분할 웹 UI
   - ✅ LocalAgreement 백엔드로 안정성 확보

2. **다음 단계 (LLM 연동)**
   - [ ] 화자별 논지 요약 API 추가
   - [ ] OpenAI/Claude API 연동
   - [ ] 자동 요약 기능

---

**버전**: LocalAgreement 1.0.0
**최종 수정일**: 2026-01-27
**기반 프로젝트**: WhisperLiveKit + 파이보 프로젝트
**백엔드**: LocalAgreement (안정적 버전)
