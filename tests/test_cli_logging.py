"""CLI diagnostics preserve streams and leave host logging configuration intact."""

import logging

import pytest

from jgrad_admission_rag.cli_logging import cli_diagnostics


def test_cli_diagnostics_use_warning_default_and_restore_configuration(capsys):
    logger = logging.getLogger("test.jgrad.cli-diagnostics")
    original = (logger.level, logger.propagate, logger.handlers[:])
    with pytest.raises(RuntimeError), cli_diagnostics(logger):
        logger.info("not a CLI diagnostic")
        logger.warning("警告")
        logger.error("configuration error: invalid")
        raise RuntimeError("restore even after failure")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "警告\nconfiguration error: invalid\n"
    assert (logger.level, logger.propagate, logger.handlers) == original


def test_repeated_cli_diagnostics_do_not_duplicate_or_keep_old_stream(capsys):
    logger = logging.getLogger("test.jgrad.repeated-cli-diagnostics")
    for _ in range(2):
        with cli_diagnostics(logger):
            logger.error("same error")
        assert capsys.readouterr().err == "same error\n"
