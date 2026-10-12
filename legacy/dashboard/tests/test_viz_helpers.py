from __future__ import annotations

from dashboard.viz_helpers import chart_download_filename


def test_chart_download_filename_uses_title() -> None:
    name = chart_download_filename("2017 年 GMV", "/tmp/viz_abc.png")
    assert name == "2017_年_GMV.png"


def test_chart_download_filename_strips_unsafe_chars() -> None:
    name = chart_download_filename('a/b:c*d?"e', "/tmp/chart.png")
    assert name == "a_b_c_d_e.png"
    assert "/" not in name
    assert ":" not in name


def test_chart_download_filename_falls_back_to_stem() -> None:
    name = chart_download_filename("   ", "/tmp/state_trend.png")
    assert name == "state_trend.png"


def test_chart_download_filename_keeps_known_suffix() -> None:
    name = chart_download_filename("热力图", "/tmp/heat.jpg")
    assert name.endswith(".jpg")
    assert name.startswith("热力图")
