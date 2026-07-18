from app.ui.application_shell import build_tab_definitions


def test_build_tab_definitions_keeps_stable_view_order() -> None:
    calls = []

    def translate(key: str, default: str) -> str:
        calls.append((key, default))
        return f"translated:{default}"

    tabs = build_tab_definitions(translate)

    assert [tab["id"] for tab in tabs] == [
        "explorer",
        "migrator",
        "save_repair",
        "backup_center",
        "map_export",
        "compare",
        "mappings",
        "server_properties",
        "settings",
    ]
    assert tabs[0]["label"] == "translated:存档浏览器"
    assert calls[-1] == ("sidebar.settings", "设置")
