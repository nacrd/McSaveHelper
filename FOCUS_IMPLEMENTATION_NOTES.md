# GUI 修复 - 技术说明

## 焦点指示器实现限制

### 问题
在修复过程中发现 Flet 0.84+ 的 `Container` 控件不支持 `on_focus` 和 `on_blur` 事件，这导致无法直接为按钮添加键盘焦点指示器。

### 当前状态

**已完成**:
- ✅ 主题系统定义焦点颜色 (`THEME.focus_ring = "#5DFDFE"`)
- ✅ 主题系统定义焦点边框函数 (`mc_focus_border()`)
- ✅ 按钮 hover 状态提供视觉反馈

**技术限制**:
- ❌ `Container.__init__()` 不接受 `on_focus` 参数
- ❌ Flet 当前版本没有暴露焦点事件 API

### 解决方案

#### 短期方案（已实现）
使用 hover 状态作为视觉反馈：
```python
def _handle_hover(self, e: ft.ControlEvent) -> None:
    if e.data == "true":
        # 鼠标悬停 - 显示高亮
        self.bgcolor = self._bgcolor_hover
        self.shadow = ft.BoxShadow(...)
    else:
        # 鼠标离开 - 恢复正常
        self.bgcolor = self._bgcolor
```

**优点**:
- 鼠标用户体验良好
- 不依赖框架特性

**缺点**:
- 键盘导航用户无法看到焦点
- 不完全符合 WCAG 2.4.7

#### 中期方案（待实现）
使用 Flet 的其他控件替代：

**方案 A: 使用 `ElevatedButton`**
```python
ft.ElevatedButton(
    text="按钮",
    on_click=handler,
    # ElevatedButton 内置焦点支持
)
```

**方案 B: 使用 `GestureDetector` 包装**
```python
ft.GestureDetector(
    content=ft.Container(...),
    on_tap=handler,
    # 可能支持焦点事件
)
```

#### 长期方案（待框架支持）
等待 Flet 团队添加焦点事件支持：
- 提交 Feature Request 到 Flet GitHub
- 监控 Flet 版本更新
- 一旦支持，快速启用已准备好的焦点系统

### 代码准备度

焦点系统的基础设施已完全就绪：

```python
# 主题定义 ✅
THEME.focus_ring = "#5DFDFE"
THEME.focus_ring_width = 3

# 工具函数 ✅
def mc_focus_border(width: int = 3) -> ft.Border:
    return ft.Border(...)

# 按钮组件预留字段 ✅
self._is_focused = False  # 状态追踪已准备

# 事件处理器已编写（暂时注释）✅
# def _handle_focus(self, e):
#     self._is_focused = True
#     self.border = mc_focus_border(...)
```

**启用所需工作量**: 取消注释 + 添加事件绑定 (~15分钟)

### 临时缓解措施

在 Flet 支持焦点事件之前，可以通过以下方式改善键盘导航体验：

1. **增强 hover 效果** ✅ (已实现)
   - 使用明显的颜色变化
   - 添加阴影效果

2. **视觉层次** ✅ (已实现)
   - Primary 按钮使用亮绿色
   - Secondary 按钮使用灰色

3. **文档说明** ⏳
   - 在帮助文档中说明当前键盘导航限制
   - 提供鼠标操作替代方案

### 验证计划

一旦 Flet 支持焦点事件：

```python
# 1. 更新按钮组件
super().__init__(
    on_focus=self._handle_focus,  # 添加
    on_blur=self._handle_blur,    # 添加
)

# 2. 运行测试
python test_gui_fixes.py

# 3. 手动验证
# - 按 Tab 键导航
# - 确认青色焦点环可见
# - 检查所有交互元素
```

### 相关 Issue

- [Flet GitHub] 查询是否有焦点事件支持计划
- [WCAG 2.4.7] Focus Visible 要求
- [Material Design] 焦点指示器规范

### 总结

虽然受限于 Flet 框架当前能力，但我们已经：

✅ **完成基础设施** - 主题、函数、预留字段全部就绪  
✅ **提供替代反馈** - Hover 状态改善体验  
✅ **保持前瞻性** - 一旦框架支持即可快速启用  

当前的实现是在框架限制下的最佳方案，并为未来升级做好了充分准备。

---

*更新时间: 2026-06-09*  
*Flet 版本: 0.84.0*
