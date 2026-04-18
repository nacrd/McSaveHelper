# MC Migrator Pro · Minecraft 存档迁移工具

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![UI: CustomTkinter](https://img.shields.io/badge/UI-CustomTkinter-0078D7)](https://github.com/TomSchimansky/CustomTkinter)

> 一款现代化的 Minecraft 客户端存档转服务端工具，支持批量处理、自定义 UUID 映射、版本检测与可视化编辑。

## ✨ 功能特点

- **🔄 双模式转换**
  - **快速模式**：仅复制双 UUID 文件，适用于纯 UUID 替换场景
  - **完整模式**：深度转换 + 可选精简，完整保留游戏数据

- **📦 批量处理**
  - 一键扫描目录下所有世界存档
  - 并发处理（可配置最大并发数）
  - 实时进度显示与日志输出

- **🔗 可视化 UUID 映射编辑器**（*新！*）
  - 表格视图直观管理玩家名‑UUID 对应关系
  - 支持拖拽排序、批量导入/导出（文本/CSV）
  - 解决正版换号、离线改名等极端需求
  - 实时验证 UUID 格式，防止错误输入

- **⚙️ 智能配置**
  - 自动检测 Minecraft 版本（基于 level.dat）
  - 可选的存档清理（移除缓存、日志等无关文件）
  - 离线模式（不请求 Mojang API）
  - 多语言界面（简体中文、English）

- **🎨 现代化界面**
  - 基于 CustomTkinter 的深色主题
  - 响应式布局，支持窗口缩放
  - 终端风格日志输出，支持彩色标签

## 🚀 快速开始

### 环境要求
- Python 3.9 或更高版本
- Windows / macOS / Linux（已测试 Windows 11）

### 安装步骤
1. 克隆或下载本仓库
   ```bash
   git clone https://github.com/yourusername/mc_migrator.git
   cd mc_migrator
   ```
2. 直接运行 `startup.bat`（Windows）

### 使用说明
1. **选择存档目录**
   - 左侧面板设置“客户端存档”路径（包含 `level.dat` 的目录）
   - 设置“服务端目录”作为输出根目录
   - 可自定义世界文件夹名称（默认为 `world`）

2. **配置迁移选项**
   - 选择“快速模式”或“完整模式”
   - 启用“离线模式”避免网络请求
   - 开启“精简存档”可删除缓存文件

3. **管理 UUID 映射**
   - 在右侧面板的 **UUID 映射管理** 区域：
     - 点击“+ 添加一行”手动输入玩家名和 UUID
     - 使用“📁 导入名单”从文本文件批量加载（格式：`玩家名 UUID`）
     - 使用“💾 导出名单”保存当前映射
     - 拖拽行左侧的 **☰** 手柄可调整顺序
     - 点击“×”按钮删除单行，点击“🗑️ 清空”移除所有映射

4. **开始转换**
   - 点击顶部导航栏的“开始转换”按钮
   - 在日志区域查看实时进度
   - 转换完成后输出目录会显示在消息框中

## ⚙️ 配置详解

程序配置存储在 `~/.mc_migrator/config.json`（用户目录下），支持以下选项：

```json
{
  "version": 2,
  "version_detection": true,
  "custom_uuid_mappings": {
    "Steve": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "Alex": "ffffffff-gggg-hhhh-iiii-jjjjjjjjjjjj"
  },
  "batch_processing": {
    "max_concurrent": 2,
    "preserve_structure": true
  },
  "ui_settings": {
    "theme": "dark",
    "auto_clear_log": true,
    "language": "zh_CN"
  },
  "api_timeout": 10,
  "cleanup_patterns": ["*.log", "cache/", "logs/"]
}
```

### 自定义 UUID 映射说明
- **键**：玩家名（字符串）
- **值**：UUID（标准格式 `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`）
- 优先级：自定义映射 > 离线 UUID > Mojang API 查询
- 支持拖拽文件导入（将映射文件拖入表格区域）

## 🧩 项目结构

```
mc_migrator/
├── core/                    # 核心逻辑
│   ├── batch_processor.py  # 批量处理器
│   ├── config.py           # 配置管理
│   ├── constants.py        # Minecraft 常量
│   ├── fast_mode.py        # 快速模式实现
│   ├── full_mode.py        # 完整模式实现
│   ├── nbt_utils.py        # NBT 文件操作
│   ├── scanner.py          # 存档扫描器
│   ├── types.py            # 类型定义
│   ├── uuid_utils.py       # UUID 工具（含映射处理）
│   └── utils.py            # 通用工具函数
├── ui/                     # 用户界面
│   ├── app.py              # 主窗口
│   ├── constants.py        # UI 常量（颜色、尺寸）
│   ├── widgets.py          # 自定义组件（*含新的 UUIDMappingTable*）
│   └── mixins/             # 混入类
│       ├── common.py       # 通用 UI 方法
│       ├── top_bar.py      # 顶部导航栏
│       ├── left_panel.py   # 左侧面板
│       └── right_panel.py  # 右侧面板（集成可视化编辑器）
├── translations/           # 多语言文件
│   ├── zh_CN.json         # 简体中文
│   └── en_US.json         # 英文
├── main.py                # 程序入口
├── requirements.txt       # Python 依赖
├── pyproject.toml        # 项目配置（类型检查）
└── startup.bat           # Windows 快捷启动脚本
```

## 🔧 开发指南

### 运行测试
项目使用严格的类型检查（mypy + pyright）：
```bash
mypy core ui
```

### 构建可执行文件
使用 PyInstaller（需额外安装）：
```bash
pyinstaller build.spec
```
生成的可执行文件位于 `dist/` 目录。

### 添加新语言
1. 复制 `translations/zh_CN.json` 为 `translations/xx_XX.json`
2. 翻译所有键值对
3. 在 `core/i18n.py` 中注册新语言代码

## ❓ 常见问题

**Q: 转换后的存档在服务端中玩家数据丢失？**  
A: 确保正确配置 UUID 映射。可使用“UUID 查询”功能获取正版玩家 UUID，或使用离线 UUID 生成器。

**Q: 批量处理时程序卡住？**  
A: 降低“最大并发数”（高级设置），或检查存档目录权限。

**Q: 如何完全重置配置？**  
A: 删除 `~/.mc_migrator/config.json` 并重启程序。

**Q: 支持哪些 Minecraft 版本？**  
A: 支持 1.0.0 至 1.19+（基于版本检测），具体见 `core/constants.py` 中的版本映射。

**Q: 可视化编辑器支持拖拽文件导入吗？**  
A: 是的，可将 `.txt` 或 `.csv` 映射文件直接拖入表格区域。

## 📄 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。  
依赖的第三方库请参考其各自许可证。

## 🙏 致谢

- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) – 现代化 UI 框架
- [nbtlib](https://github.com/vberlier/nbtlib) – NBT 文件解析
- [anvil-parser2](https://github.com/TkTech/anvil-parser2) – 区块文件读取
- [Mojang API](https://api.mojang.com) – 正版 UUID 查询服务

---

> **提示**：遇到问题或希望贡献代码？欢迎提交 Issue 或 Pull Request！
