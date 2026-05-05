import pandas as pd
import os
import glob
from datetime import datetime, timedelta

def calculate_weekly_returns(df, code):
    """
    计算单个股票的周收益率
    逻辑：周二开盘买入，周五收盘卖出
    """
    weekly_results = []
    
    # 添加周标识 (Monday of the week)
    df['Week_Start'] = df['Date'].apply(lambda x: x - timedelta(days=x.weekday()))
    # Normalize to date object for grouping if needed, but keeping as timestamp is fine for arithmetic
    
    # Group by Week using Week_Start
    # Note: df['Week_Start'] allows us to group all days of the same week together
    unique_weeks = df['Week_Start'].unique()
    
    # Optimization: Iterate over groups instead of unique values to avoid repeated filtering
    for week_start, group in df.groupby('Week_Start'):
        # Target dates
        target_tuesday = week_start + timedelta(days=1)
        target_friday = week_start + timedelta(days=4)
        
        # Check if we have data for Tuesday and Friday
        # group['Date'] are timestamps
        tuesday_data = group[group['Date'].dt.date == target_tuesday.date()]
        friday_data = group[group['Date'].dt.date == target_friday.date()]
        
        if tuesday_data.empty or friday_data.empty:
            continue
            
        tuesday_open = tuesday_data.iloc[0]['Open']
        friday_close = friday_data.iloc[0]['Close']
        
        # Calculate return
        if tuesday_open == 0:
            weekly_return = 0
        else:
            weekly_return = (friday_close - tuesday_open) / tuesday_open
        
        weekly_results.append({
            '股票代码': code,
            '周起始日': week_start.date(),
            '周二日期': target_tuesday.date(),
            '周二开盘价': tuesday_open,
            '周五日期': target_friday.date(),
            '周五收盘价': friday_close,
            '周收益率': weekly_return
        })
        
    return weekly_results

def run_backtest(codes=None, export_dir="data"):
    """
    改为从 日线数据.csv 中读取所需代码的数据进行回测。
    Saves to weekly_trade_log.csv for downstream use.
    """
    all_results = []
    daily_csv = "日线数据.csv"
    
    if not os.path.exists(daily_csv):
        # 尝试加上当前文件目录
        daily_csv = os.path.join(os.path.dirname(__file__), "日线数据.csv")
        
    print(f"从 {daily_csv} 读取日线数据...")
    if not os.path.exists(daily_csv):
        print(f"找不到日线数据文件: {daily_csv}")
        return

    codes_set = set()
    if codes:
        codes_set = {c.split('.')[-1].zfill(6) for c in codes}

    # 读取大型CSV时，可以只加载我们需要的列
    cols_to_use = ['代码', '日期', '开盘', '收盘']
    try:
        df_all = pd.read_csv(daily_csv, usecols=cols_to_use, encoding='utf-8')
    except Exception as e:
        df_all = pd.read_csv(daily_csv, usecols=cols_to_use, encoding='gbk')

    # 填充前面的0，确保都是6位代码
    df_all['代码'] = df_all['代码'].astype(str).str.zfill(6)
    
    if codes:
        df_all = df_all[df_all['代码'].isin(codes_set)]
        
    unique_codes = df_all['代码'].unique()
    print(f"共发现 {len(unique_codes)} 个要回测的股票")

    for i, code in enumerate(unique_codes):
        print(f"正在处理: {code} ({i+1}/{len(unique_codes)})", flush=True)
            
        try:
            df = df_all[df_all['代码'] == code].copy()
            df = df[['日期', '开盘', '收盘']].copy()
            df.columns = ['Date', 'Open', 'Close']
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            df.dropna(subset=['Date'], inplace=True)
            
            if df.empty:
                continue
                
            df['Stock_Code'] = code
            df.sort_values('Date', inplace=True)
            
            results = calculate_weekly_returns(df, code)
            all_results.extend(results)
            
        except Exception as e:
            print(f"处理 {code} 时出错: {e}")
            continue

    print(f"\n处理完成。共生成 {len(all_results)} 条交易记录。")
    
    output_file = 'weekly_trade_log.csv'
    if all_results:
        results_df = pd.DataFrame(all_results)
        results_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"结果已保存至 {output_file}")
    else:
        print("没有生成任何交易记录，创建空的文件以避免报错。")
        pd.DataFrame(columns=['股票代码', '周起始日', '周二日期', '周二开盘价', '周五日期', '周五收盘价', '周收益率']).to_csv(output_file, index=False, encoding='utf-8-sig')

if __name__ == "__main__":
    # 定义 export 目录路径
    export_dir = "E:\desktop\泰迪杯\阶段三\export"
    
    if os.path.exists(export_dir):
        print(f"开始从 {export_dir} 读取数据并回测...")
        run_backtest(export_dir)
    else:
        print(f"目录不存在: {export_dir}")
