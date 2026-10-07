import asyncio
import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parent.parent / "scripts" / "bench.py"
    spec = importlib.util.spec_from_file_location("bench_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bench_runs_every_scenario_offline():
    """Смоук: бенч на крошечной БД проходит все команды, не трогая сеть, и восстанавливает service.refresh_only."""
    from mmrbot import service

    bench = _load()
    original = service.refresh_only
    rows = asyncio.run(bench.run_bench(players=2, matches=12, repeats=2))
    assert service.refresh_only is original
    names = [name for name, _, _ in rows]
    assert {"/stats", "/week", "/graph", "/player"} <= set(names)
    assert all(p50 >= 0 and p95 >= p50 for _, p50, p95 in rows)
