from core.performance import PerfTracker


def test_perf_tracker_publishes_metrics_without_ui_dependency() -> None:
    published = []
    tracker = PerfTracker(metrics_sink=published.append)

    with tracker.track("scan", {"dimension": "overworld"}):
        tracker.increment_files(2)
        tracker.increment_bytes(1024)

    assert len(published) == 1
    assert published[0].operation == "scan"
    assert published[0].files_processed == 2
    assert published[0].bytes_processed == 1024
