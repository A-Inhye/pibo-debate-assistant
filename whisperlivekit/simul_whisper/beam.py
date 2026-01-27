"""
beam.py - Beam Search Inference

Beam Search를 지원하는 PyTorch Inference 확장 클래스입니다.
Cross-attention 가중치를 반환하고 KV 캐시를 빔별로 재배열합니다.
"""

from torch import Tensor

from whisperlivekit.whisper.decoding import PyTorchInference


class BeamPyTorchInference(PyTorchInference):
    """
    Beam Search를 위한 PyTorchInference 확장

    Cross-attention 가중치 반환 및 KV 캐시 재배열 기능을 추가합니다.
    Beam Search는 여러 가설(빔)을 동시에 탐색하여 최적의 전사 결과를 찾습니다.

    주요 기능:
        - KV 캐시 재배열: 빔 순서가 변경될 때 캐시 동기화
        - Cross-attention 반환: AlignAtt 정책에서 단어 경계 감지에 사용

    상속:
        PyTorchInference: 기본 Whisper inference 클래스
    """

    def _kv_cache_ids(self):
        """
        Self-attention KV 캐시 ID 목록 가져오기

        각 디코더 블록의 key/value 캐시 ID를 반환합니다.
        KV 캐시는 이전 토큰의 attention 계산을 재사용하여 속도를 높입니다.

        Returns:
            List[str]: 캐시 ID 문자열 리스트 (key_ids + value_ids)
        """
        key_ids = [block.attn.key_cache_id for block in self.model.decoder.blocks]
        value_ids = [block.attn.value_cache_id for block in self.model.decoder.blocks]
        return key_ids + value_ids

    def rearrange_kv_cache(self, source_indices):
        """
        KV 캐시를 빔 순서에 맞게 재배열

        Beam Search 중 빔 순서가 변경될 때 (가지치기, 재정렬),
        KV 캐시도 동일한 순서로 재배열합니다.

        Args:
            source_indices (List[int]): 새로운 빔 순서 인덱스
                - 예: [0, 2, 1] → 빔 0, 2, 1 순서로 재배열

        동작:
            - source_indices가 [0, 1, 2, ...]와 다르면 재배열 수행
            - 각 KV 캐시 텐서를 source_indices 순서로 인덱싱
            - detach()로 그래디언트 전파 차단 (inference 모드)

        Note:
            순서가 변경되지 않으면 (이미 정렬됨) 아무 작업도 수행하지 않습니다.
        """
        if source_indices != list(range(len(source_indices))):
            for cache_id in self._kv_cache_ids():
                if cache_id in self.kv_cache:
                    self.kv_cache[cache_id] = self.kv_cache[cache_id][source_indices].detach()

    def logits(
        self,
        tokens: Tensor,
        audio_features: Tensor,
        return_cross_attn: bool = False,
    ):
        """
        로짓(logits) 계산 (선택적으로 cross-attention 반환)

        주어진 토큰과 오디오 특징으로 다음 토큰 확률 분포를 계산합니다.
        AlignAtt 정책을 위해 cross-attention 가중치도 반환할 수 있습니다.

        Args:
            tokens (Tensor): 입력 토큰 시퀀스 [batch_size, seq_len]
            audio_features (Tensor): 인코더 출력 [batch_size, audio_len, dim]
            return_cross_attn (bool): True면 cross-attention 가중치 반환

        Returns:
            Tuple[Tensor, Tensor] (return_cross_attn=True):
                - logits: 다음 토큰 확률 분포 [batch, seq_len, vocab_size]
                - cross_attn: Cross-attention 가중치 [batch, heads, seq_len, audio_len]
            Tensor (return_cross_attn=False):
                - logits만 반환

        Note:
            Cross-attention은 디코더가 오디오의 어느 부분에 집중하는지를 나타냅니다.
            AlignAtt 정책은 이를 분석하여 단어 경계를 감지합니다.
        """
        return self.model.decoder(
            tokens, audio_features,
            kv_cache=self.kv_cache,
            return_cross_attn=return_cross_attn,
        )