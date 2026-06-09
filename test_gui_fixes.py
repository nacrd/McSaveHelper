"""测试 GUI 修复 - 验证图标和主题改进"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.ui.icons import IconSet
from app.ui.theme import THEME, mc_border, mc_focus_border


def test_icons():
    """测试图标系统"""
    print("=" * 60)
    print("测试图标系统")
    print("=" * 60)

    icons_to_test = [
        ("MAP", IconSet.MAP),
        ("PACKAGE", IconSet.PACKAGE),
        ("BUILD", IconSet.BUILD),
        ("PICKAXE", IconSet.PICKAXE),
        ("FOLDER", IconSet.FOLDER),
        ("SAVE", IconSet.SAVE),
        ("MINIMIZE", IconSet.MINIMIZE),
        ("MAXIMIZE", IconSet.MAXIMIZE),
        ("CLOSE", IconSet.CLOSE),
    ]

    all_passed = True
    for name, icon_value in icons_to_test:
        if isinstance(icon_value, int):
            print(f"✓ {name}: {icon_value}")
        else:
            print(f"✗ {name}: 无效值 ({type(icon_value)})")
            all_passed = False

    return all_passed


def test_theme_contrast():
    """测试文本对比度改进"""
    print("\n" + "=" * 60)
    print("测试主题对比度")
    print("=" * 60)

    def calculate_relative_luminance(hex_color):
        """计算相对亮度"""
        hex_color = hex_color.lstrip('#')
        r, g, b = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]

        def adjust(c):
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        return 0.2126 * adjust(r) + 0.7152 * adjust(g) + 0.0722 * adjust(b)

    def contrast_ratio(color1, color2):
        """计算对比度"""
        l1 = calculate_relative_luminance(color1)
        l2 = calculate_relative_luminance(color2)
        lighter = max(l1, l2)
        darker = min(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)

    tests = [
        ("text_primary on bg_primary", THEME.text_primary, THEME.bg_primary, 7.0),
        ("text_secondary on bg_primary", THEME.text_secondary, THEME.bg_primary, 4.5),
        ("text_muted on bg_primary", THEME.text_muted, THEME.bg_primary, 4.5),
    ]

    all_passed = True
    for name, fg, bg, min_ratio in tests:
        ratio = contrast_ratio(fg, bg)
        passed = ratio >= min_ratio
        symbol = "✓" if passed else "✗"
        print(f"{symbol} {name}: {ratio:.2f}:1 (需要 ≥{min_ratio}:1)")
        if not passed:
            all_passed = False

    return all_passed


def test_focus_system():
    """测试焦点系统"""
    print("\n" + "=" * 60)
    print("测试焦点系统")
    print("=" * 60)

    tests = [
        ("focus_ring 颜色", hasattr(THEME, 'focus_ring')),
        ("focus_ring_width", hasattr(THEME, 'focus_ring_width')),
        ("mc_focus_border 函数", callable(mc_focus_border)),
    ]

    all_passed = True
    for name, condition in tests:
        symbol = "✓" if condition else "✗"
        print(f"{symbol} {name}: {'通过' if condition else '失败'}")
        if not condition:
            all_passed = False

    if hasattr(THEME, 'focus_ring'):
        print(f"  - 焦点颜色: {THEME.focus_ring}")
    if hasattr(THEME, 'focus_ring_width'):
        print(f"  - 焦点宽度: {THEME.focus_ring_width}px")

    return all_passed


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("MCSaveHelper GUI 修复验证")
    print("=" * 60 + "\n")

    results = {
        "图标系统": test_icons(),
        "主题对比度": test_theme_contrast(),
        "焦点系统": test_focus_system(),
    }

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    for name, passed in results.items():
        symbol = "✓" if passed else "✗"
        print(f"{symbol} {name}: {'通过' if passed else '失败'}")

    all_passed = all(results.values())
    print("\n" + ("=" * 60))
    if all_passed:
        print("✓ 所有测试通过！")
    else:
        print("✗ 部分测试失败")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
