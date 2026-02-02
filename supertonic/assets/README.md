## ONNX 모델 파일 안내

본 저장소에는 용량 문제로 인해 ONNX 모델 파일이 포함되어 있지 않습니다.  
아래 링크에서 `onnx` 폴더를 다운로드한 후, 지정된 위치에 직접 넣어주셔야 합니다.

다운로드 링크:  
https://drive.google.com/drive/folders/1qKo_iTToYkyagZxDpiGw6sXt5Hzn5OEA?usp=sharing

### 사용 방법

1. 위 링크에 접속하여 `onnx` 폴더를 다운로드합니다.
2. 다운로드한 `onnx` 폴더를 다음 경로에 복사합니다.

TTS/supertonic/assets/onnx


최종적으로 폴더 구조는 아래와 같아야 합니다.

TTS/
└─ supertonic/
└─ assets/
└─ onnx/
├─ tts.json
├─ unicode_indexer.json
├─ duration_predictor.onnx
├─ text_encoder.onnx
├─ vector_estimator.onnx
└─ vocoder.onnx


해당 파일들이 올바르게 배치되면,  
`run_tts.py`를 정상적으로 실행할 수 있습니다.
