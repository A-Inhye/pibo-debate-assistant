"""
web_pibo_localagreement 패키지 - 파이보 프로젝트 웹 UI 리소스 (LocalAgreement 백엔드)

웹 인터페이스를 위한 HTML, CSS, JavaScript 리소스를 포함합니다.
실시간 토론 지원 시스템을 위한 브라우저 기반 UI를 제공합니다.

주요 특징:
    - 좌우 2분할 레이아웃
    - 왼쪽: 실시간 대화 기록 (시간 + 화자 + 내용)
    - 오른쪽: 화자별 논지 요약 (화자별 핵심 주장 정리)
    - LocalAgreement 백엔드 사용 (안정적)

사용법:
    from whisperlivekit.web_pibo_localagreement.web_interface import get_inline_ui_html
    html = get_inline_ui_html()

백엔드:
    LocalAgreement - 텐서 크기 오류 없이 안정적으로 동작
"""
