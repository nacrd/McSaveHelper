"""MCSaveHelper —— Minecraft 存档管理工具

启动入口：确保依赖已安装，然后直接运行。
  python main.py

打包后命令行调试：
  MCSaveHelper.exe --console
"""
import traceback
import sys
from pathlib import Path


CONSOLE_FLAG = "--console"


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


def _consume_console_flag(argv: list[str]) -> bool:
    """Remove the private console flag before Flet parses arguments."""
    if CONSOLE_FLAG not in argv:
        return False

    argv[:] = [argument for argument in argv if argument != CONSOLE_FLAG]
    return True


def _get_log_path() -> Path:
    """获取启动错误日志路径"""
    if _is_packaged():
        log_dir = Path(sys.executable).parent
    else:
        log_dir = Path(__file__).parent
    return log_dir / "startup_error.log"


def _run_application() -> None:
    """Configure shared runtime policy and start the Flet application."""
    from core.threading_runtime import configure_thread_fairness

    configure_thread_fairness()

    import flet as ft

    from app.application import Application

    ft.run(Application)


def _report_startup_failure(message: str) -> int:
    """Report one fatal startup failure and return the process exit code."""
    print(message)
    _write_error_log(message)
    return 1


def main(argv: list[str] | None = None) -> int:
    """应用主入口。

    解析 ``--console``、配置线程公平性并启动 Flet 应用。
    启动失败时写入 ``startup_error.log`` 并以非零状态退出。

    Args:
        argv: 进程参数；默认使用并原位更新 ``sys.argv``。

    Returns:
        进程退出码，成功为 0，启动失败为 1。
    """
    process_args = sys.argv if argv is None else argv
    if _consume_console_flag(process_args):
        _setup_console()

    try:
        _run_application()
    except ImportError as exc:
        message = (
            f"[FATAL] 缺少依赖: {exc}\n"
            "请运行: pip install -r requirements.txt"
        )
        return _report_startup_failure(message)
    except Exception:
        # 进程入口边界：记录完整栈并退出，避免 GUI 子系统静默失败。
        message = "[FATAL] 应用启动失败:\n" + traceback.format_exc()
        return _report_startup_failure(message)

    return 0


def _write_error_log(msg: str) -> None:
    """将错误写入启动日志，便于排查打包后的问题。

    Args:
        msg: 要写入的错误文本。
    """
    try:
        log_path = _get_log_path()
        log_path.write_text(msg, encoding="utf-8")
        print(f"错误日志已保存到: {log_path}")
    except OSError:
        # best-effort：日志本身失败不应再抛出。
        pass


if __name__ == "__main__":
    raise SystemExit(main())
