"""MCSaveHelper —— Minecraft 存档管理工具

启动入口：确保依赖已安装，然后直接运行。
  python main.py

打包后命令行调试：
  MCSaveHelper.exe --console
"""
import sys
import os
import builtins
import traceback
from pathlib import Path

if not hasattr(builtins, 'exit'):
    builtins.exit = sys.exit
if not hasattr(builtins, 'quit'):
    builtins.quit = sys.exit


def _setup_console() -> None:
    """为 GUI 子系统的 exe 分配控制台（仅在 --console 参数时）"""
    if sys.platform != 'win32' or not hasattr(sys, '_MEIPASS'):
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        if kernel32.AllocConsole():
            sys.stdout = open('CONOUT$', 'w', encoding='utf-8', errors='replace')
            sys.stderr = open('CONOUT$', 'w', encoding='utf-8', errors='replace')
            sys.stdin = open('CONIN$', 'r', encoding='utf-8', errors='replace')
    except Exception:
        pass


def _get_log_path() -> Path:
    """获取启动错误日志路径"""
    if hasattr(sys, '_MEIPASS'):
        log_dir = Path(sys.executable).parent
    else:
        log_dir = Path(__file__).parent
    return log_dir / "startup_error.log"


def main() -> None:
    """应用主入口"""
    if '--console' in sys.argv:
        sys.argv.remove('--console')
        _setup_console()

    try:
        import flet as ft
        
        # ============================================================================
        # Flet 0.85+ API 兼容性补丁（Monkey Patch）
        # ============================================================================
        _patch_flet_api(ft)
        
        from app.application import Application

        ft.run(Application)

    except ImportError as e:
        msg = f"[FATAL] 缺少依赖: {e}\n请运行: pip install -r requirements.txt"
        print(msg)
        _write_error_log(msg)
        sys.exit(1)
    except Exception:
        msg = "[FATAL] 应用启动失败:\n" + traceback.format_exc()
        print(msg)
        _write_error_log(msg)
        sys.exit(1)


def _patch_flet_api(ft) -> None:
    """
    Flet 0.85+ API 兼容性补丁
    
    修复以下 API 变更：
    1. ft.alignment.center 等便捷属性不存在
    2. ft.ImageFit 改为 ft.BoxFit
    3. ft.Image 构造函数 src 参数必传
    4. ft.Dropdown 构造函数不接受 on_change
    5. ft.Spacer 已移除，用 ft.Container(expand=True) 替代
    6. ft.border.all() 已弃用
    7. page.set_clipboard() 已改为 page.set_clipboard_async()
    8. page.run_task() 要求 async 函数
    """
    try:
        # 1. 修复 alignment 便捷属性
        if not hasattr(ft.alignment, 'center'):
            ft.alignment.center = ft.alignment.Alignment(0, 0)
            ft.alignment.top_left = ft.alignment.Alignment(-1, -1)
            ft.alignment.top_center = ft.alignment.Alignment(0, -1)
            ft.alignment.top_right = ft.alignment.Alignment(1, -1)
            ft.alignment.center_left = ft.alignment.Alignment(-1, 0)
            ft.alignment.center_right = ft.alignment.Alignment(1, 0)
            ft.alignment.bottom_left = ft.alignment.Alignment(-1, 1)
            ft.alignment.bottom_center = ft.alignment.Alignment(0, 1)
            ft.alignment.bottom_right = ft.alignment.Alignment(1, 1)
        
        # 2. 修复 ImageFit -> BoxFit
        if not hasattr(ft, 'ImageFit'):
            ft.ImageFit = ft.BoxFit
        
        # 3. 包装 Image 构造函数（src 可选）
        _original_image = ft.Image
        def _image_wrapper(src=None, **kwargs):
            if src is None:
                src = ""
            return _original_image(src=src, **kwargs)
        ft.Image = _image_wrapper
        
        # 4. 包装 Dropdown 构造函数（on_change 作为参数）
        _original_dropdown = ft.Dropdown
        def _dropdown_wrapper(on_change=None, on_select=None, **kwargs):
            dropdown = _original_dropdown(**kwargs)
            if on_change is not None:
                dropdown.on_change = on_change
            if on_select is not None:
                dropdown.on_select = on_select
            return dropdown
        ft.Dropdown = _dropdown_wrapper
        
        # 5. 兼容 Spacer（已移除，用 Container 替代）
        if not hasattr(ft, 'Spacer'):
            def _spacer_wrapper():
                return ft.Container(expand=True)
            ft.Spacer = _spacer_wrapper
        
        # 6. 修复 ft.border.all() API
        if hasattr(ft, 'border') and not hasattr(ft.border, 'all'):
            def _border_all(width, color):
                """兼容旧版 ft.border.all() API"""
                return ft.border.Border(
                    left=ft.border.BorderSide(width, color),
                    right=ft.border.BorderSide(width, color),
                    top=ft.border.BorderSide(width, color),
                    bottom=ft.border.BorderSide(width, color),
                )
            ft.border.all = _border_all
        
        # 7. 修复 Page.set_clipboard() API
        _original_page_init = ft.Page.__init__
        def _page_init_wrapper(self, *args, **kwargs):
            _original_page_init(self, *args, **kwargs)
            # 添加 set_clipboard 方法
            if not hasattr(self, 'set_clipboard'):
                def _set_clipboard(text):
                    """兼容旧版 set_clipboard API"""
                    self.set_clipboard_async(text)
                self.set_clipboard = _set_clipboard
        ft.Page.__init__ = _page_init_wrapper
        
        # 8. 包装 Page.run_task（自动转换为 async）
        import inspect
        
        _original_page_class = ft.Page
        _original_run_task = _original_page_class.run_task
        
        def _run_task_wrapper(self, handler, *args, **kwargs):
            """包装 run_task，自动将普通函数转为 async"""
            if inspect.iscoroutinefunction(handler):
                # 已经是 async 函数，直接调用
                return _original_run_task(self, handler, *args, **kwargs)
            else:
                # 普通函数，包装为 async
                async def _async_wrapper():
                    return handler(*args, **kwargs)
                return _original_run_task(self, _async_wrapper)
        
        ft.Page.run_task = _run_task_wrapper
        
    except Exception as e:
        print(f"[WARNING] Flet API 补丁失败: {e}")


def _write_error_log(msg: str) -> None:
    """将错误写入日志文件，便于排查打包后的问题"""
    try:
        log_path = _get_log_path()
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(msg)
        print(f"错误日志已保存到: {log_path}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
