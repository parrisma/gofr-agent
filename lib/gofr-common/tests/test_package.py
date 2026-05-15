"""Basic tests for gofr_common package."""



def test_import_gofr_common():
    """Test that gofr_common can be imported."""
    import gofr_common

    assert hasattr(gofr_common, "__version__")
    assert gofr_common.__version__ == "1.0.0"


def test_version_format():
    """Test that version follows semver format."""
    import gofr_common

    parts = gofr_common.__version__.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)
