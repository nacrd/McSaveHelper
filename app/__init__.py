"""MCSaveHelper Application Layer

架构分层：
  - models/   : 数据模型（纯数据结构，无业务逻辑）
  - services/ : 服务层（封装 core/ 的业务逻辑，提供干净接口）
  - ui/       : 用户界面（Flet 组件和视图）
  - application.py : 应用核心（状态管理、视图协调、初始化）
"""
