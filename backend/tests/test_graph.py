import pytest

from app.graph import graph_cloud


def test_us_government_cloud_uses_gcc_high_endpoint() -> None:
    cloud = graph_cloud("usgovernment")
    assert cloud.base_url == "https://graph.microsoft.us"
    assert cloud.scope == "https://graph.microsoft.us/.default"


def test_unknown_cloud_is_rejected() -> None:
    with pytest.raises(ValueError):
        graph_cloud("unknown")
