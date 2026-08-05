"""Qt Minecraft 风格物品槽：emoji / 贴图 / 数量 / 耐久 / 附魔。"""
from __future__ import annotations

import base64
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.services.item_icons import get_item_emoji
from app.services.item.models import ItemInfo


SLOT_BG_EMPTY = "#2a2a2e"
SLOT_BG_FILLED = "#3a3a3e"
SELECTED_BORDER = "#42A5F5"
DURABILITY_HIGH = "#4CAF50"
DURABILITY_MEDIUM = "#FF9800"
DURABILITY_LOW = "#F44336"
ENCHANTMENT_COLOR = "#7B68EE"


class QtItemSlot(QFrame):
    """单个物品槽控件：居中图标 + 角标层。"""

    def __init__(
        self,
        slot_size: int = 48,
        *,
        count_size: int = 9,
        on_click: Optional[object] = None,
    ) -> None:
        """创建空槽。

        Args:
            slot_size: 边长像素。
            count_size: 数量字号。
            on_click: 可选无参点击回调。
        """
        super().__init__()
        self._slot_size = slot_size
        self._on_click = on_click
        self.setFixedSize(slot_size, slot_size)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._image = QLabel(self)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setGeometry(0, 0, slot_size, slot_size)
        self._image.hide()
        self._icon = QLabel(self)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setGeometry(0, 0, slot_size, slot_size)
        self._icon.setStyleSheet("background: transparent; font-size: 20px;")
        self._count = QLabel(self)
        self._count.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
        )
        self._count.setGeometry(2, 2, slot_size - 4, slot_size - 4)
        self._count.setStyleSheet(
            f"background: transparent; color: #ddd; "
            f"font-size: {count_size}px; font-weight: bold;"
        )
        self._durability = QLabel(self)
        self._durability.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
        )
        self._durability.setGeometry(2, 2, slot_size - 4, slot_size - 4)
        self._durability.setStyleSheet(
            f"background: transparent; color: {DURABILITY_HIGH}; font-size: 6px;"
        )
        self._enchant = QLabel(self)
        self._enchant.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._enchant.setGeometry(2, 1, slot_size - 4, slot_size - 4)
        self._enchant.setStyleSheet(
            f"background: transparent; color: {ENCHANTMENT_COLOR}; font-size: 7px;"
        )
        self.reset()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and callable(self._on_click)
        ):
            self._on_click()
        super().mousePressEvent(event)

    def reset(self) -> None:
        """清空槽位显示。"""
        self.set_selected(False)
        self.setStyleSheet(
            f"QFrame {{ background-color: {SLOT_BG_EMPTY}; "
            f"border: 2px solid rgba(255,255,255,0.12); border-radius: 2px; }}"
        )
        self.setToolTip("")
        self._image.hide()
        self._image.clear()
        self._icon.setText("")
        self._icon.show()
        self._count.setText("")
        self._durability.setText("")
        self._enchant.setText("")

    def apply_item(self, item_info: ItemInfo, tooltip: str) -> None:
        """用物品信息填充槽位。"""
        self.setStyleSheet(
            f"QFrame {{ background-color: {SLOT_BG_FILLED}; "
            f"border: 2px solid rgba(255,255,255,0.12); border-radius: 2px; }}"
        )
        self.setToolTip(tooltip)
        self._icon.setText(get_item_emoji(item_info.id))
        self._icon.show()
        self._image.hide()
        self._count.setText(
            f"×{item_info.count}" if item_info.count > 1 else ""
        )
        if item_info.durability_percent is not None:
            percent = item_info.durability_percent
            if percent > 60:
                color = DURABILITY_HIGH
            elif percent > 30:
                color = DURABILITY_MEDIUM
            else:
                color = DURABILITY_LOW
            bar_len = 6
            filled = int(percent / 100 * bar_len)
            self._durability.setText("█" * filled + "░" * (bar_len - filled))
            self._durability.setStyleSheet(
                f"background: transparent; color: {color}; font-size: 6px;"
            )
        else:
            self._durability.setText("")
        if item_info.enchantments:
            self._enchant.setText("✦" * min(len(item_info.enchantments), 3))
        else:
            self._enchant.setText("")

    def apply_texture(self, uri: str) -> None:
        """贴图就绪后覆盖 emoji。"""
        pixmap = _pixmap_from_uri(uri, int(self._slot_size * 0.7))
        if pixmap is None or pixmap.isNull():
            return
        self._image.setPixmap(pixmap)
        self._image.show()
        self._icon.hide()

    def set_selected(self, selected: bool) -> None:
        """高亮快捷栏选中槽。"""
        if selected:
            self.setStyleSheet(
                f"QFrame {{ background-color: {SLOT_BG_FILLED}; "
                f"border: 2px solid {SELECTED_BORDER}; border-radius: 2px; }}"
            )
        else:
            # 保持当前填充色由 apply/reset 决定；仅恢复默认边框时由调用方 reset/apply。
            color = (
                SLOT_BG_FILLED
                if self._icon.text() or self._image.isVisible()
                else SLOT_BG_EMPTY
            )
            self.setStyleSheet(
                f"QFrame {{ background-color: {color}; "
                f"border: 2px solid rgba(255,255,255,0.12); border-radius: 2px; }}"
            )


def _pixmap_from_uri(uri: str, size: int) -> Optional[QPixmap]:
    """从 data URI 或本地路径加载缩放贴图。"""
    try:
        if uri.startswith("data:image"):
            payload = uri.split(",", 1)[1]
            data = base64.b64decode(payload)
            pixmap = QPixmap()
            if not pixmap.loadFromData(data):
                return None
        else:
            pixmap = QPixmap(uri)
            if pixmap.isNull():
                return None
        return pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    except (ValueError, OSError, TypeError):
        return None


class QtLabeledSlot(QWidget):
    """带标题的装备槽单元格。"""

    def __init__(
        self,
        emoji: str,
        label: str,
        slot: QtItemSlot,
        width: int,
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        icon = QLabel(emoji)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("color: #9aa; font-size: 14px;")
        name = QLabel(label)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet("color: #bbb; font-size: 11px;")
        name.setWordWrap(True)
        layout.addWidget(icon)
        layout.addWidget(slot, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(name)
        self.setFixedWidth(width)
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )


__all__ = [
    "QtItemSlot",
    "QtLabeledSlot",
    "SLOT_BG_EMPTY",
    "SLOT_BG_FILLED",
    "SELECTED_BORDER",
]
