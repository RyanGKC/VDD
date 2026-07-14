import pytest
pytest.main(["tests/test_resilience_loop.py::test_malformed_json_is_skipped", "-v", "-s"])
