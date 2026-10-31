from logging.handlers import RotatingFileHandler

from src.logging_setup import setup_logging


def test_setup_logging_creates_file_and_is_idempotent(tmp_path):
    log1 = setup_logging(log_dir=tmp_path, force=True)
    log2 = setup_logging(log_dir=tmp_path)
    assert log1 is log2
    log1.debug("hello")
    for h in log1.handlers:
        h.flush()
    assert "hello" in (tmp_path / "app.log").read_text()
    assert len([h for h in log1.handlers if isinstance(h, RotatingFileHandler)]) == 1
