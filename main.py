"""MCSaveHelper —— Minecraft 存档管理工具

启动入口：确保依赖已安装，然后直接运行。
  python main.py
"""
import sys
import traceback


def main() -> None:
    """应用主入口"""
    try:
        import flet as ft
        from app.application import Application

        ft.app(lambda page: Application(page))

    except ImportError as e:
        print(f"[FATAL] 缺少依赖: {e}")
        print("请运行: pip install -r requirements.txt")
        sys.exit(1)
    except Exception:
        print("[FATAL] 应用启动失败:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
