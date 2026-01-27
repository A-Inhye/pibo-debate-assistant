/**
 * pcm_worklet.js - AudioWorklet PCM 데이터 포워더
 *
 * AudioWorkletProcessor를 사용하여 마이크 입력을 실시간으로 캡처하고
 * 메인 스레드로 전달합니다. PCM 입력 모드에서 사용됩니다.
 *
 * 동작:
 *   - 오디오 렌더링 스레드에서 실행 (낮은 지연시간)
 *   - 128 샘플 블록 단위로 처리
 *   - Float32Array PCM 데이터를 메인 스레드로 postMessage
 *
 * 장점:
 *   - MediaRecorder보다 낮은 지연시간
 *   - 압축 없음 (PCM 직접 전송)
 *   - 오디오 렌더링 스레드에서 실행 (우선순위 높음)
 *
 * 단점:
 *   - 대역폭 소비 높음 (압축 없음)
 *   - 브라우저 지원 제한적 (Chrome, Edge만)
 */

class PCMForwarder extends AudioWorkletProcessor {
  /**
   * 오디오 처리 콜백 (128 샘플마다 호출)
   *
   * @param {Float32Array[][]} inputs - 입력 오디오 버퍼
   *   - inputs[0]: 첫 번째 입력 소스 (마이크)
   *   - inputs[0][0]: 모노 채널 (왼쪽)
   *   - inputs[0][1]: 스테레오 채널 (오른쪽, 선택)
   * @returns {boolean} true를 반환하여 프로세서 유지
   */
  process(inputs) {
    const input = inputs[0];
    if (input && input[0] && input[0].length) {
      // 모노 채널(0)을 전달. 멀티채널이면 다운믹싱 추가 가능
      const channelData = input[0];

      // Float32Array 복사 (Transferable로 전송하기 위해)
      const copy = new Float32Array(channelData.length);
      copy.set(channelData);

      // 메인 스레드로 전송 (버퍼 소유권 이전)
      this.port.postMessage(copy, [copy.buffer]);
    }

    // 프로세서를 계속 살려둠 (false 반환 시 종료)
    return true;
  }
}

// AudioWorklet 프로세서 등록
registerProcessor('pcm-forwarder', PCMForwarder);
