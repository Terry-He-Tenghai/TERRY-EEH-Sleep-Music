"""Session-local confirmation of complete, quality-checked state windows."""
import math


class ClassificationGate:
    def __init__(self):
        self.reset()

    def reset(self):
        self.stage = None
        self.count = 0
        self.last_time = None
        self.history = []  # 记录最近的分类历史

    def update(self, state):
        probabilities = state.aasm_state_probabilities or {}
        
        # 基础验证
        valid = (state.status == 'ok' and math.isfinite(state.signal_quality)
                 and state.signal_quality >= .5 and state.window_end_s >= 30
                 and set(probabilities) == {'W', 'N1', 'N2'}
                 and all(math.isfinite(v) and 0 <= v <= 1 for v in probabilities.values())
                 and abs(sum(probabilities.values()) - 1) <= .01)
        
        if not valid:
            self.reset()
            return False
        
        # 获取最高概率的分期
        stage = max(probabilities, key=probabilities.get)
        max_prob = probabilities[stage]
        
        # 提高置信度要求，特别是对 W（清醒）状态
        # W 状态：至少 70% 置信度
        # N1/N2 状态：至少 65% 置信度
        min_confidence = 0.70 if stage == 'W' else 0.65
        
        if max_prob < min_confidence:
            self.reset()
            return False
        
        # 检查时间戳单调性
        if self.last_time is not None and state.window_end_s <= self.last_time:
            return False
        
        # 添加到历史记录（保留最近5个）
        self.history.append(stage)
        if len(self.history) > 5:
            self.history.pop(0)
        
        # 检查稳定性：最近3个窗口中，至少2个是相同分期
        if len(self.history) >= 3:
            recent_3 = self.history[-3:]
            if recent_3.count(stage) < 2:
                # 分类不稳定，重置但保留历史
                self.count = 0
                self.stage = None
                self.last_time = state.window_end_s
                return False
        
        # 连续确认逻辑
        if stage == self.stage:
            self.count += 1
        else:
            self.count = 1
            self.stage = stage
        
        self.last_time = state.window_end_s
        
        # 需要至少3次连续确认（从2次提高到3次）
        return self.count >= 3
