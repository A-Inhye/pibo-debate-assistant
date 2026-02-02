/**
 * live_transcription.js - 실시간 음성 전사 웹 UI
 *
 * WhisperLiveKit의 프론트엔드 JavaScript 코드입니다.
 * WebSocket을 통해 서버와 통신하며 실시간 음성 전사를 수행합니다.
 *
 * 주요 기능:
 *   1. 오디오 캡처: MediaRecorder 또는 AudioWorklet
 *   2. WebSocket 통신: 오디오 전송 및 전사 결과 수신
 *   3. UI 업데이트: 전사 결과 표시, 타이머, 파형 시각화
 *   4. 테마 관리: 라이트/다크/시스템 모드
 *   5. 마이크 선택: 사용 가능한 오디오 입력 장치 목록
 *   6. 텍스트 읽기: Web Speech API를 사용한 TTS
 *
 * 아키텍처:
 *   - MediaRecorder 모드 (기본):
 *     마이크 → MediaRecorder → WebM/Opus → WebSocket → 서버
 *   - AudioWorklet 모드 (--pcm-input):
 *     마이크 → AudioWorklet → PCM Float32 → Worker → PCM Int16 → WebSocket → 서버
 *
 * 전역 상태:
 *   - isRecording: 녹음 중 여부
 *   - websocket: WebSocket 연결 객체
 *   - recorder: MediaRecorder 또는 null
 *   - audioContext: Web Audio API 컨텍스트
 *   - workletNode: AudioWorkletNode (PCM 모드)
 *   - recorderWorker: Web Worker (PCM 모드)
 *
 * 이벤트 흐름:
 *   1. 녹음 시작 버튼 클릭 → toggleRecording()
 *   2. startRecording() → WebSocket 연결 + 오디오 캡처 시작
 *   3. 오디오 데이터 → WebSocket 전송 (sendAudioData)
 *   4. WebSocket 메시지 수신 → updateTranscription()
 *   5. 녹음 중지 → stopRecording() → 리소스 정리
 */

// ============================================================================
// 환경 감지 및 전역 변수
// ============================================================================

// Chrome 확장 프로그램 감지
const isExtension = typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.getURL;
if (isExtension) {
  document.documentElement.classList.add('is-extension');
}
const isWebContext = !isExtension;

// 녹음 상태
let isRecording = false;           // 녹음 중 여부
let websocket = null;              // WebSocket 연결 객체
let recorder = null;               // MediaRecorder 인스턴스
let chunkDuration = 100;           // 오디오 청크 지속시간 (ms)
let websocketUrl = "ws://localhost:8000/asr";  // WebSocket URL
let userClosing = false;           // 사용자가 의도적으로 연결 종료했는지
let wakeLock = null;               // Screen Wake Lock (화면 꺼짐 방지)
let startTime = null;              // 녹음 시작 시간
let timerInterval = null;          // 타이머 인터벌 ID
let audioContext = null;           // Web Audio API 컨텍스트
let analyser = null;               // 오디오 분석기 (파형 시각화)
let microphone = null;             // 마이크 입력 스트림
let workletNode = null;            // AudioWorkletNode (PCM 모드)
let recorderWorker = null;         // Web Worker (PCM 리샘플링)
let waveCanvas = document.getElementById("waveCanvas");  // 파형 캔버스
let waveCtx = waveCanvas.getContext("2d");              // 캔버스 컨텍스트
let animationFrame = null;         // 애니메이션 프레임 ID
let waitingForStop = false;        // 서버의 ready_to_stop 대기 중
let lastReceivedData = null;       // 마지막 수신 데이터
let lastSignature = null;          // 마지막 데이터 시그니처 (중복 방지)
let availableMicrophones = [];     // 사용 가능한 마이크 목록
let selectedMicrophoneId = null;   // 선택된 마이크 ID
let serverUseAudioWorklet = null;  // 서버가 AudioWorklet 사용 여부
let configReadyResolve;            // 서버 설정 완료 Promise 리졸버
const configReady = new Promise((r) => (configReadyResolve = r));  // 설정 완료 Promise
let outputAudioContext = null;     // TTS 오디오 컨텍스트
let audioSource = null;            // TTS 오디오 소스

// 캔버스 해상도 설정 (고해상도 디스플레이 지원)
waveCanvas.width = 60 * (window.devicePixelRatio || 1);
waveCanvas.height = 30 * (window.devicePixelRatio || 1);
waveCtx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

// DOM 요소 참조
const statusText = document.getElementById("status");
const recordButton = document.getElementById("recordButton");
const chunkSelector = document.getElementById("chunkSelector");
const websocketInput = document.getElementById("websocketInput");
const websocketDefaultSpan = document.getElementById("wsDefaultUrl");
const linesTranscriptDiv = document.getElementById("linesTranscript");
const timerElement = document.querySelector(".timer");
const themeRadios = document.querySelectorAll('input[name="theme"]');
const microphoneSelect = document.getElementById("microphoneSelect");

const settingsToggle = document.getElementById("settingsToggle");
const settingsDiv = document.querySelector(".settings");

// ============================================================================
// SVG 아이콘 (인라인)
// ============================================================================

// Chrome 확장 프로그램용 주석 처리된 코드
// if (isExtension) {
//   chrome.runtime.onInstalled.addListener((details) => {
//     if (details.reason.search(/install/g) === -1) {
//       return;
//     }
//     chrome.tabs.create({
//       url: chrome.runtime.getURL("welcome.html"),
//       active: true
//     });
//   });
// }

// UI 아이콘 (SVG 인라인)
const translationIcon = `<svg xmlns="http://www.w3.org/2000/svg" height="12px" viewBox="0 -960 960 960" width="12px" fill="#5f6368"><path d="m603-202-34 97q-4 11-14 18t-22 7q-20 0-32.5-16.5T496-133l152-402q5-11 15-18t22-7h30q12 0 22 7t15 18l152 403q8 19-4 35.5T868-80q-13 0-22.5-7T831-106l-34-96H603ZM362-401 188-228q-11 11-27.5 11.5T132-228q-11-11-11-28t11-28l174-174q-35-35-63.5-80T190-640h84q20 39 40 68t48 58q33-33 68.5-92.5T484-720H80q-17 0-28.5-11.5T40-760q0-17 11.5-28.5T80-800h240v-40q0-17 11.5-28.5T360-880q17 0 28.5 11.5T400-840v40h240q17 0 28.5 11.5T680-760q0 17-11.5 28.5T640-720h-76q-21 72-63 148t-83 116l96 98-30 82-122-125Zm266 129h144l-72-204-72 204Z"/></svg>`
const silenceIcon = `<svg xmlns="http://www.w3.org/2000/svg" style="vertical-align: text-bottom;" height="14px" viewBox="0 -960 960 960" width="14px" fill="#5f6368"><path d="M514-556 320-752q9-3 19-5.5t21-2.5q66 0 113 47t47 113q0 11-1.5 22t-4.5 22ZM40-200v-32q0-33 17-62t47-44q51-26 115-44t141-18q26 0 49.5 2.5T456-392l-56-54q-9 3-19 4.5t-21 1.5q-66 0-113-47t-47-113q0-11 1.5-21t4.5-19L84-764q-11-11-11-28t11-28q12-12 28.5-12t27.5 12l675 685q11 11 11.5 27.5T816-80q-11 13-28 12.5T759-80L641-200h39q0 33-23.5 56.5T600-120H120q-33 0-56.5-23.5T40-200Zm80 0h480v-32q0-14-4.5-19.5T580-266q-36-18-92.5-36T360-320q-71 0-127.5 18T140-266q-9 5-14.5 14t-5.5 20v32Zm240 0Zm560-400q0 69-24.5 131.5T829-355q-12 14-30 15t-32-13q-13-13-12-31t12-33q30-38 46.5-85t16.5-98q0-51-16.5-97T767-781q-12-15-12.5-33t12.5-32q13-14 31.5-13.5T829-845q42 51 66.5 113.5T920-600Zm-182 0q0 32-10 61.5T700-484q-11 15-29.5 15.5T638-482q-13-13-13.5-31.5T633-549q6-11 9.5-24t3.5-27q0-14-3.5-27t-9.5-25q-9-17-8.5-35t13.5-31q14-14 32.5-13.5T700-716q18 25 28 54.5t10 61.5Z"/></svg>`;
const languageIcon = `<svg xmlns="http://www.w3.org/2000/svg" height="12" viewBox="0 -960 960 960" width="12" fill="#5f6368"><path d="M480-80q-82 0-155-31.5t-127.5-86Q143-252 111.5-325T80-480q0-83 31.5-155.5t86-127Q252-817 325-848.5T480-880q83 0 155.5 31.5t127 86q54.5 54.5 86 127T880-480q0 82-31.5 155t-86 127.5q-54.5 54.5-127 86T480-80Zm0-82q26-36 45-75t31-83H404q12 44 31 83t45 75Zm-104-16q-18-33-31.5-68.5T322-320H204q29 50 72.5 87t99.5 55Zm208 0q56-18 99.5-55t72.5-87H638q-9 38-22.5 73.5T584-178ZM170-400h136q-3-20-4.5-39.5T300-480q0-21 1.5-40.5T306-560H170q-5 20-7.5 39.5T160-480q0 21 2.5 40.5T170-400Zm216 0h188q3-20 4.5-39.5T580-480q0-21-1.5-40.5T574-560H386q-3 20-4.5 39.5T380-480q0 21 1.5 40.5T386-400Zm268 0h136q5-20 7.5-39.5T800-480q0-21-2.5-40.5T790-560H654q3 20 4.5 39.5T660-480q0 21-1.5 40.5T654-400Zm-16-240h118q-29-50-72.5-87T584-782q18 33 31.5 68.5T638-640Zm-234 0h152q-12-44-31-83t-45-75q-26 36-45 75t-31 83Zm-200 0h118q9-38 22.5-73.5T376-782q-56 18-99.5 55T204-640Z"/></svg>`
const speakerIcon = `<svg xmlns="http://www.w3.org/2000/svg" height="16px" style="vertical-align: text-bottom;" viewBox="0 -960 960 960" width="16px" fill="#5f6368"><path d="M480-480q-66 0-113-47t-47-113q0-66 47-113t113-47q66 0 113 47t47 113q0 66-47 113t-113 47ZM160-240v-32q0-34 17.5-62.5T224-378q62-31 126-46.5T480-440q66 0 130 15.5T736-378q29 15 46.5 43.5T800-272v32q0 33-23.5 56.5T720-160H240q-33 0-56.5-23.5T160-240Zm80 0h480v-32q0-11-5.5-20T700-306q-54-27-109-40.5T480-360q-56 0-111 13.5T260-306q-9 5-14.5 14t-5.5 20v32Zm240-320q33 0 56.5-23.5T560-640q0-33-23.5-56.5T480-720q-33 0-56.5 23.5T400-640q0 33 23.5 56.5T480-560Zm0-80Zm0 400Z"/></svg>`;

// ============================================================================
// 테마 및 UI 헬퍼 함수
// ============================================================================

/**
 * 파형 색상 가져오기 (CSS 변수)
 *
 * @returns {string} 파형 선 색상
 */
function getWaveStroke() {
  const styles = getComputedStyle(document.documentElement);
  const v = styles.getPropertyValue("--wave-stroke").trim();
  return v || "#000";
}

let waveStroke = getWaveStroke();

/**
 * 파형 색상 업데이트 (테마 변경 시)
 */
function updateWaveStroke() {
  waveStroke = getWaveStroke();
}

/**
 * 테마 적용
 *
 * @param {string} pref - 테마 설정 ("light" | "dark" | "system")
 */
function applyTheme(pref) {
  if (pref === "light") {
    document.documentElement.setAttribute("data-theme", "light");
  } else if (pref === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  updateWaveStroke();
}

// Persisted theme preference
const savedThemePref = localStorage.getItem("themePreference") || "system";
applyTheme(savedThemePref);
if (themeRadios.length) {
  themeRadios.forEach((r) => {
    r.checked = r.value === savedThemePref;
    r.addEventListener("change", () => {
      if (r.checked) {
        localStorage.setItem("themePreference", r.value);
        applyTheme(r.value);
      }
    });
  });
}

// React to OS theme changes when in "system" mode
const darkMq = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)");
const handleOsThemeChange = () => {
  const pref = localStorage.getItem("themePreference") || "system";
  if (pref === "system") updateWaveStroke();
};
if (darkMq && darkMq.addEventListener) {
  darkMq.addEventListener("change", handleOsThemeChange);
} else if (darkMq && darkMq.addListener) {
  // deprecated, but included for Safari compatibility
  darkMq.addListener(handleOsThemeChange);
}

/**
 * 마이크 목록 열거
 *
 * navigator.mediaDevices.enumerateDevices()를 사용하여
 * 사용 가능한 오디오 입력 장치를 가져옵니다.
 *
 * 동작:
 *   1. 임시로 마이크 권한 요청 (getUserMedia)
 *   2. 권한 획득 후 즉시 스트림 중지
 *   3. 장치 목록 가져오기
 *   4. audioinput 타입만 필터링
 *   5. 드롭다운 메뉴에 채우기
 *
 * Note:
 *   마이크 레이블을 가져오려면 권한이 필요하므로
 *   먼저 getUserMedia를 호출해야 합니다.
 */
async function enumerateMicrophones() {
  try {
    // 마이크 권한 요청 (레이블 가져오기 위해)
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach(track => track.stop());

    // 장치 목록 가져오기
    const devices = await navigator.mediaDevices.enumerateDevices();
    availableMicrophones = devices.filter(device => device.kind === 'audioinput');

    populateMicrophoneSelect();
    console.log(`Found ${availableMicrophones.length} microphone(s)`);
  } catch (error) {
    console.error('Error enumerating microphones:', error);
    statusText.textContent = "Error accessing microphones. Please grant permission.";
  }
}

/**
 * 마이크 선택 드롭다운 채우기
 *
 * availableMicrophones 목록을 사용하여
 * <select> 요소에 옵션을 추가합니다.
 * 저장된 선택을 복원합니다.
 */
function populateMicrophoneSelect() {
  if (!microphoneSelect) return;

  microphoneSelect.innerHTML = '<option value="">Default Microphone</option>';

  availableMicrophones.forEach((device, index) => {
    const option = document.createElement('option');
    option.value = device.deviceId;
    option.textContent = device.label || `Microphone ${index + 1}`;
    microphoneSelect.appendChild(option);
  });

  const savedMicId = localStorage.getItem('selectedMicrophone');
  if (savedMicId && availableMicrophones.some(mic => mic.deviceId === savedMicId)) {
    microphoneSelect.value = savedMicId;
    selectedMicrophoneId = savedMicId;
  }
}

function handleMicrophoneChange() {
  selectedMicrophoneId = microphoneSelect.value || null;
  localStorage.setItem('selectedMicrophone', selectedMicrophoneId || '');

  const selectedDevice = availableMicrophones.find(mic => mic.deviceId === selectedMicrophoneId);
  const deviceName = selectedDevice ? selectedDevice.label : 'Default Microphone';

  console.log(`Selected microphone: ${deviceName}`);
  statusText.textContent = `Microphone changed to: ${deviceName}`;

  if (isRecording) {
    statusText.textContent = "Switching microphone... Please wait.";
    stopRecording().then(() => {
      setTimeout(() => {
        toggleRecording();
      }, 1000);
    });
  }
}

// ============================================================================
// WebSocket 및 연결 설정
// ============================================================================

/**
 * 숫자 포맷팅 헬퍼 (소수점 1자리)
 *
 * @param {any} x - 포맷팅할 값
 * @returns {string} 포맷팅된 문자열 또는 원본 값
 */
function fmt1(x) {
  const n = Number(x);
  return Number.isFinite(n) ? n.toFixed(1) : x;
}

// WebSocket URL 자동 감지
let host, port, protocol;
port = 8000;
if (isExtension) {
    host = "localhost";
    protocol = "ws";
} else {
    host = window.location.hostname || "localhost";
    port = window.location.port;
    protocol = window.location.protocol === "https:" ? "wss" : "ws";
}
const defaultWebSocketUrl = `${protocol}://${host}${port ? ":" + port : ""}/asr`;

// Populate default caption and input
if (websocketDefaultSpan) websocketDefaultSpan.textContent = defaultWebSocketUrl;
websocketInput.value = defaultWebSocketUrl;
websocketUrl = defaultWebSocketUrl;

// Optional chunk selector (guard for presence)
if (chunkSelector) {
  chunkSelector.addEventListener("change", () => {
    chunkDuration = parseInt(chunkSelector.value);
  });
}

// WebSocket input change handling
websocketInput.addEventListener("change", () => {
  const urlValue = websocketInput.value.trim();
  if (!urlValue.startsWith("ws://") && !urlValue.startsWith("wss://")) {
    statusText.textContent = "Invalid WebSocket URL (must start with ws:// or wss://)";
    return;
  }
  websocketUrl = urlValue;
  statusText.textContent = "WebSocket URL updated. Ready to connect.";
});

/**
 * WebSocket 연결 설정
 *
 * WebSocket을 생성하고 이벤트 핸들러를 등록합니다.
 * Promise를 반환하여 연결 완료를 대기할 수 있습니다.
 *
 * 이벤트 핸들러:
 *   - onopen: 연결 성공 시 resolve
 *   - onmessage: 전사 결과 수신 시 updateTranscription 호출
 *   - onerror: 오류 발생 시 reject
 *   - onclose: 연결 종료 시 상태 업데이트 및 재연결
 *
 * @returns {Promise<void>} 연결 성공 시 resolve
 */
function setupWebSocket() {
  return new Promise((resolve, reject) => {
    try {
      websocket = new WebSocket(websocketUrl);
    } catch (error) {
      statusText.textContent = "Invalid WebSocket URL. Please check and try again.";
      reject(error);
      return;
    }

    // 연결 성공
    websocket.onopen = () => {
      statusText.textContent = "Connected to server.";
      resolve();
    };

    websocket.onclose = () => {
      if (userClosing) {
        if (waitingForStop) {
          statusText.textContent = "Processing finalized or connection closed.";
          if (lastReceivedData) {
          renderLinesWithBuffer(
              lastReceivedData.lines || [],
              lastReceivedData.buffer_diarization || "",
              lastReceivedData.buffer_transcription || "",
              lastReceivedData.buffer_translation || "",
              0,
              0,
              true
            );
          }
        }
      } else {
        statusText.textContent = "Disconnected from the WebSocket server. (Check logs if model is loading.)";
        if (isRecording) {
          stopRecording();
        }
      }
      isRecording = false;
      waitingForStop = false;
      userClosing = false;
      lastReceivedData = null;
      websocket = null;
      updateUI();
    };

    websocket.onerror = () => {
      statusText.textContent = "Error connecting to WebSocket.";
      reject(new Error("Error connecting to WebSocket"));
    };

    websocket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "config") {
        serverUseAudioWorklet = !!data.useAudioWorklet;
        statusText.textContent = serverUseAudioWorklet
          ? "Connected. Using AudioWorklet (PCM)."
          : "Connected. Using MediaRecorder (WebM).";
        if (configReadyResolve) configReadyResolve();
        return;
      }

      if (data.type === "ready_to_stop") {
        console.log("Ready to stop received, finalizing display and closing WebSocket.");
        waitingForStop = false;

        if (lastReceivedData) {
          renderLinesWithBuffer(
            lastReceivedData.lines || [],
            lastReceivedData.buffer_diarization || "",
            lastReceivedData.buffer_transcription || "",
            lastReceivedData.buffer_translation || "",
            0,
            0,
            true
          );
        }
        statusText.textContent = "Finished processing audio! Ready to record again.";
        recordButton.disabled = false;

        if (websocket) {
          websocket.close();
        }
        return;
      }

      lastReceivedData = data;

      const {
        lines = [],
        buffer_transcription = "",
        buffer_diarization = "",
        buffer_translation = "",
        remaining_time_transcription = 0,
        remaining_time_diarization = 0,
        status = "active_transcription",
        summary = null,
        timestamp_summaries = [],
        ai_response = null,
      } = data;

      // 타임스탬프 요약 업데이트 (실시간)
      if (timestamp_summaries && timestamp_summaries.length > 0) {
        updateTimestampSummaries(timestamp_summaries);
      }

      // AI 어시스턴트 응답 표시
      if (ai_response) {
        console.log("🤖 AI 응답:", ai_response.command, "→", ai_response.response);
        displayAIResponse(ai_response);
      }

      // 요약 데이터가 있으면 요약 패널 업데이트
      if (summary) {
        updateSummaryPanel(summary);
      }

      renderLinesWithBuffer(
        lines,
        buffer_diarization,
        buffer_transcription,
        buffer_translation,
        remaining_time_diarization,
        remaining_time_transcription,
        false,
        status
      );
    };
  });
}

/**
 * 요약 패널 업데이트
 *
 * ChatGPT API에서 받은 요약 결과를 Right Panel에 표시합니다.
 *
 * @param {Object} summaryData - 요약 결과 객체
 *   백엔드 구조: { full: {...}, hierarchical: {...} }
 *   또는 직접: { summary: "...", speaker_summaries: {...}, ... }
 */
function updateSummaryPanel(summaryData) {
  const container = document.getElementById('speakerSummary');
  if (!container || !summaryData) return;

  // 중첩 구조 처리: summary.full 또는 summary.hierarchical 우선 사용
  let summary = summaryData;
  if (summaryData.hierarchical) {
    summary = summaryData.hierarchical;
  } else if (summaryData.full) {
    summary = summaryData.full;
  }

  let html = '';

  // 에러가 있으면 에러 표시
  if (summary.error) {
    html = `
      <div class="summary-error">
        <p>Summary failed: ${escapeHtml(summary.error)}</p>
      </div>
    `;
    container.innerHTML = html;
    return;
  }

  // Summary
  if (summary.summary) {
    html += `
      <div class="summary-section">
        <h3 class="summary-title">Summary</h3>
        <p class="summary-text">${escapeHtml(summary.summary)}</p>
      </div>
    `;
  }

  // Speaker Arguments
  if (summary.speaker_summaries && Object.keys(summary.speaker_summaries).length > 0) {
    html += `<div class="summary-section"><h3 class="summary-title">Speaker Arguments</h3>`;
    for (const [speaker, argument] of Object.entries(summary.speaker_summaries)) {
      const speakerNum = parseInt(speaker) || speaker;
      html += `
        <div class="speaker-argument">
          <span class="speaker-badge speaker-${speakerNum}">Speaker ${speakerNum}</span>
          <p>${escapeHtml(argument)}</p>
        </div>
      `;
    }
    html += `</div>`;
  }

  // 토큰 사용량 (디버깅용)
  if (summary.token_usage) {
    html += `
      <div class="summary-meta">
        <small>Token usage: ${summary.token_usage}</small>
      </div>
    `;
  }

  container.innerHTML = html || '<div class="placeholder-message">No summary available.</div>';
}

/**
 * HTML 이스케이프 유틸리티
 */
function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// 타임스탬프 요약 누적 저장
let accumulatedTimestampSummaries = [];

/**
 * 타임스탬프 요약 업데이트 (실시간)
 *
 * 서버로부터 받은 타임스탬프 기반 요약들을 오른쪽 패널에 표시합니다.
 * 새로운 요약을 기존 목록에 추가하여 누적 표시합니다.
 *
 * @param {Array} timestamp_summaries - 새로 받은 타임스탬프 요약 배열
 *   예: [{ start: 0.0, end: 60.0, timestamp: "00:00 - 01:00", summary: "..." }, ...]
 */
function updateTimestampSummaries(timestamp_summaries) {
  const container = document.getElementById('timestampSummaries');
  const countElement = document.getElementById('timestampSummaryCount');

  if (!container) return;

  // 새로운 요약을 누적 목록에 추가
  if (timestamp_summaries && timestamp_summaries.length > 0) {
    accumulatedTimestampSummaries.push(...timestamp_summaries);
  }

  // 요약 개수 업데이트
  if (countElement) {
    countElement.textContent = `${accumulatedTimestampSummaries.length}개 요약`;
  }

  // 요약이 없으면 플레이스홀더 표시
  if (accumulatedTimestampSummaries.length === 0) {
    container.innerHTML = `
      <div class="placeholder-message">
        <div class="placeholder-icon">⏱️</div>
        <p>실시간 타임스탬프 요약이 여기에 표시됩니다.</p>
      </div>
    `;
    return;
  }

  // 타임스탬프 요약 HTML 생성
  let html = '';

  accumulatedTimestampSummaries.forEach((item, index) => {
    // 백엔드에서 이미 포맷팅된 timestamp 사용
    const timeRange = item.timestamp || `${Math.floor(item.start / 60)}:${Math.floor(item.start % 60).toString().padStart(2, '0')} - ${Math.floor(item.end / 60)}:${Math.floor(item.end % 60).toString().padStart(2, '0')}`;

    html += `
      <div class="timestamp-summary-item">
        <div class="timestamp-summary-header">
          <span class="timestamp-badge">${timeRange}</span>
        </div>
        <p class="timestamp-summary-text">${escapeHtml(item.summary)}</p>
      </div>
    `;
  });

  container.innerHTML = html;

  // 스크롤을 최신 요약으로 이동
  const summaryContainer = document.getElementById('timestampSummaryContainer');
  if (summaryContainer) {
    summaryContainer.scrollTo({ top: summaryContainer.scrollHeight, behavior: 'smooth' });
  }
}

/**
 * AI 어시스턴트 응답 표시
 *
 * 파동아 등 웨이크워드로 호출된 AI 응답을 화면에 표시합니다.
 *
 * @param {Object} aiResponse - AI 응답 객체
 *   예: { command: "요약해줘", response: "현재까지의 토론은...", timestamp: 1234567890 }
 */
function displayAIResponse(aiResponse) {
  if (!aiResponse || !aiResponse.response) return;

  console.log("AI 응답 수신:", aiResponse);

  // AI 응답 표시할 컨테이너 (타임스탬프 요약 위에 표시)
  let aiContainer = document.getElementById('aiResponseContainer');

  if (!aiContainer) {
    // 컨테이너가 없으면 생성
    const timestampContainer = document.getElementById('timestampSummaryContainer');
    if (timestampContainer) {
      aiContainer = document.createElement('div');
      aiContainer.id = 'aiResponseContainer';
      aiContainer.className = 'ai-response-container';
      timestampContainer.parentNode.insertBefore(aiContainer, timestampContainer);
    } else {
      return;
    }
  }

  // AI 응답 HTML 생성
  const html = `
    <div class="ai-response-card">
      <div class="ai-response-header">
        <img src="/web/padong.png" alt="파동이" class="ai-icon-img">
        <span class="ai-name">파동이</span>
        <span class="ai-command">"${escapeHtml(aiResponse.command)}"</span>
      </div>
      <div class="ai-response-content">
        ${escapeHtml(aiResponse.response)}
      </div>
    </div>
  `;

  aiContainer.innerHTML = html;
  aiContainer.style.display = 'block';

  // 5초 후 자동 숨김 (선택사항)
  // setTimeout(() => {
  //   aiContainer.style.display = 'none';
  // }, 10000);
}

function renderLinesWithBuffer(
  lines,
  buffer_diarization,
  buffer_transcription,
  buffer_translation,
  remaining_time_diarization,
  remaining_time_transcription,
  isFinalizing = false,
  current_status = "active_transcription"
) {
  if (current_status === "no_audio_detected") {
    linesTranscriptDiv.innerHTML =
      "<p style='text-align: center; color: var(--muted); margin-top: 20px;'><em>No audio detected...</em></p>";
    return;
  }

  const showLoading = !isFinalizing && (lines || []).some((it) => it.speaker == 0);
  const showTransLag = !isFinalizing && remaining_time_transcription > 0;
  const showDiaLag = !isFinalizing && !!buffer_diarization && remaining_time_diarization > 0;
  const signature = JSON.stringify({
    lines: (lines || []).map((it) => ({ speaker: it.speaker, text: it.text, start: it.start, end: it.end, detected_language: it.detected_language })),
    buffer_transcription: buffer_transcription || "",
    buffer_diarization: buffer_diarization || "",
    buffer_translation: buffer_translation,
    status: current_status,
    showLoading,
    showTransLag,
    showDiaLag,
    isFinalizing: !!isFinalizing,
  });
  if (lastSignature === signature) {
    const t = document.querySelector(".lag-transcription-value");
    if (t) t.textContent = fmt1(remaining_time_transcription);
    const d = document.querySelector(".lag-diarization-value");
    if (d) d.textContent = fmt1(remaining_time_diarization);
    const ld = document.querySelector(".loading-diarization-value");
    if (ld) ld.textContent = fmt1(remaining_time_diarization);
    return;
  }
  lastSignature = signature;

  const linesHtml = (lines || [])
    .map((item, idx) => {
      let timeInfo = "";
      if (item.start !== undefined && item.end !== undefined) {
        timeInfo = ` ${item.start} - ${item.end}`;
      }

      let speakerLabel = "";
      if (item.speaker === -2) {
        speakerLabel = `<span class="silence">${silenceIcon}<span id='timeInfo'>${timeInfo}</span></span>`;
      } else if (item.speaker == 0 && !isFinalizing) {
        speakerLabel = `<span class='loading'><span class="spinner"></span><span id='timeInfo'><span class="loading-diarization-value">${fmt1(
          remaining_time_diarization
        )}</span> second(s) of audio are undergoing diarization</span></span>`;
      } else if (item.speaker !== 0) {
        const speakerNum = `<span class="speaker-badge">${item.speaker}</span>`;
        speakerLabel = `<span id="speaker">${speakerIcon}${speakerNum}<span id='timeInfo'>${timeInfo}</span></span>`;

        if (item.detected_language) {
          speakerLabel += `<span class="label_language">${languageIcon}<span>${item.detected_language}</span></span>`;
        }
      }

      let currentLineText = item.text || "";

      if (idx === lines.length - 1) {
        if (!isFinalizing && item.speaker !== -2) {
            speakerLabel += `<span class="label_transcription"><span class="spinner"></span>Transcription lag <span id='timeInfo'><span class="lag-transcription-value">${fmt1(
              remaining_time_transcription
            )}</span>s</span></span>`;

          if (buffer_diarization && remaining_time_diarization) {
            speakerLabel += `<span class="label_diarization"><span class="spinner"></span>Diarization lag<span id='timeInfo'><span class="lag-diarization-value">${fmt1(
              remaining_time_diarization
            )}</span>s</span></span>`;
          }
        }

        if (buffer_diarization) {
          if (isFinalizing) {
            currentLineText +=
              (currentLineText.length > 0 && buffer_diarization.trim().length > 0 ? " " : "") + buffer_diarization.trim();
          } else {
            currentLineText += `<span class="buffer_diarization">${buffer_diarization}</span>`;
          }
        }
        if (buffer_transcription) {
          if (isFinalizing) {
            currentLineText +=
              (currentLineText.length > 0 && buffer_transcription.trim().length > 0 ? " " : "") +
              buffer_transcription.trim();
          } else {
            currentLineText += `<span class="buffer_transcription">${buffer_transcription}</span>`;
          }
        }
      }
      let translationContent = "";
      if (item.translation) {
        translationContent += item.translation.trim();
      }
      if (idx === lines.length - 1 && buffer_translation) {
        const bufferPiece = isFinalizing
          ? buffer_translation
          : `<span class="buffer_translation">${buffer_translation}</span>`;
        translationContent += translationContent ? `${bufferPiece}` : bufferPiece;
      }
      if (translationContent.trim().length > 0) {
        currentLineText += `
            <div>
                <div class="label_translation">
                    ${translationIcon}
                    <span class="translation_text">${translationContent}</span>
                </div>
            </div>`;
      }

      return currentLineText.trim().length > 0 || speakerLabel.length > 0
        ? `<p>${speakerLabel}<br/><div class='textcontent'>${currentLineText}</div></p>`
        : `<p>${speakerLabel}<br/></p>`;
    })
    .join("");

  linesTranscriptDiv.innerHTML = linesHtml;
  const transcriptContainer = document.querySelector('.transcript-container');
  if (transcriptContainer) {
    transcriptContainer.scrollTo({ top: transcriptContainer.scrollHeight, behavior: "smooth" });
  }
}

function updateTimer() {
  if (!startTime) return;

  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  const minutes = Math.floor(elapsed / 60).toString().padStart(2, "0");
  const seconds = (elapsed % 60).toString().padStart(2, "0");
  timerElement.textContent = `${minutes}:${seconds}`;
}

function drawWaveform() {
  if (!analyser) return;

  const bufferLength = analyser.frequencyBinCount;
  const dataArray = new Uint8Array(bufferLength);
  analyser.getByteTimeDomainData(dataArray);

  waveCtx.clearRect(
    0,
    0,
    waveCanvas.width / (window.devicePixelRatio || 1),
    waveCanvas.height / (window.devicePixelRatio || 1)
  );
  waveCtx.lineWidth = 1;
  waveCtx.strokeStyle = waveStroke;
  waveCtx.beginPath();

  const sliceWidth = (waveCanvas.width / (window.devicePixelRatio || 1)) / bufferLength;
  let x = 0;

  for (let i = 0; i < bufferLength; i++) {
    const v = dataArray[i] / 128.0;
    const y = (v * (waveCanvas.height / (window.devicePixelRatio || 1))) / 2;

    if (i === 0) {
      waveCtx.moveTo(x, y);
    } else {
      waveCtx.lineTo(x, y);
    }

    x += sliceWidth;
  }

  waveCtx.lineTo(
    waveCanvas.width / (window.devicePixelRatio || 1),
    (waveCanvas.height / (window.devicePixelRatio || 1)) / 2
  );
  waveCtx.stroke();

  animationFrame = requestAnimationFrame(drawWaveform);
}

// ============================================================================
// 녹음 시작/중지 함수
// ============================================================================

/**
 * 녹음 시작
 *
 * WebSocket 연결 후 마이크 캡처를 시작합니다.
 * 서버 설정(useAudioWorklet)에 따라 MediaRecorder 또는 AudioWorklet 모드를 선택합니다.
 *
 * 동작 흐름:
 *   1. Screen Wake Lock 획득 (화면 꺼짐 방지)
 *   2. 마이크 스트림 획득 (getUserMedia 또는 tabCapture)
 *   3. WebSocket 연결
 *   4. 서버 설정 대기 (config 메시지)
 *   5. 오디오 캡처 모드 선택:
 *      - AudioWorklet 모드: PCM Float32 → Worker → PCM Int16
 *      - MediaRecorder 모드: WebM/Opus 압축
 *   6. 타이머 및 파형 시각화 시작
 *
 * AudioWorklet 모드:
 *   - 낮은 지연시간, 높은 대역폭
 *   - PCM 데이터를 직접 전송
 *   - Web Worker에서 리샘플링 (48kHz → 16kHz)
 *
 * MediaRecorder 모드:
 *   - 압축 전송, 낮은 대역폭
 *   - WebM/Opus 컨테이너
 *   - 서버에서 FFmpeg로 디코딩
 *
 * @throws {Error} 마이크 권한 거부, WebSocket 연결 실패 등
 */
async function startRecording() {
  try {
    // 타임스탬프 요약 초기화 (새 세션 시작)
    accumulatedTimestampSummaries = [];
    const timestampContainer = document.getElementById('timestampSummaries');
    if (timestampContainer) {
      timestampContainer.innerHTML = `
        <div class="placeholder-message">
          <div class="placeholder-icon">⏱️</div>
          <p>실시간 타임스탬프 요약이 여기에 표시됩니다.</p>
        </div>
      `;
    }
    const timestampCount = document.getElementById('timestampSummaryCount');
    if (timestampCount) {
      timestampCount.textContent = '실시간 요약';
    }

    // 1. Screen Wake Lock 획득 (화면 꺼짐 방지)
    try {
      wakeLock = await navigator.wakeLock.request("screen");
    } catch (err) {
      console.log("Error acquiring wake lock.");
    }

    let stream;
    
    // chromium extension. in the future, both chrome page audio and mic will be used
    if (isExtension) {
      try {
        stream = await new Promise((resolve, reject) => {
          chrome.tabCapture.capture({audio: true}, (s) => {
            if (s) {
              resolve(s);
            } else {
              reject(new Error('Tab capture failed or not available'));
            }
          });
        });
        
        try {
          outputAudioContext = new (window.AudioContext || window.webkitAudioContext)();
          audioSource = outputAudioContext.createMediaStreamSource(stream);
          audioSource.connect(outputAudioContext.destination);
        } catch (audioError) {
          console.warn('could not preserve system audio:', audioError);
        }
        
        statusText.textContent = "Using tab audio capture.";
      } catch (tabError) {
        console.log('Tab capture not available, falling back to microphone', tabError);
        const audioConstraints = selectedMicrophoneId
          ? { audio: { deviceId: { exact: selectedMicrophoneId } } }
          : { audio: true };
        stream = await navigator.mediaDevices.getUserMedia(audioConstraints);
        statusText.textContent = "Using microphone audio.";
      }
    } else if (isWebContext) {
      const audioConstraints = selectedMicrophoneId 
        ? { audio: { deviceId: { exact: selectedMicrophoneId } } }
        : { audio: true };
      stream = await navigator.mediaDevices.getUserMedia(audioConstraints);
    }

    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    microphone = audioContext.createMediaStreamSource(stream);
    microphone.connect(analyser);

    if (serverUseAudioWorklet) {
      if (!audioContext.audioWorklet) {
        throw new Error("AudioWorklet is not supported in this browser");
      }
      await audioContext.audioWorklet.addModule("/web/pcm_worklet.js");
      workletNode = new AudioWorkletNode(audioContext, "pcm-forwarder", { numberOfInputs: 1, numberOfOutputs: 0, channelCount: 1 });
      microphone.connect(workletNode);

      recorderWorker = new Worker("/web/recorder_worker.js");
      recorderWorker.postMessage({
        command: "init",
        config: {
          sampleRate: audioContext.sampleRate,
        },
      });

      recorderWorker.onmessage = (e) => {
        if (websocket && websocket.readyState === WebSocket.OPEN) {
          websocket.send(e.data.buffer);
        }
      };

      workletNode.port.onmessage = (e) => {
        const data = e.data;
        const ab = data instanceof ArrayBuffer ? data : data.buffer;
        recorderWorker.postMessage(
          {
            command: "record",
            buffer: ab,
          },
          [ab]
        );
      };
    } else {
      try {
        recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
      } catch (e) {
        recorder = new MediaRecorder(stream);
      }
      recorder.ondataavailable = (e) => {
        if (websocket && websocket.readyState === WebSocket.OPEN) {
          if (e.data && e.data.size > 0) {
            websocket.send(e.data);
          }
        }
      };
      recorder.start(chunkDuration);
    }

    startTime = Date.now();
    timerInterval = setInterval(updateTimer, 1000);
    drawWaveform();

    isRecording = true;
    updateUI();
  } catch (err) {
    if (window.location.hostname === "0.0.0.0") {
      statusText.textContent =
        "Error accessing microphone. Browsers may block microphone access on 0.0.0.0. Try using localhost:8000 instead.";
    } else {
      statusText.textContent = "Error accessing microphone. Please allow microphone access.";
    }
    console.error(err);
  }
}

/**
 * 녹음 중지
 *
 * 모든 오디오 캡처를 중지하고 리소스를 정리합니다.
 * 서버에 빈 Blob을 전송하여 스트림 종료를 알립니다.
 *
 * 정리 항목:
 *   1. Screen Wake Lock 해제
 *   2. 서버에 빈 Blob 전송 (스트림 종료 신호)
 *   3. MediaRecorder 중지
 *   4. Web Worker 종료
 *   5. AudioWorkletNode 연결 해제
 *   6. 마이크 스트림 중지
 *   7. AudioContext 중지
 *   8. 타이머 및 애니메이션 중지
 *   9. 서버의 ready_to_stop 메시지 대기
 *
 * Note:
 *   waitingForStop 플래그를 설정하여 서버가 모든 오디오를
 *   처리할 때까지 기다립니다. ready_to_stop 메시지를 받으면
 *   WebSocket을 닫습니다.
 */
async function stopRecording() {
  // 1. Screen Wake Lock 해제
  if (wakeLock) {
    try {
      await wakeLock.release();
    } catch (e) {
      // ignore
    }
    wakeLock = null;
  }

  userClosing = true;         // 사용자가 의도적으로 종료
  waitingForStop = true;      // 서버의 ready_to_stop 대기

  // 2. 서버에 빈 Blob 전송 (스트림 종료 신호)
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    const emptyBlob = new Blob([], { type: "audio/webm" });
    websocket.send(emptyBlob);
    statusText.textContent = "Recording stopped. Processing final audio...";
  }

  // 3. MediaRecorder 중지
  if (recorder) {
    try {
      recorder.stop();
    } catch (e) {
      // 이미 중지됨
    }
    recorder = null;
  }

  // 4. Web Worker 종료 (PCM 리샘플링)
  if (recorderWorker) {
    recorderWorker.terminate();
    recorderWorker = null;
  }

  // 5. AudioWorkletNode 연결 해제
  if (workletNode) {
    try {
      workletNode.port.onmessage = null;
    } catch (e) {}
    try {
      workletNode.disconnect();
    } catch (e) {}
    workletNode = null;
  }

  // 6. 마이크 스트림 중지
  if (microphone) {
    microphone.disconnect();
    microphone = null;
  }

  if (analyser) {
    analyser = null;
  }

  if (audioContext && audioContext.state !== "closed") {
    try {
      await audioContext.close();
    } catch (e) {
      console.warn("Could not close audio context:", e);
    }
    audioContext = null;
  }

  if (audioSource) {
    audioSource.disconnect();
    audioSource = null;
  }

  if (outputAudioContext && outputAudioContext.state !== "closed") {
    outputAudioContext.close()
    outputAudioContext = null;
  }

  if (animationFrame) {
    cancelAnimationFrame(animationFrame);
    animationFrame = null;
  }

  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
  timerElement.textContent = "00:00";
  startTime = null;

  isRecording = false;
  updateUI();
}

async function toggleRecording() {
  if (!isRecording) {
    if (waitingForStop) {
      console.log("Waiting for stop, early return");
      return;
    }
    console.log("Connecting to WebSocket");
    try {
      if (websocket && websocket.readyState === WebSocket.OPEN) {
        await configReady;
        await startRecording();
      } else {
        await setupWebSocket();
        await configReady;
        await startRecording();
      }
    } catch (err) {
      statusText.textContent = "Could not connect to WebSocket or access mic. Aborted.";
      console.error(err);
    }
  } else {
    console.log("Stopping recording");
    stopRecording();
  }
}

function updateUI() {
  recordButton.classList.toggle("recording", isRecording);
  recordButton.disabled = waitingForStop;

  if (waitingForStop) {
    // 처리 대기 중 메시지 숨김
    statusText.textContent = "";
  } else if (isRecording) {
    statusText.textContent = "";
  } else {
    if (
      statusText.textContent !== "Finished processing audio! Ready to record again." &&
      statusText.textContent !== "Processing finalized or connection closed."
    ) {
      statusText.textContent = "Click to start transcription";
    }
  }
  if (!waitingForStop) {
    recordButton.disabled = false;
  }
}

recordButton.addEventListener("click", toggleRecording);

if (microphoneSelect) {
  microphoneSelect.addEventListener("change", handleMicrophoneChange);
}
document.addEventListener('DOMContentLoaded', async () => {
  try {
    await enumerateMicrophones();
  } catch (error) {
    console.log("Could not enumerate microphones on load:", error);
  }
});
navigator.mediaDevices.addEventListener('devicechange', async () => {
  console.log('Device change detected, re-enumerating microphones');
  try {
    await enumerateMicrophones();
  } catch (error) {
    console.log("Error re-enumerating microphones:", error);
  }
});


settingsToggle.addEventListener("click", () => {
settingsDiv.classList.toggle("visible");
settingsToggle.classList.toggle("active");
});

if (isExtension) {
  async function checkAndRequestPermissions() {
    const micPermission = await navigator.permissions.query({
      name: "microphone",
    });

    const permissionDisplay = document.getElementById("audioPermission");
    if (permissionDisplay) {
      permissionDisplay.innerText = `MICROPHONE: ${micPermission.state}`;
    }

    // if (micPermission.state !== "granted") {
    //   chrome.tabs.create({ url: "welcome.html" });
    // }

    const intervalId = setInterval(async () => {
      const micPermission = await navigator.permissions.query({
        name: "microphone",
      });
      if (micPermission.state === "granted") {
        if (permissionDisplay) {
          permissionDisplay.innerText = `MICROPHONE: ${micPermission.state}`;
        }
        clearInterval(intervalId);
      }
    }, 100);
  }

  void checkAndRequestPermissions();
}

// ================================
// 화자별 요약 기능 (파이보 프로젝트)
// ================================

/**
 * 화자별 메시지 데이터 저장
 * 형식: { "SPEAKER_00": ["발언1", "발언2", ...], "SPEAKER_01": [...], ... }
 */
const speakerMessages = {};

/**
 * 화자별 요약 업데이트
 *
 * 현재는 화자별 발언 수를 표시하는 간단한 버전입니다.
 * 나중에 LLM API를 연동하여 실제 논지 요약을 생성할 수 있습니다.
 */
function updateSpeakerSummary() {
  const summaryContainer = document.getElementById('speakerSummary');

  // Show placeholder if no speakers
  if (Object.keys(speakerMessages).length === 0) {
    summaryContainer.innerHTML = `
      <div class="summary-placeholder">
        Speaker arguments will appear here when conversation starts.
      </div>
    `;
    return;
  }

  // 화자별 요약 HTML 생성
  let summaryHTML = '';

  for (const [speaker, messages] of Object.entries(speakerMessages)) {
    // 화자 이름 한글화
    const speakerName = speaker.replace('SPEAKER_', '화자 ');

    // 최근 3개 발언만 표시
    const recentMessages = messages.slice(-3);

    summaryHTML += `
      <div class="speaker-summary-item">
        <h3>
          <span class="label_diarization">${speakerName}</span>
          <span style="font-size: 14px; font-weight: normal; color: var(--muted);">
            (총 ${messages.length}개 발언)
          </span>
        </h3>
        <ul>
          ${recentMessages.map(msg => `<li>${msg}</li>`).join('')}
        </ul>
      </div>
    `;
  }

  summaryContainer.innerHTML = summaryHTML;
}

/**
 * 화자 메시지 추가
 *
 * @param {string} speaker - 화자 ID (예: "SPEAKER_00")
 * @param {string} message - 메시지 내용
 */
function addSpeakerMessage(speaker, message) {
  // 화자가 없으면 배열 초기화
  if (!speakerMessages[speaker]) {
    speakerMessages[speaker] = [];
  }

  // 메시지 추가 (중복 체크)
  const trimmedMessage = message.trim();
  if (trimmedMessage && !speakerMessages[speaker].includes(trimmedMessage)) {
    speakerMessages[speaker].push(trimmedMessage);

    // 요약 업데이트
    updateSpeakerSummary();
  }
}

/**
 * 새로고침 버튼 이벤트 핸들러
 */
document.getElementById('refreshSummary')?.addEventListener('click', () => {
  updateSpeakerSummary();

  // 버튼 애니메이션
  const button = document.getElementById('refreshSummary');
  button.style.transform = 'rotate(360deg)';
  setTimeout(() => {
    button.style.transform = 'rotate(0deg)';
  }, 300);
});

/**
 * WebSocket 메시지 처리 수정
 *
 * 기존 displayTranscript 함수를 확장하여 화자별 메시지를 추적합니다.
 * 이 함수는 기존 코드의 displayTranscript를 래핑합니다.
 */
const originalDisplayTranscript = window.displayTranscript;
if (originalDisplayTranscript) {
  window.displayTranscript = function(data) {
    // 기존 함수 실행
    originalDisplayTranscript(data);

    // 화자 정보 추출 및 저장
    if (data.speaker && data.text) {
      addSpeakerMessage(data.speaker, data.text);
    }
  };
}

// 초기 플레이스홀더 표시
updateSpeakerSummary();
