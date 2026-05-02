import pandas as pd
import sqlite3
import math
from pathlib import Path

# =====================
# 参数配置
# =====================
INITIAL_CAPITAL = 100000
WEIGHTS = [0.5, 0.3, 0.2]

TOP_STOCKS_FILE = "safe_top3_stocks.csv"
TRADE_LOG_FILE = "weekly_trade_log.csv"
BASE_DIR = Path(__file__).parent
DB_FILE = BASE_DIR / "structured_events.db"

RESULT_XLSX = "result/result.xlsx"
ACCOUNT_CSV = "result/account_value.csv"

GROUP_SIZE = 3

# =====================
# 工具函数
# =====================
def normalize_code(code):
    return str(code).split('.')[0].zfill(6)

# =====================
# 读取数据
# =====================
def load_data():
    top_stocks = pd.read_csv(TOP_STOCKS_FILE, dtype={'股票代码': str})
    trade_log = pd.read_csv(TRADE_LOG_FILE, dtype={'股票代码': str})

    # ✅ 股票代码统一格式
    top_stocks['股票代码'] = top_stocks['股票代码'].apply(normalize_code)
    trade_log['股票代码'] = trade_log['股票代码'].apply(normalize_code)

    # ✅ 日期转 datetime（关键）
    trade_log['周起始日'] = pd.to_datetime(trade_log['周起始日'])
    trade_log['周五日期'] = pd.to_datetime(trade_log['周五日期'])

    # ✅ 按时间排序
    trade_log = trade_log.sort_values('周起始日')

    return top_stocks, trade_log


# =====================
# 事件映射
# =====================
def get_event_mapping():
    """Load event mapping; tolerate missing DB file by returning an empty map."""
    if not DB_FILE.exists():
        print(f"提示: 找不到数据库文件 {DB_FILE}，将使用空事件映射继续运行。")
        return {}

    try:
        conn = sqlite3.connect(DB_FILE)
        query = "SELECT event_id, news_title FROM event_stocks"
        df = pd.read_sql(query, conn)
        conn.close()
        return dict(zip(df['event_id'], df['news_title']))
    except Exception as exc:
        print(f"读取数据库失败({exc})，使用空事件映射继续运行。")
        return {}


# =====================
# 单周计算
# =====================
def calculate_week(capital, week_stocks, trade_log, event_map, week_start):
    results = []
    total_value = 0

    for i, row in week_stocks.iterrows():
        stock_code = row['股票代码']
        event_id = row['对应事件ID']
        weight = WEIGHTS[i]

        allocated = capital * weight

        # ✅ 用“周起始日 + 股票代码”匹配
        ret_row = trade_log[
            (trade_log['股票代码'] == stock_code) &
            (trade_log['周起始日'] == week_start)
        ]

        if ret_row.empty:
            print("DEBUG信息：")
            print("周起始日:", week_start)
            print("股票:", stock_code)
            print("该股票所有记录：")
            print(trade_log[trade_log['股票代码'] == stock_code])
            raise ValueError(f"{week_start} 找不到股票 {stock_code} 的收益率")

        weekly_return = ret_row.iloc[0]['周收益率']

        final_value = allocated * (1 + weekly_return)
        total_value += final_value

        results.append({
            '周起始日': week_start.strftime('%Y-%m-%d'),
            '事件名': event_map.get(event_id, 'UNKNOWN'),
            '股票代码': stock_code,
            '资金比例': weight
        })

    return total_value, pd.DataFrame(results)


# =====================
# 主流程
# =====================
def main():
    top_stocks, trade_log = load_data()
    event_map = get_event_mapping()

    # ✅ 提取所有“周”（按时间顺序）
    weeks = trade_log['周起始日'].drop_duplicates().tolist()

    capital = INITIAL_CAPITAL

    all_results = []
    account_records = []

    #total_groups = math.floor(len(top_stocks) / GROUP_SIZE)

    total_groups = min(
        math.floor(len(top_stocks) / GROUP_SIZE),
        len(weeks)
    )

    # ⚠️ 防止股票组数 > 周数
    if total_groups > len(weeks):
        raise ValueError("股票组数超过可用周数，请检查数据")

    for i in range(total_groups):
        start = i * GROUP_SIZE
        end = start + GROUP_SIZE

        week_stocks = top_stocks.iloc[start:end].reset_index(drop=True)
        week_start = weeks[i]

        capital, result_df = calculate_week(
            capital,
            week_stocks,
            trade_log,
            event_map,
            week_start
        )

        all_results.append(result_df)

        account_records.append({
            'week': week_start.strftime('%Y-%m-%d'),
            'account_value': capital
        })

    # =====================
    # 输出
    # =====================
    final_result_df = pd.concat(all_results, ignore_index=True)
    account_df = pd.DataFrame(account_records)

    final_result_df.to_excel(RESULT_XLSX, index=False)
    account_df.to_csv(ACCOUNT_CSV, index=False)

    print("运行完成！")
    print(account_df)


if __name__ == "__main__":
    main()