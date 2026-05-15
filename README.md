# MCSaveHelper · Minecraft 存档管理工具

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![UI: Flet](https://img.shields.io/badge/UI-Flet-0078D7)](https://flet.dev)

> 一款现代化的 Minecraft 存档管理工具，支持批量处理、自定义 UUID 映射、版本检测与可视化编辑。

## ✨ 功能特点

- **🔄 双模式转换**
  - **快速模式**：仅复制双 UUID 文件，适用于纯 UUID 替换场景
  - **完整模式**：深度转换 + 可选精简，完整保留游戏数据

- **📦 批量处理**
  - 一键扫描目录下所有世界存档
  - 并发处理（可配置最大并发数）
  - 实时进度显示与日志输出

- **🔗 可视化 UUID 映射编辑器**
  - 表格视图直观管理玩家名‑UUID 对应关系
  - 支持导入/导出（文本/CSV 格式）
  - 解决正版换号、离线改名等极端需求
  - 实时验证 UUID 格式，防止错误输入

- **⚙️ 智能配置**
  - 自动检测 Minecraft 版本（基于 level.dat）
  - 可选的存档清理（移除缓存、日志等无关文件）
  - 离线模式（不请求 Mojang API）
  - 多语言界面（简体中文、English）

- **🎨 现代化界面**
  - 基于 [Flet](https://flet.dev) 的深色主题
  - 响应式布局，支持窗口缩放
  - 终端风格日志输出，支持彩色标签

## 🚀 快速开始

### 环境要求
- Python 3.9 或更高版本
- Windows / macOS / Linux

### 安装步骤
```bash
git clone https://github.com/yourusername/mcsavehelper.git
cd mcsavehelper
pip install -r requirements.txt
python main.py
```

## 🧩 项目结构

```
mcsavehelper/
├── app/                         # 应用层（新架构）
│   ├── application.py           # 应用主协调器
│   ├── models/                  # 数据模型
│   │   ├── config.py
│   │   └── mapping.py
│   ├── services/                # 业务逻辑层
│   │   ├── config_service.py
│   │   ├── i18n_service.py
│   │   ├── migration_service.py
│   │   └── uuid_service.py
│   └── ui/                      # 用户界面
│       ├── theme.py             # 色彩/主题定义
│       ├── sidebar.py           # 侧边栏导航
│       ├── components/          # 可复用组件
│       │   ├── buttons.py
│       │   ├── cards.py
│       │   ├── fields.py
│       │   ├── log_panel.py
│       │   └── uuid_table.py
│       └── views/               # 页面视图
│           ├── migrator.py      # 批量迁移
│           ├── explorer.py      # 存档探险
│           ├── mappings.py      # 映射管理
│           └── settings.py      # 设置
├── core/                        # 核心领域逻辑
│   ├── batch_processor.py
│   ├── cleaner.py
│   ├── config.py
│   ├── constants.py
│   ├── converter.py
│   ├── fast_mode.py
│   ├── full_mode.py
│   ├── i18n.py
│   ├── logger.py
│   ├── nbt_utils.py
│   ├── pure_cleaner.py
│   ├── scanner.py
│   ├── types.py
│   ├── uuid_utils.py
│   ├── utils.py
│   ├── worker.py
│   └── omni/
│       └── world_session.py
├── translations/                # 多语言文件
│   ├── zh_CN.json
│   └── en_US.json
├── main.py                      # 程序入口
├── requirements.txt
└── pyproject.toml
```

## ⚙️ 架构说明

项目采用三层架构：

1. **模型层** (`app/models/`)：纯数据结构，无业务逻辑
2. **服务层** (`app/services/`)：封装 `core/` 的业务逻辑，为 UI 提供干净接口
3. **UI 层** (`app/ui/`)：Flet 组件和视图

`core/` 目录保持领域逻辑不变，`app/application.py` 作为应用主协调器连接所有层。

## 📄 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。

## 🙏 致谢

- [Flet](https://flet.dev) – 现代化 UI 框架
- [nbtlib](https://github.com/vberlier/nbtlib) – NBT 文件解析
- [anvil-parser2](https://github.com/TkTech/anvil-parser2) – 区块文件读取
- [Mojang API](https://api.mojang.com) – 正版 UUID 查询服务
