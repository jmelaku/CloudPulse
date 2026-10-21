from tools.e2e_benchmark import percentile


def test_percentile_uses_sorted_latency_values():
    assert percentile([0.3, 0.1, 0.2], 0.50) == 0.2
    assert percentile([0.3, 0.1, 0.2], 0.95) == 0.2
