"""性能监控工具

提供GUI性能监控和优化工具：
- 帧率监控
- 组件渲染时间跟踪
- 内存使用监控
- 异步操作性能分析
- 健康监控和告警

本模块已重构为多个子模块，但保持完全向后兼容。
"""

# 导出核心类和数据结构
from app.ui.performance.monitor import (
    PerformanceMetric,
    PerformanceMonitor,
)

from app.ui.performance.resource import (
    ResourceUsageMonitor,
)

from app.ui.performance.health import (
    AlertLevel,
    HealthAlert,
    HealthMonitor,
)

from app.ui.performance.timer import (
    Timer,
    measure_time,
    log_slow_operation,
    AsyncOperationTracker,
)

from app.ui.performance.frame_rate import (
    FrameRateMonitor,
)

# 创建全局单例实例（向后兼容）
perf_monitor = PerformanceMonitor()
health_monitor = HealthMonitor()
resource_monitor = ResourceUsageMonitor(
    performance_monitor=perf_monitor,
    health_monitor=health_monitor,
)
async_tracker = AsyncOperationTracker()

# 导出所有公共接口
__all__ = [
    # 数据结构
    "PerformanceMetric",
    "HealthAlert",
    "AlertLevel",

    # 核心类
    "PerformanceMonitor",
    "ResourceUsageMonitor",
    "HealthMonitor",
    "FrameRateMonitor",
    "Timer",
    "AsyncOperationTracker",

    # 装饰器和工具函数
    "measure_time",
    "log_slow_operation",

    # 全局单例
    "perf_monitor",
    "resource_monitor",
    "health_monitor",
    "async_tracker",
]
