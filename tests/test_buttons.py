#!/usr/bin/env python
"""测试按钮组件的 disabled 属性"""
from app.ui.components.buttons import btn_primary, btn_ghost, McButton

# 测试按钮创建
btn = btn_primary("测试按钮")
print(f"按钮类型: {type(btn)}")
print(f"是否有 disabled 属性: {hasattr(btn, 'disabled')}")

# 测试设置 disabled
btn.disabled = True
print(f"设置 disabled=True 成功，当前值: {btn.disabled}")

btn.disabled = False
print(f"设置 disabled=False 成功，当前值: {btn.disabled}")

print("所有测试通过！")