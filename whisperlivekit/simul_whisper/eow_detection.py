"""
eow_detection.py - End-of-Word (끝말) 감지

CIF (Continuous Integrate-and-Fire) 모델을 사용한 단어 경계 감지입니다.
Simul-Whisper 논문에서 제안된 방법을 구현합니다.

주요 함수:
    - load_cif(): CIF 모델 로드 및 초기화
    - resize(): Alpha 가중치 정규화
    - fire_at_boundary(): 단어 경계 감지 (CIF 기반)

알고리즘:
    1. CIF Linear: 인코더 특징 → 알파 가중치 (0~1)
    2. Cumsum: 알파를 누적하여 integrate
    3. Threshold: 누적 값이 임계값(0.999)을 초과하면 단어 경계

참고:
    - CIF 논문: https://arxiv.org/abs/1905.11235
    - Simul-Whisper: https://arxiv.org/abs/2402.14036
"""

import torch

# Simul-Whisper 논문의 CIF 모델 기반 끝말 감지 코드

def load_cif(cfg, n_audio_state, device):
    """
    CIF (Continuous Integrate-and-Fire) 모델 로드

    CIF 모델은 인코더 특징에서 단어 경계를 예측하는 선형 레이어입니다.
    체크포인트가 제공되면 학습된 가중치를 로드하고,
    없으면 always_fire 또는 never_fire 모드로 동작합니다.

    Args:
        cfg (AlignAttConfig): AlignAtt 설정
            - cif_ckpt_path: CIF 체크포인트 경로 (빈 문자열 = 사용 안 함)
            - never_fire: True면 CIF 없이 frame_threshold만 사용
        n_audio_state (int): 인코더 출력 차원 (예: 512, 1024)
        device (torch.device): 모델을 로드할 디바이스 (CPU/CUDA)

    Returns:
        Tuple[torch.nn.Linear, bool, bool]:
            - cif_linear: CIF 선형 레이어 (n_audio_state → 1)
            - always_fire: 항상 단어 경계로 간주 (CIF 미사용)
            - never_fire: 단어 경계 감지 안 함 (CIF 미사용)

    동작 모드:
        1. cif_ckpt_path 제공: 학습된 CIF 모델 사용
           - always_fire=False, never_fire=cfg.never_fire
        2. cif_ckpt_path 없음 + never_fire=True:
           - always_fire=False, never_fire=True (CIF 안 씀, frame_threshold만 사용)
        3. cif_ckpt_path 없음 + never_fire=False:
           - always_fire=True, never_fire=False (모든 프레임을 단어 경계로 간주)
    """
    # CIF 선형 레이어 생성 (n_audio_state → 1)
    cif_linear = torch.nn.Linear(n_audio_state, 1)

    # 체크포인트 경로 확인
    if cfg.cif_ckpt_path is None or not cfg.cif_ckpt_path:
        # 체크포인트 없음 → always_fire 또는 never_fire 모드
        if cfg.never_fire:
            never_fire = True
            always_fire = False
        else:
            always_fire = True
            never_fire = False
    else:
        # 체크포인트 있음 → 학습된 CIF 모델 사용
        always_fire = False
        never_fire = cfg.never_fire
        checkpoint = torch.load(cfg.cif_ckpt_path)
        cif_linear.load_state_dict(checkpoint)

    cif_linear.to(device)
    return cif_linear, always_fire, never_fire


# 출처: https://github.com/dqqcasia/mosst/blob/master/fairseq/models/speech_to_text/convtransformer_wav2vec_cif.py
def resize(alphas, target_lengths, threshold=0.999):
    """
    Alpha 가중치를 목표 길이에 맞게 정규화

    CIF 알파 가중치의 합을 target_lengths에 맞추기 위해 스케일링하고,
    임계값을 초과하는 알파 값을 반복적으로 재분배합니다.

    Args:
        alphas (Tensor): 알파 가중치 [batch, time]
            - 각 프레임의 중요도 (0~1)
        target_lengths (Tensor): 목표 길이 [batch]
            - 알파 합계가 이 값이 되도록 스케일링
        threshold (float): 알파 최대값 임계값 (기본값 0.999)
            - 이 값을 초과하면 재분배

    Returns:
        Tuple[Tensor, Tensor]:
            - _alphas: 정규화된 알파 [batch, time]
            - _num: 원래 알파 합계 [batch]

    동작:
        1. 알파 합계 계산: _num = sum(alphas)
        2. 스케일링: _alphas = alphas * (target_lengths / _num)
        3. 임계값 초과 값 재분배 (최대 10회 반복):
           - _alphas > threshold인 위치 찾기
           - 해당 위치의 알파를 0.5로 줄이고 평균값 추가
    """
    # 알파 합계 계산
    _num = alphas.sum(-1)
    num = target_lengths.float()
    # 스케일링 (target_lengths에 맞춤)
    _alphas = alphas * (num / _num)[:, None].repeat(1, alphas.size(1))
    # 임계값 초과 값 재분배
    count = 0
    while len(torch.where(_alphas > threshold)[0]):
        count += 1
        if count > 10:  # 최대 10회 반복
            break
        xs, ys = torch.where(_alphas > threshold)
        for x, y in zip(xs, ys):
            if _alphas[x][y] >= threshold:
                mask = _alphas[x].ne(0).float()
                mean = 0.5 * _alphas[x].sum() / mask.sum()
                _alphas[x] = _alphas[x] * 0.5 + mean * mask

    return _alphas, _num

def fire_at_boundary(chunked_encoder_feature: torch.Tensor, cif_linear):
    """
    단어 경계에서 Fire 여부 감지 (CIF 기반)

    인코더 특징에 CIF 모델을 적용하여 현재 청크의 끝이
    단어 경계인지 판단합니다.

    Args:
        chunked_encoder_feature (Tensor): 인코더 특징 [batch, time, dim]
            - 현재 청크의 인코더 출력
        cif_linear (torch.nn.Linear): CIF 선형 레이어

    Returns:
        bool: True면 단어 경계 (fire), False면 아님

    알고리즘:
        1. CIF Linear: encoder_feature → alphas (알파 가중치)
        2. Sigmoid: alphas를 0~1 범위로 정규화
        3. Decode Length: round(sum(alphas))로 예상 단어 수 계산
        4. Resize: alphas를 decode_length에 맞게 정규화
        5. Cumsum: alphas를 누적하여 integrate
        6. Threshold: integrate가 0.999를 초과하는 위치 찾기
        7. 경계 판단: 첫 번째 초과 위치가 청크 끝 근처면 True

    단어 경계 조건:
        - important_positions[0] >= content_mel_len - 2
        - 즉, CIF가 청크의 마지막 2 프레임 이내에서 fire하면
          이 청크가 단어 경계라고 판단

    Note:
        integrate[-1]을 사용하여 마지막 누적 값에서
        임계값을 초과한 횟수만큼 1을 빼서 정규화합니다.
    """
    content_mel_len = chunked_encoder_feature.shape[1]  # B, T, D → T
    # CIF Linear: [B, T, D] → [B, T, 1] → [B, T]
    alphas = cif_linear(chunked_encoder_feature).squeeze(dim=2)
    # Sigmoid: 알파를 0~1 범위로 정규화
    alphas = torch.sigmoid(alphas)
    # 예상 단어 수 계산
    decode_length = torch.round(alphas.sum(-1)).int()
    # 알파 정규화 (decode_length에 맞춤)
    alphas, _ = resize(alphas, decode_length)
    alphas = alphas.squeeze(0)  # (T, )
    threshold = 0.999
    # 누적 알파 계산 (마지막 프레임 제외)
    integrate = torch.cumsum(alphas[:-1], dim=0)
    # 임계값 초과 횟수 계산
    exceed_count = integrate[-1] // threshold
    # 정규화: 초과 횟수만큼 1을 빼기
    integrate = integrate - exceed_count * 1.0
    # 0 이상인 위치 찾기 (단어 경계 후보)
    important_positions = (integrate >= 0).nonzero(as_tuple=True)[0]
    if important_positions.numel() == 0:
        return False
    else:
        # 첫 번째 단어 경계가 청크 끝 근처인지 확인
        return important_positions[0] >= content_mel_len - 2