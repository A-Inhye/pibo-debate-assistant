# api.py
import os
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, Response
from scipy.io import wavfile
import io
import json
from tts_engine import TTSEngine

app = FastAPI()

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

tts_engine = TTSEngine(
    onnx_dir=os.path.join(BASE_DIR, "assets", "onnx"),
    voice_style_path=os.path.join(BASE_DIR, "assets", "voice_styles", "M1.json")
)


@app.post("/tts")
def tts(text: str):
    """
    전체 텍스트를 한번에 처리해서 wav 파일 반환
    """
    print(f"📝 TTS 요청: {text[:50]}...")
    
    # 전체 음성 생성
    import tempfile
    temp_file = os.path.join(tempfile.gettempdir(), "tts_output.wav")
    tts_engine.synthesize(text, temp_file)
    
    # 파일 읽어서 반환
    with open(temp_file, "rb") as f:
        audio_data = f.read()
    
    os.remove(temp_file)
    
    return Response(
        content=audio_data,
        media_type="audio/wav",
        headers={"Content-Disposition": "attachment; filename=output.wav"}
    )

@app.post("/tts-stream")
def tts_stream(text: str):
    """
    문장 단위로 스트리밍 생성 및 전송
    """
    print(f"📝 TTS 스트리밍 요청: {text[:50]}...")
    
    def generate():
        for wav, idx in tts_engine.synthesize_streaming(text):
            print(f"   📤 [{idx}] 청크 전송 중...")
            
            # wav를 bytes로 변환
            buffer = io.BytesIO()
            wavfile.write(buffer, tts_engine.sample_rate, wav)
            buffer.seek(0)
            chunk_data = buffer.read()
            
            # 청크 크기와 데이터를 함께 전송
            chunk_size = len(chunk_data)
            yield chunk_size.to_bytes(4, byteorder='big')  # 4바이트 크기 정보
            yield chunk_data  # 실제 오디오 데이터
    
    return StreamingResponse(
        generate(),
        media_type="application/octet-stream"
    )


if __name__ == "__main__":
    import uvicorn
    print(f"[TTS API Server] 시작: http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)