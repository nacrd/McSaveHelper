# 翻译功能使用指南

## 概述

MCSaveHelper 现在支持多语言翻译功能。当前支持以下语言：
- 简体中文 (zh_CN) - 默认语言
- 英文 (en_US)

## 文件结构

```
translations/
├── zh_CN.json          # 简体中文翻译
├── en_US.json          # 英文翻译
└── README.md           # 本文件
```

## 翻译文件格式

翻译文件使用 JSON 格式，结构如下：

```json
{
  "category": {
    "subcategory": {
      "key": "翻译文本"
    }
  }
}
```

支持格式化参数，使用 `{parameter}` 语法：
```json
{
  "messages": {
    "scanned_worlds": "扫描到 {count} 个世界存档: {names}"
  }
}
```

## 在代码中使用翻译

### 1. 导入翻译函数

```python
from core.i18n import t, set_language, Language, get_translator
```

### 2. 获取翻译文本

```python
# 简单翻译
title = t("app.title")

# 带默认值的翻译
text = t("some.key", "默认文本")

# 带格式化参数的翻译
message = t("messages.scanned_worlds", "扫描到 {count} 个世界存档").format(count=5, names="world1, world2")
```

### 3. 切换语言

```python
# 切换到英文
set_language(Language.EN_US)

# 切换到中文
set_language(Language.ZH_CN)
```

### 4. 获取当前语言

```python
translator = get_translator()
current_lang = translator.current_language
```

## 添加新语言

1. 复制现有的翻译文件（如 `zh_CN.json`）并重命名为新的语言代码（如 `fr_FR.json`）
2. 翻译所有文本
3. 在 `core/i18n.py` 中的 `Language` 枚举中添加新语言
4. 在 `TranslationManager.available_languages` 属性中添加显示名称

## 在 UI 中使用翻译

### 静态文本

在 UI 构建时使用 `t()` 函数：

```python
ctk.CTkLabel(
    parent,
    text=t("left_panel.client_archive", "客户端存档"),
    # ...
)
```

### 动态文本

对于需要动态更新的文本，需要在语言切换时更新：

```python
# 在语言切换回调中更新文本
def _update_ui_texts(self):
    self.label.configure(text=t("some.key"))
```

## 配置集成

语言设置会自动保存到用户配置中（`~/.mcsavehelper/config.json`），下次启动时会自动加载上次使用的语言。

## 注意事项

1. 所有 UI 文本都应通过翻译系统获取，不要硬编码
2. 翻译键名应使用有意义的层级结构，如 `category.subcategory.key`
3. 新增文本时，需要同时更新所有翻译文件
4. 格式化参数要确保在所有语言中一致

## 故障排除

### 翻译未生效
- 检查翻译键名是否正确
- 确认翻译文件已正确加载
- 查看控制台输出是否有错误信息

### 语言切换后 UI 未更新
- 确保调用了 `_update_ui_texts()` 方法
- 检查是否所有 UI 组件都使用了翻译文本

### 翻译文件格式错误
- 使用 JSON 验证工具检查文件格式
- 确保文件编码为 UTF-8