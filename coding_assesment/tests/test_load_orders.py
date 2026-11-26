"""Loader tests. Hermetic: the engine is a mock, no database."""

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy import Engine

from app.cleaning import CLEAN_COLUMNS
from scripts import load_orders
from scripts.load_orders import EmptyLoadError, load_clean_orders

HEADER = "date,customer,country,product,amount,status\n"
VALID_ROW = "2025-03-01,Ana Garcia,Spain,Laptop,1200.50,completed\n"
INVALID_ROW = "bad,,Atlantis,,x,zzz\n"


def _args(tmp_path: Path, csv_text: str) -> list[str]:
    source = tmp_path / "raw.csv"
    source.write_text(csv_text, encoding="utf-8")
    return ["--input", str(source), "--rejects", str(tmp_path / "rejects.csv")]


def test_empty_clean_set_never_touches_the_database() -> None:
    engine = MagicMock(spec=Engine)

    with pytest.raises(EmptyLoadError):
        load_clean_orders(engine, pd.DataFrame(columns=list(CLEAN_COLUMNS)))

    engine.begin.assert_not_called()


@pytest.mark.parametrize("csv_text", [HEADER, HEADER + INVALID_ROW])
def test_main_refuses_to_load_when_nothing_is_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, csv_text: str
) -> None:
    monkeypatch.setattr(load_orders, "create_engine_from_env", lambda var: MagicMock())

    with pytest.raises(SystemExit) as exc:
        load_orders.main(_args(tmp_path, csv_text))

    assert "no valid rows" in str(exc.value)


def test_main_reports_a_run_with_zero_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(load_orders, "create_engine_from_env", lambda var: MagicMock())
    monkeypatch.setattr(load_orders, "load_clean_orders", lambda engine, clean: 1)

    load_orders.main(_args(tmp_path, HEADER + VALID_ROW))

    out = capsys.readouterr().out
    assert "rejected: 0" in out
    assert "loaded:   1" in out
