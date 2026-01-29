#!/bin/bash
# Pibo Debate Assistant - macOS 설치 스크립트
# Apple Silicon (M1/M2/M3/M4) 전용

set -e

echo "=========================================="
echo " Pibo Debate Assistant - macOS 설치"
echo "=========================================="

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 함수: 성공 메시지
success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# 함수: 경고 메시지
warn() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# 함수: 에러 메시지
error() {
    echo -e "${RED}✗ $1${NC}"
    exit 1
}

# 1. 운영체제 확인
echo ""
echo "1. 운영체제 확인..."
if [[ "$(uname)" != "Darwin" ]]; then
    error "이 스크립트는 macOS 전용입니다."
fi
success "macOS 확인됨"

# 아키텍처 확인
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
    success "Apple Silicon (arm64) 확인됨 - MLX-Whisper 사용 가능"
else
    warn "Intel Mac 감지됨 - MLX-Whisper 대신 faster-whisper 사용"
fi

# 2. Homebrew 확인
echo ""
echo "2. Homebrew 확인..."
if ! command -v brew &> /dev/null; then
    warn "Homebrew가 설치되어 있지 않습니다. 설치를 시작합니다..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    success "Homebrew 설치 완료"
else
    success "Homebrew 확인됨"
fi

# 3. Python 및 FFmpeg 설치
echo ""
echo "3. Python 3.11 및 FFmpeg 설치..."
brew install python@3.11 ffmpeg 2>/dev/null || true
success "Python 3.11 및 FFmpeg 설치 완료"

# Python 경로 확인
PYTHON_PATH=$(brew --prefix python@3.11)/bin/python3.11
if [[ ! -f "$PYTHON_PATH" ]]; then
    PYTHON_PATH=$(which python3.11 2>/dev/null || which python3)
fi
echo "   Python 경로: $PYTHON_PATH"

# 4. 프로젝트 디렉토리 이동
echo ""
echo "4. 프로젝트 디렉토리 확인..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"
success "프로젝트 디렉토리: $PROJECT_DIR"

# 5. 가상환경 생성
echo ""
echo "5. 가상환경 생성..."
if [[ -d "venv" ]]; then
    warn "기존 가상환경이 있습니다. 덮어쓰기합니다..."
    rm -rf venv
fi
$PYTHON_PATH -m venv venv
source venv/bin/activate
success "가상환경 생성 완료 (venv)"

# pip 업그레이드
pip install --upgrade pip setuptools wheel

# 6. 기본 의존성 설치
echo ""
echo "6. 기본 의존성 설치..."
pip install -e .
success "기본 패키지 설치 완료"

# 7. macOS 전용 패키지 설치
echo ""
echo "7. macOS 전용 패키지 설치..."

if [[ "$ARCH" == "arm64" ]]; then
    # Apple Silicon: MLX-Whisper 설치
    pip install mlx-whisper
    success "MLX-Whisper 설치 완료 (Apple Silicon 최적화)"
fi

# diart 및 pyannote 설치 (화자분리용)
echo "   화자분리 패키지 설치 중... (시간이 걸릴 수 있습니다)"
pip install diart pyannote.audio
success "diart 및 pyannote.audio 설치 완료"

# OpenAI 패키지 설치
pip install openai tiktoken
success "OpenAI 패키지 설치 완료"

# 8. 환경 변수 설정
echo ""
echo "8. 환경 변수 설정..."
if [[ ! -f ".env" ]]; then
    echo '# OpenAI API 키 설정' > .env
    echo '# https://platform.openai.com/api-keys 에서 발급' >> .env
    echo 'export OPENAI_API_KEY="sk-your-api-key-here"' >> .env
    warn ".env 파일이 생성되었습니다. API 키를 설정해주세요."
else
    success ".env 파일이 이미 존재합니다."
fi

# 9. Hugging Face 토큰 안내
echo ""
echo "=========================================="
echo " 추가 설정 필요"
echo "=========================================="
echo ""
echo "화자분리 기능을 사용하려면 Hugging Face 설정이 필요합니다:"
echo ""
echo "1. Hugging Face 계정 생성: https://huggingface.co/join"
echo "2. 토큰 발급: https://huggingface.co/settings/tokens"
echo "3. 모델 사용 동의:"
echo "   - https://huggingface.co/pyannote/segmentation-3.0"
echo "   - https://huggingface.co/pyannote/embedding"
echo ""
echo "설정 후 다음 명령어 실행:"
echo "   huggingface-cli login"
echo ""

# 10. 설치 완료
echo "=========================================="
echo " 설치 완료!"
echo "=========================================="
echo ""
echo "실행 방법:"
echo ""
echo "# 1. 가상환경 활성화"
echo "source venv/bin/activate"
echo ""
echo "# 2. .env 파일에 OpenAI API 키 설정"
echo "nano .env"
echo ""
echo "# 3. 서버 실행"
if [[ "$ARCH" == "arm64" ]]; then
    echo "source .env && python -m whisperlivekit.basic_server_pibo_design \\"
    echo "  --model small \\"
    echo "  --language ko \\"
    echo "  --diarization \\"
    echo "  --backend mlx-whisper \\"
    echo "  --enable-summary"
else
    echo "source .env && python -m whisperlivekit.basic_server_pibo_design \\"
    echo "  --model small \\"
    echo "  --language ko \\"
    echo "  --diarization \\"
    echo "  --enable-summary"
fi
echo ""
echo "# 4. 브라우저에서 접속"
echo "http://localhost:8000"
echo ""
