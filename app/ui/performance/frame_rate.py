"""帧率监控模块

监控 UI 更新频率和帧时间。
"""
import time
from collections import deque


class FrameRateMonitor:
    """帧率监控器

    监控UI更新频率
    """

    def __init__(self, window_size: int = 60):
        """初始化帧率采样器。"""
        self.frame_times: deque = deque(maxlen=window_size)
        self.last_frame_time: float = time.time()

    def tick(self) -> None:
        """记录一次UI更新"""
        current_time = time.time()
        frame_time = current_time - self.last_frame_time
        self.frame_times.append(frame_time)
        self.last_frame_time = current_time

    def get_fps(self) -> float:
        """获取当前帧率

        Returns:
            FPS值
        """
        if len(self.frame_times) < 2:
            return 0.0

        avg_frame_time = sum(self.frame_times) / len(self.frame_times)
        if avg_frame_time == 0:
            return 0.0

        return 1.0 / avg_frame_time

    def get_average_frame_time(self) -> float:
        """获取平均帧时间（毫秒）

        Returns:
            平均帧时间
        """
        if not self.frame_times:
            return 0.0

        return (sum(self.frame_times) / len(self.frame_times)) * 1000
