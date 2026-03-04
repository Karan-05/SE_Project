from datetime import date, timedelta

from automation import Automation


def test_month_windows_cover_entire_year(tmp_path):
    automation = Automation(
        year=2023,
        status="Completed",
        storage_directory=tmp_path,
        track="Dev",
    )

    windows = automation.month_windows()

    assert len(windows) == 12
    assert windows[0].start == date(2023, 1, 1)
    assert windows[-1].end == date(2023, 12, 31)

    for current, nxt in zip(windows, windows[1:]):
        assert current.end + timedelta(days=1) == nxt.start
