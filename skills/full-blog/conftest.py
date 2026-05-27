def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks integration tests (deselect with '-m \"not integration\"')")
