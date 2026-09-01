import sys

from reader_app.cli import main


def test_main_reports_version(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["reader-app", "--version"])
    assert main() == 0
    assert capsys.readouterr().out == "Reader App 0.1.0\n"
