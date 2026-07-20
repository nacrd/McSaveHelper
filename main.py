"""MCSaveHelper —— Minecraft 存档管理工具

启动入口：确保依赖已安装，然后直接运行。
  python main.py

打包后命令行调试：
  MCSaveHelper.exe --console
"""
import sys
import builtins
import traceback
from pathlib import Path

if not hasattr(builtins, 'exit'):
    setattr(builtins, 'exit', sys.exit)
if not hasattr(builtins, 'quit'):
    setattr(builtins, 'quit', sys.exit)


def _is_packaged() -> bool:
    """Return whether the entrypoint runs from a frozen executable."""
    return hasattr(sys, '_MEIPASS') or '__compiled__' in globals()


def _setup_console() -> None:
    """为 GUI 子系统的 exe 分配控制台（仅在 --console 参数时）"""
    if sys.platform != 'win32' or not _is_packaged():
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        if kernel32.AllocConsole():
            sys.stdout = open(
                'CONOUT$',
                'w',
                encoding='utf-8',
                errors='replace')
            sys.stderr = open(
                'CONOUT$',
                'w',
                encoding='utf-8',
                errors='replace')
            sys.stdin = open('CONIN$', 'r', encoding='utf-8', errors='replace')
    except Exception:
        pass


def _get_log_path() -> Path:
    """获取启动错误日志路径"""
    if _is_packaged():
        log_dir = Path(sys.executable).parent
    else:
        log_dir = Path(__file__).parent
    return log_dir / "startup_error.log"


def main() -> None:
    """应用主入口。

    解析 ``--console``、配置线程公平性并启动 Flet 应用。
    启动失败时写入 ``startup_error.log`` 并以非零状态退出。
    """
    if "--console" in sys.argv:
        sys.argv.remove("--console")
        _setup_console()

    try:
        from core.threading_runtime import configure_thread_fairness

        configure_thread_fairness()

        import flet as ft

        from app.application import Application

        ft.run(Application)

    except ImportError as exc:
        msg = (
            f"[FATAL] 缺少依赖: {exc}\n"
            "请运行: pip install -r requirements.txt"
        )
        print(msg)
        _write_error_log(msg)
        sys.exit(1)
    except Exception:
        # 进程入口边界：记录完整栈并退出，避免 GUI 子系统静默失败。
        msg = "[FATAL] 应用启动失败:\n" + traceback.format_exc()
        print(msg)
        _write_error_log(msg)
        sys.exit(1)


def _write_error_log(msg: str) -> None:
    """将错误写入启动日志，便于排查打包后的问题。

    Args:
        msg: 要写入的错误文本。
    """
    try:
        log_path = _get_log_path()
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write(msg)
        print(f"错误日志已保存到: {log_path}")
    except OSError:
        # best-effort：日志本身失败不应再抛出。
        pass


if __name__ == "__main__":
    main()
