from src.cli import discover_pairs


def test_discover_pairs_finds_the_committed_sample_pairs():
    pairs = discover_pairs()
    labels = [label for label, _, _ in pairs]
    assert any("pair_01_lift_gas_compressor (native PDF)" in l for l in labels)
    assert any("pair_01_lift_gas_compressor (scanned PDF" in l for l in labels)
    assert any("pair_02_dxf_sample (DXF)" in l for l in labels)


def test_discover_pairs_only_returns_paths_that_exist():
    for _, path_a, path_b in discover_pairs():
        assert path_a.exists()
        assert path_b.exists()
