"""Migration task orchestration for the application."""
import os
import threading
from typing import Any


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
                app.warn_dialog(
                    app._t("dialogs.warning", "提示"),
                    app._t("messages.please_select_source", "请先选择客户端存档目录"),
                )
                return

            app._start_btn.disabled = True
            app.page.update()

            self.save_config()

            dest_dir = mc.dest_path or os.getcwd()

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
            app._start_btn.disabled = False
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
        c._config["version_detection"] = mc.version_detection
        c._config.setdefault("batch_processing", {})["max_concurrent"] = c.max_concurrent
        c._config["custom_uuid_mappings"] = c.custom_uuid_mappings
        c._config["use_custom_mapping"] = c.use_custom_mapping
        c.save()

    def run_single_thread(self, dest_dir: str) -> None:
        """Run a single-world migration in the current worker thread."""
        app = self.app
        mc = app.config.migration
        try:
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
            app.log_header(app._t("messages.migration_complete", "迁移完成"))
            app.log(app._t("messages.migration_success", "迁移完成！输出目录: {output_path}",
                           output_path=output_path), "SUCCESS")
            app._progress_label.value = app._t("top_bar.completed", "已完成")
            app.info_dialog(
                app._t("dialogs.success", "成功"),
                app._t("messages.migration_success", "迁移完成！输出目录: {output_path}",
                       output_path=output_path),
            )
        except Exception as e:
            app.handle_exception(
                e,
                title=app._t("messages.migration_exception", "迁移失败: {error}", error=str(e)),
                log=True,
                show_dialog=False,
            )
            app._progress_label.value = app._t("top_bar.failed", "失败")
            app.error_dialog(
                app._t("dialogs.error", "错误"),
                app._t("messages.migration_exception", "迁移失败: {error}", error=str(e)),
                exception=e,
                show_details=True,
            )
        finally:
            app._start_btn.disabled = False
            app._progress_bar.value = 0
            self.try_update_page()

    def run_batch_thread(self, dest_dir: str) -> None:
        """Run batch migration in the current worker thread."""
        app = self.app
        mc = app.config.migration
        try:
            app.log_header(app._t("messages.batch_migration_started", "开始批量处理"))
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
            app.log_header(app._t("messages.batch_migration_complete_header", "批量处理完成"))
            app.log(app._t("messages.batch_migration_complete",
                           "成功: {success}/{total}",
                           success=success, total=len(results)), "SUCCESS")
            app._progress_label.value = app._t("top_bar.batch_completed", "批量处理完成")
        except Exception as e:
            app.handle_exception(
                e,
                title=app._t("messages.save_failed", "批量处理失败: {error}", error=str(e)),
                log=True,
                show_dialog=False,
            )
            app._progress_label.value = app._t("top_bar.batch_failed", "批量处理失败")
        finally:
            app._start_btn.disabled = False
            app._progress_bar.value = 0
            self.try_update_page()

    def open_folder(self, path: str) -> None:
        """Open a folder in the platform file manager."""
        self.app.migration.open_folder(path)
