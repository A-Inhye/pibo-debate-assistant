#!/usr/bin/env python3
"""
WebSocket 테스트 클라이언트
오디오 파일을 서버로 전송하고 STT 결과를 확인합니다.
"""

import asyncio
import json
import wave
import sys
import struct

import websockets


async def test_stt(audio_path: str, server_url: str = "ws://localhost:8000/asr"):
    """오디오 파일을 WebSocket으로 전송하고 결과를 출력합니다."""

    # WAV 파일 읽기
    with wave.open(audio_path, 'rb') as wav_file:
        sample_rate = wav_file.getframerate()
        n_channels = wav_file.getnchannels()
        n_frames = wav_file.getnframes()
        sample_width = wav_file.getsampwidth()
        audio_data = wav_file.readframes(n_frames)

    print(f"오디오 파일: {audio_path}")
    print(f"샘플레이트: {sample_rate}Hz, 채널: {n_channels}, 프레임: {n_frames}")
    print(f"샘플 너비: {sample_width} bytes")
    print(f"길이: {n_frames / sample_rate:.2f}초")
    print("-" * 50)

    try:
        async with websockets.connect(server_url) as ws:
            print(f"서버 연결됨: {server_url}")

            # 설정 메시지 수신
            config_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            config = json.loads(config_msg)
            print(f"서버 설정: {config}")
            use_pcm = config.get("useAudioWorklet", False)
            print(f"PCM 모드: {use_pcm}")
            print("-" * 50)

            # PCM 모드: raw s16le 데이터 전송
            # 오디오를 청크로 나누어 전송 (100ms 단위)
            chunk_duration = 0.1  # 100ms
            chunk_samples = int(sample_rate * chunk_duration)
            chunk_size = chunk_samples * sample_width  # bytes per chunk

            total_chunks = (len(audio_data) + chunk_size - 1) // chunk_size

            print(f"오디오 전송 중... ({total_chunks} 청크, 각 {chunk_duration*1000:.0f}ms)")

            results = []
            transcriptions = []

            async def receive_results():
                """결과 수신 태스크"""
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                        data = json.loads(msg)
                        results.append(data)

                        if data.get("type") == "ready_to_stop":
                            print("\n[서버] 처리 완료")
                            break

                        # 전사 결과 출력
                        if "lines" in data and data["lines"]:
                            for line in data["lines"]:
                                speaker = line.get("speaker", "?")
                                text = line.get("text", "")
                                if text.strip():
                                    transcriptions.append((speaker, text))
                                    print(f"  [화자 {speaker}] {text}")

                        if data.get("buffer_transcription"):
                            buf = data["buffer_transcription"]
                            if buf.strip():
                                print(f"  [버퍼] {buf}", end="\r")

                except asyncio.TimeoutError:
                    print("\n[타임아웃] 더 이상 결과가 없습니다.")
                except websockets.exceptions.ConnectionClosed:
                    print("\n[연결 종료]")

            # 결과 수신 태스크 시작
            receive_task = asyncio.create_task(receive_results())

            # 오디오 청크 전송
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]
                await ws.send(chunk)
                await asyncio.sleep(chunk_duration)  # 실시간 시뮬레이션

            print("\n오디오 전송 완료. 결과 대기 중...")

            # 잠시 대기 후 연결 종료
            await asyncio.sleep(3)

            # 결과 수신 대기 (최대 10초)
            try:
                await asyncio.wait_for(receive_task, timeout=10.0)
            except asyncio.TimeoutError:
                print("결과 수신 타임아웃")
                receive_task.cancel()

            print("\n" + "=" * 50)
            print("테스트 완료!")
            print(f"총 {len(results)}개의 메시지 수신")

            # 최종 결과 출력
            if transcriptions:
                print("\n[최종 전사 결과]")
                seen = set()
                for speaker, text in transcriptions:
                    key = (speaker, text.strip())
                    if key not in seen:
                        seen.add(key)
                        print(f"  화자 {speaker}: {text}")
            else:
                print("\n전사 결과가 없습니다.")

    except ConnectionRefusedError:
        print("오류: 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.")
    except Exception as e:
        print(f"오류: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    audio_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/test_audio.wav"
    asyncio.run(test_stt(audio_file))
