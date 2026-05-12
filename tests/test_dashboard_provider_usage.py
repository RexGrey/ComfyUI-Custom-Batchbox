"""Tests for provider/key usage aggregation in dashboard.py."""

from dashboard import DASHBOARD_HTML, compute_stats


def test_compute_stats_provider_usage_is_additive_to_existing_totals():
    records = [
        {
            "ts": "2026-05-12T10:00:00+08:00",
            "machine": "PC-1_AAAAAA",
            "node": "image",
            "model": "NanoBananaPro",
            "batch": 2,
            "gen": 2,
            "saved": 2,
            "ok": True,
            "providers": ["google"],
            "provider_usage": [
                {
                    "provider": "google",
                    "provider_label": "Google",
                    "key_label": "main · ****abcdef",
                    "gen": 2,
                }
            ],
        },
        {
            "ts": "2026-05-12T10:01:00+08:00",
            "machine": "PC-2_BBBBBB",
            "node": "image",
            "model": "NanoBananaPro",
            "batch": 1,
            "gen": 1,
            "saved": 1,
            "ok": True,
            "providers": ["google"],
            "provider_usage": [
                {
                    "provider": "google",
                    "provider_label": "Google",
                    "key_label": "backup · ****123456",
                    "gen": 1,
                }
            ],
        },
        {
            "ts": "2026-05-12T10:02:00+08:00",
            "machine": "PC-3_CCCCCC",
            "node": "image",
            "model": "OldModel",
            "batch": 3,
            "gen": 3,
            "saved": 3,
            "ok": True,
            "providers": [],
        },
    ]

    stats = compute_stats(records, date_filter="today")

    assert stats["total_generated"] == 6
    assert stats["models"] == {"NanoBananaPro": 2, "OldModel": 1}
    assert stats["providers_usage"] == [
        {
            "provider": "google",
            "provider_label": "Google",
            "gen": 3,
            "keys": [
                {"key_label": "main · ****abcdef", "gen": 2},
                {"key_label": "backup · ****123456", "gen": 1},
            ],
        }
    ]


def test_dashboard_has_provider_usage_as_top_level_tab():
    assert "switchTab('providers')" in DASHBOARD_HTML
    assert "供应商/API数量详情" in DASHBOARD_HTML
    assert 'id="page-providers"' in DASHBOARD_HTML

    overview_start = DASHBOARD_HTML.index('id="page-overview"')
    machines_start = DASHBOARD_HTML.index('id="page-machines"')
    providers_start = DASHBOARD_HTML.index('id="page-providers"')
    provider_list = DASHBOARD_HTML.index('id="providerUsageList"')

    assert overview_start < machines_start < providers_start
    assert provider_list > providers_start


def test_provider_page_shows_chart_before_key_blocks():
    assert 'id="providerChart"' in DASHBOARD_HTML
    assert "let chartProvider" in DASHBOARD_HTML
    assert "renderProviderChart(items);" in DASHBOARD_HTML

    providers_start = DASHBOARD_HTML.index('id="page-providers"')
    chart_start = DASHBOARD_HTML.index('id="providerChart"')
    list_start = DASHBOARD_HTML.index('id="providerUsageList"')

    assert providers_start < chart_start < list_start


def test_recent_activity_table_has_provider_column():
    table_start = DASHBOARD_HTML.index('id="recentTable"')
    header_end = DASHBOARD_HTML.index("</thead>", table_start)
    header_html = DASHBOARD_HTML[table_start:header_end]

    assert "<th>供应商</th>" in header_html
    assert "providerSummary(r)" in DASHBOARD_HTML
