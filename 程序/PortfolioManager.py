import pandas as pd
import sqlite3
import math
from pathlib import Path

# =====================
# 参数配置
# =====================
INITIAL_CAPITAL = 100000
WEIGHTS = [0.5, 0.3, 0.2]

BASE_DIR = Path(__file__).parent
TOP_STOCKS_FILE = BASE_DIR / "safe_top3_stocks.csv"
TRADE_LOG_FILE = BASE_DIR / "weekly_trade_log.csv"
DB_FILE = BASE_DIR / "structured_events.db"

RESULT_XLSX = BASE_DIR / "result" / "result.xlsx"
ACCOUNT_CSV = BASE_DIR / "result" / "account_value.csv"

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

    # ✅ 按时间排序并根据题目要求精确定位2025年12月8日到2025年12月26日
    trade_log = trade_log.sort_values('周起始日')
    trade_log = trade_log[
        (trade_log['周起始日'] >= '2025-12-08') & 
        (trade_log['周五日期'] <= '2025-12-26')
    ].copy()
    
    # 单独分析每只股票在给定时间范围内的累计收益率
    print("\n--- 【2025年12月8日 至 2025年12月26日】单只股票累计收益率分析 ---")
    for stock_code in top_stocks['股票代码']:
        stock_data = trade_log[trade_log['股票代码'] == stock_code]
        if not stock_data.empty:
            # 累乘所有周的 (1 + 收益率) 得到总净值，减1即为累计收益率
            cumulative_return = (1 + stock_data['周收益率']).prod() - 1
            print(f"股票 {stock_code} 累计周收益率: {cumulative_return:.2%}")
        else:
            print(f"股票 {stock_code} 在该维段内无交易记录")
    print("------------------------------------------\n")

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
            '时间窗口': week_start.strftime('%Y-%m-%d'),
            '周二买入日期': ret_row.iloc[0]['周二日期'].strftime('%Y-%m-%d') if isinstance(ret_row.iloc[0]['周二日期'], pd.Timestamp) else ret_row.iloc[0]['周二日期'],
            '周五卖出日期': ret_row.iloc[0]['周五日期'].strftime('%Y-%m-%d') if isinstance(ret_row.iloc[0]['周五日期'], pd.Timestamp) else ret_row.iloc[0]['周五日期'],
            '事件名': row['事件标题'] if '事件标题' in row else 'UNKNOWN',
            '股票名称': row['股票名称'] if '股票名称' in row else 'UNKNOWN',
            '股票代码': stock_code,
            '资金分配比例': f"{int(weight*100)}%",
            '当周收益率': f"{weekly_return:.2%}",
            '期末资金': round(final_value, 2)
        })

    return total_value, pd.DataFrame(results)


# =====================
# 主流程
# =====================
def main():
    top_stocks, trade_log = load_data()
    event_map = get_event_mapping()

    # ✅ 提取所有“周”（按时间顺序）
    weeks = sorted(trade_log['周起始日'].drop_duplicates().tolist())

    capital = INITIAL_CAPITAL

    all_results = []
    account_records = []

    # Use the same 3 stocks for all weeks
    week_stocks = top_stocks

    if not weeks:
        print("未找到符合时间窗口（2025-12-08 至 2025-12-26）的记录！")
        return

    account_records.append({
        'week': (weeks[0] - pd.Timedelta(days=7)).strftime('%Y-%m-%d'),
        'account_value': capital
    })

    for week_start in weeks:
        # Check if all 3 stocks have data for this week
        valid = True
        for stock_code in week_stocks['股票代码']:
            if trade_log[(trade_log['股票代码'] == stock_code) & (trade_log['周起始日'] == week_start)].empty:
                valid = False
                break
        
        if not valid:
            continue
            
        try:
            capital_new, result_df = calculate_week(
                capital,
                week_stocks,
                trade_log,
                event_map,
                week_start
            )
            capital = capital_new
            
            all_results.append(result_df)
            account_records.append({
                'week': week_start.strftime('%Y-%m-%d'),
                'account_value': capital
            })
        except ValueError as e:
            print(e)
            continue

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