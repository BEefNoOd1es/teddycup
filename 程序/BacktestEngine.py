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
    Process .txt files in export_dir. If codes is provided (list of stock codes),
    only process matching files. Saves to weekly_trade_log.csv for downstream use.
    """
    all_results = []
    files = glob.glob(os.path.join(export_dir, "*.txt"))
    if codes:
        codes_set = {c.split('.')[-1].zfill(6) for c in codes}
        files = [f for f in files if any(code in os.path.basename(f) for code in codes_set)]

    print(f"在 {export_dir} 发现 {len(files)} 个文件。")
    
    for i, file_path in enumerate(files):
        filename = os.path.basename(file_path)
        print(f"正在处理: {filename} ({i+1}/{len(files)})", flush=True)
            
        try:
            # 解析文件名获取代码
            if '#' in filename:
                code = filename.split('#')[1].split('.')[0]
            else:
                code = filename.split('.')[0]
                
            # 若指定了 codes，仅处理匹配的代码
            if codes and code not in codes_set:
                continue

            # 读取数据
            df = pd.read_csv(file_path, skiprows=2, encoding='gbk', sep=r'\s+', header=None, on_bad_lines='skip', engine='python')
            if df.shape[1] < 5:
                df = pd.read_csv(file_path, skiprows=3, encoding='gbk', sep=r'\s+', header=None, on_bad_lines='skip', engine='python')
            
            if df.shape[1] < 5:
                continue
                
            df = df.iloc[:, [0, 1, 4]]
            df.columns = ['Date', 'Open', 'Close']
            df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
            df.dropna(subset=['Date'], inplace=True)
            
            if df.empty:
                continue
                
            df['Stock_Code'] = code
            df.sort_values('Date', inplace=True)
            
            results = calculate_weekly_returns(df, code)
            all_results.extend(results)
            
        except Exception as e:
            print(f"处理文件 {filename} 时出错: {e}")
            continue

    print(f"\n处理完成。共生成 {len(all_results)} 条交易记录。")
    
    if all_results:
        results_df = pd.DataFrame(all_results)
        output_file = 'weekly_trade_log.csv'
        results_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"结果已保存至 {output_file}")
    else:
        print("没有生成任何交易记录。")

if __name__ == "__main__":
    # 定义 export 目录路径
    export_dir = "E:\desktop\泰迪杯\阶段三\export"
    
    if os.path.exists(export_dir):
        print(f"开始从 {export_dir} 读取数据并回测...")
        run_backtest(export_dir)
    else:
        print(f"目录不存在: {export_dir}")
