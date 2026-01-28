/**
 * recorder_worker.js - 오디오 리샘플링 및 PCM 변환 워커
 *
 * Web Worker를 사용하여 오디오 리샘플링과 PCM 변환을 백그라운드에서 수행합니다.
 * MediaRecorder 모드에서 사용됩니다.
 *
 * 주요 기능:
 *   - 리샘플링: 브라우저 샘플레이트 (48kHz) → Whisper 샘플레이트 (16kHz)
 *   - PCM 변환: Float32Array → Int16 PCM (s16le)
 *   - 백그라운드 처리: 메인 스레드를 블록하지 않음
 *
 * 메시지 프로토콜:
 *   - 'init': 샘플레이트 설정 (브라우저, 목표)
 *   - 'record': 오디오 버퍼 처리 및 PCM 반환
 */

// 샘플레이트 설정
let sampleRate = 48000;        // 브라우저 오디오 컨텍스트 샘플레이트
let targetSampleRate = 16000;  // Whisper 목표 샘플레이트

/**
 * 메시지 핸들러 (메인 스레드로부터)
 *
 * @param {MessageEvent} e - 메시지 이벤트
 *   - command: 'init' | 'record'
 *   - config: { sampleRate, targetSampleRate }
 *   - buffer: Float32Array (오디오 데이터)
 */
self.onmessage = function (e) {
  switch (e.data.command) {
    case 'init':
      // 샘플레이트 초기화
      init(e.data.config);
      break;
    case 'record':
      // 오디오 버퍼 처리
      record(e.data.buffer);
      break;
  }
};

/**
 * 워커 초기화
 *
 * @param {Object} config - 설정
 *   - sampleRate: 브라우저 샘플레이트 (Hz)
 *   - targetSampleRate: 목표 샘플레이트 (Hz, 기본값 16000)
 */
function init(config) {
  sampleRate = config.sampleRate;
  targetSampleRate = config.targetSampleRate || 16000;
}

/**
 * 오디오 버퍼 처리 (리샘플링 + PCM 변환)
 *
 * @param {ArrayBuffer} inputBuffer - Float32 오디오 버퍼
 *
 * 처리 흐름:
 *   1. ArrayBuffer → Float32Array 변환
 *   2. 리샘플링: sampleRate → targetSampleRate
 *   3. PCM 변환: Float32 → Int16
 *   4. 메인 스레드로 전송 (Transferable)
 */
function record(inputBuffer) {
  const buffer = new Float32Array(inputBuffer);
  const resampledBuffer = resample(buffer, sampleRate, targetSampleRate);
  const pcmBuffer = toPCM(resampledBuffer);
  self.postMessage({ buffer: pcmBuffer }, [pcmBuffer]);
}

/**
 * 오디오 리샘플링 (선형 보간)
 *
 * @param {Float32Array} buffer - 입력 오디오 버퍼
 * @param {number} from - 원본 샘플레이트 (Hz)
 * @param {number} to - 목표 샘플레이트 (Hz)
 * @returns {Float32Array} 리샘플링된 버퍼
 *
 * 알고리즘:
 *   - 샘플레이트 비율 계산: ratio = from / to
 *   - 새 길이: newLength = buffer.length / ratio
 *   - 각 출력 샘플마다 입력 샘플들의 평균 계산
 *
 * 예:
 *   - 48000 → 16000: ratio = 3, 3개 샘플의 평균
 *   - 16000 → 16000: ratio = 1, 그대로 반환
 */
function resample(buffer, from, to) {
    // 같은 샘플레이트면 그대로 반환
    if (from === to) {
        return buffer;
    }

    // 샘플레이트 비율 계산
    const ratio = from / to;
    const newLength = Math.round(buffer.length / ratio);
    const result = new Float32Array(newLength);

    let offsetResult = 0;    // 출력 버퍼 오프셋
    let offsetBuffer = 0;    // 입력 버퍼 오프셋

    // 각 출력 샘플 생성
    while (offsetResult < result.length) {
        // 다음 출력 샘플의 입력 범위 계산
        const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
        let accum = 0, count = 0;

        // 입력 샘플들의 평균 계산
        for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
            accum += buffer[i];
            count++;
        }

        // 평균값을 출력 버퍼에 저장
        result[offsetResult] = accum / count;
        offsetResult++;
        offsetBuffer = nextOffsetBuffer;
    }

    return result;
}

/**
 * Float32 오디오를 PCM Int16으로 변환
 *
 * @param {Float32Array} input - Float32 오디오 (-1.0 ~ 1.0)
 * @returns {ArrayBuffer} PCM s16le 버퍼
 *
 * 변환:
 *   - Float32 범위: -1.0 ~ 1.0
 *   - Int16 범위: -32768 ~ 32767
 *   - 음수: value * 0x8000 (32768)
 *   - 양수: value * 0x7FFF (32767)
 *
 * 포맷: PCM s16le (signed 16-bit little-endian)
 */
function toPCM(input) {
  const buffer = new ArrayBuffer(input.length * 2);  // Int16 = 2 bytes
  const view = new DataView(buffer);

  for (let i = 0; i < input.length; i++) {
    // 범위 클램핑: -1.0 ~ 1.0
    const s = Math.max(-1, Math.min(1, input[i]));

    // Float32 → Int16 변환
    // 음수: -1.0 → -32768, 양수: 1.0 → 32767
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }

  return buffer;
}
