"""Migration task orchestration for the application."""
import os
import threading
from typing import Any

# 导入性能监控和反馈工具
from app.ui.performance import Timer, async_tracker


class MigrationController:
    """Coordinates single and batch migration jobs for the UI application."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def sync_config_to_migration(self) -> None:
        """Synchronize persisted config values into runtime migration config."""
        mc = self.app.config.migration
        mc.version_detection = self.app.config.version_detection

    def start(self) -> None:
        """Start the currently configured migration task."""
        app = self.app
        try:
            mc = app.config.migration

            if not mc.src_path and not mc.batch_mode:
                app.warn_dialog(app._t("dialogs.warning", "提示"), app._t(
                    "messages.please_select_source", "请先通过侧边栏设置客户端存档目录"), )
                return

            app.set_start_button_enabled(False)
            app.page.update()

            self.save_config()

            dest_dir = mc.dest_path or os.getcwd()

            # 开始跟踪异步操作
            operation_id = "migration_batch" if mc.batch_mode else "migration_single"
            async_tracker.start(operation_id)

            if mc.batch_mode and app.migration.batch_worlds:
                threading.Thread(
                    target=self.run_batch_thread,
                    args=(dest_dir,), daemon=True,
                ).start()
            else:
                threading.Thread(
                    target=self.run_single_thread,
                    args=(dest_dir,), daemon=True,
                ).start()
        except Exception as e:
            app.handle_exception(e, title="启动转换失败")
            app.set_start_button_enabled(True)
            self.try_update_page()

    def try_update_page(self) -> None:
        """Update the Flet page, ignoring lifecycle errors."""
        try:
            self.app.page.update()
        except Exception:
            pass

    def save_config(self) -> None:
        """Save current migration-related configuration."""
        c = self.app.config
        mc = c.migration
        # 使用线程安全的批量更新方法
        c.update_batch_config(
            version_detection=mc.version_detection,
            max_concurrent=c.max_concurrent,
            custom_uuid_mappings=c.custom_uuid_mappings,
            use_custom_mapping=c.use_custom_mapping,
        )

    def run_single_thread(self, dest_dir: str) -> None:
        """Run a single-world migration in the current worker thread."""
        app = self.app
        mc = app.config.migration

        try:
            with Timer("single_migration"):
                app.log_header(app._t("messages.migration_started", "开始迁移任务"))
                output_path = app.migration.run_single(
                    src=mc.src_path,
                    dest=dest_dir,
                    world_name=mc.world_name,
                    mode=mc.mode,
                    offline=mc.offline_mode,
                    clean=mc.clean_mode,
                    pure_clean=mc.pure_clean_mode,
                    target_platform=mc.target_platform,
                    target_version=mc.target_version,
                    manual_names_str=mc.manual_names,
                    log_cb=app.log,
                    progress_cb=app.update_progress,
                )

            elapsed = async_tracker.complete("migration_single")
            if elapsed:
                app.log(f"迁移耗时: {elapsed:.2f}秒", "INFO")

            app.log_header(app._t("messages.migration_complete", "迁移完成"))
            app.log(
                app._t(
                    "messages.migration_success",
                    "迁移完成！输出目录: {output_path}",
                    output_path=output_path),
                "SUCCESS")
            app.set_progress_label(app._t("top_bar.completed", "已完成"))

            if hasattr(
                    app,
                    "notification_manager") and app.notification_manager:
                app.notification_manager.show_success(
                    f"迁移完成！输出目录: {output_path}")
            else:
                app.info_dialog(
                    app._t(
                        "dialogs.success",
                        "成功"),
                    app._t(
                        "messages.migration_success",
                        "迁移完成！输出目录: {output_path}",
                        output_path=output_path),
                )
        except Exception as e:
            async_tracker.complete("migration_single")
            app.handle_exception(
                e,
                title=app._t(
                    "messages.migration_exception",
                    "迁移失败: {error}",
                    error=str(e)),
                log=True,
                show_dialog=False,
            )
            app.set_progress_label(app._t("top_bar.failed", "失败"))
            app.error_dialog(
                app._t(
                    "dialogs.error",
                    "错误"),
                app._t(
                    "messages.migration_exception",
                    "迁移失败: {error}",
                    error=str(e)),
                exception=e,
                show_details=True,
            )
        finally:
            app.set_start_button_enabled(True)
            app.set_progress_value(0)
            self.try_update_page()

    def run_batch_thread(self, dest_dir: str) -> None:
        """Run batch migration in the current worker thread."""
        app = self.app
        mc = app.config.migration
        try:
            app.log_header(
                app._t(
                    "messages.batch_migration_started",
                    "开始批量处理"))
            self.save_config()
            results = app.migration.run_batch(
                dest_dir=dest_dir,
                mode=mc.mode,
                offline=mc.offline_mode,
                clean=mc.clean_mode,
                pure_clean=mc.pure_clean_mode,
                target_platform=mc.target_platform,
                target_version=mc.target_version,
                manual_names_str=mc.manual_names,
                max_concurrent=app.config.max_concurrent,
                log_cb=app.log,
                progress_cb=app.update_progress,
            )
            success = sum(1 for r in results.values() if r["success"])
            app.log_header(
                app._t(
                    "messages.batch_migration_complete_header",
                    "批量处理完成"))
            app.log(app._t("messages.batch_migration_complete",
                           "成功: {success}/{total}",
                           success=success, total=len(results)), "SUCCESS")
            app.set_progress_label(app._t("top_bar.batch_completed", "批量处理完成"))
        except Exception as e:
            app.handle_exception(
                e,
                title=app._t(
                    "messages.save_failed",
                    "批量处理失败: {error}",
                    error=str(e)),
                log=True,
                show_dialog=False,
            )
            app.set_progress_label(app._t("top_bar.batch_failed", "批量处理失败"))
        finally:
            app.set_start_button_enabled(True)
            app.set_progress_value(0)
            self.try_update_page()

    def open_folder(self, path: str) -> None:
        """Open a folder in the platform file manager."""
        self.app.migration.open_folder(path)
