import argparse
from pathlib import Path
from typing import List, Optional

import pandas as pd

from BacktestEngine import run_backtest
from MetricsPlotter import run as run_metrics
from PortfolioManager import main as portfolio_main
from RiskFilter import RiskFilter

BASE_DIR = Path(__file__).parent


def read_codes_from_safe_top3(file_path: Path) -> List[str]:
    if not file_path.exists():
        return []

    df = pd.read_csv(file_path, dtype=str)
    candidates = [c for c in ["股票代码", "code", "代码"] if c in df.columns]
    if not candidates:
        return []

    col = candidates[0]
    codes = df[col].dropna().astype(str).str.strip()
    codes = codes[codes != ""]
    return codes.str.split(".").str[0].str.zfill(6).tolist()


def run_pipeline(
    skip_risk: bool,
    skip_backtest: bool,
    skip_portfolio: bool,
    skip_metrics: bool,
    account_csv: Path,
    benchmark_csv: Optional[Path],
) -> None:
    safe_top3_path = BASE_DIR / "safe_top3_stocks2.csv"

    if not skip_risk:
        try:
            rf = RiskFilter(
                db_path=str(BASE_DIR / "selected_events2.db"),
                json_file=str(BASE_DIR / "test2.json"),
                price_data_file=str(BASE_DIR / "日线数据.csv"),
            )
            rf.run()
        except Exception as exc:
            print(f"RiskFilter 运行失败，跳过后续风控，错误: {exc}")

    stock_codes = read_codes_from_safe_top3(safe_top3_path)
    if not stock_codes:
        stock_codes = ["600000", "000001", "002415"]
        print("safe_top3_stocks.csv 不存在或无代码，使用示例股票列表运行回测。")

    if not skip_backtest:
        try:
            run_backtest(stock_codes, export_dir=r"e:\量化项目\股票数据\export")
        except Exception as exc:
            print(f"BacktestEngine 运行失败，错误: {exc}")

    if not skip_portfolio:
        try:
            portfolio_main()
        except Exception as exc:
            print(f"PortfolioManager 运行失败，错误: {exc}")

    if not skip_metrics:
        try:
            run_metrics(account_csv=account_csv, benchmark_csv=benchmark_csv)
        except Exception as exc:
            print(f"MetricsPlotter 运行失败，错误: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="串联阶段三任务的简易主入口")
    parser.add_argument("--skip-risk", action="store_true", help="跳过任务1 风控过滤")
    parser.add_argument("--skip-backtest", action="store_true", help="跳过任务2 回测")
    parser.add_argument("--skip-portfolio", action="store_true", help="跳过任务3 资金曲线计算")
    parser.add_argument("--skip-metrics", action="store_true", help="跳过任务5 指标与绘图")
    parser.add_argument("--account-csv", default=str(BASE_DIR / "result/account_value.csv"), help="任务3输出的资金曲线文件路径")
    parser.add_argument("--benchmark-csv", default=None, help="沪深300基准数据文件路径，包含 date 和 close 列")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    benchmark_csv = Path(args.benchmark_csv) if args.benchmark_csv else None
    run_pipeline(
        skip_risk=args.skip_risk,
        skip_backtest=args.skip_backtest,
        skip_portfolio=args.skip_portfolio,
        skip_metrics=args.skip_metrics,
        account_csv=Path(args.account_csv),
        benchmark_csv=benchmark_csv,
    )


if __name__ == "__main__":
    main()
