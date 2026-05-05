import pandas as pd
import os
import glob
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib as mpl

def _set_chinese_font():
    try:
        plt.style.use('seaborn-v0_8-muted')
    except OSError:
        plt.style.use('default')

    if sys.platform.startswith('win'):
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'FangSong']
    else:
        plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang HK']   
    plt.rcParams['axes.unicode_minus'] = False

def find_stock_file(code, export_dir):
    files = glob.glob(os.path.join(export_dir, f"*{code}.txt"))
    if files: return files[0]
    return None

def load_stock_data(filepath, code):
    """
    改为从 日线数据.csv 直接检索该代码的数据。
    """
    try:
        daily_csv = "日线数据.csv"
        if not os.path.exists(daily_csv):
            daily_csv = os.path.join(os.path.dirname(__file__), "日线数据.csv")
            
        columns = ['代码', '日期', '开盘', '收盘']
        df_all = pd.read_csv(daily_csv, usecols=columns, encoding='utf-8')
        df_all['代码'] = df_all['代码'].astype(str).str.zfill(6)
        df = df_all[df_all['代码'] == code].copy()
        
        df = df[['日期', '开盘', '收盘']].copy()
        df.columns = ['Date', 'Open', 'Close']
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
        df.dropna(subset=['Date', 'Close'], inplace=True)
        df.sort_values('Date', inplace=True)
        df['Return'] = df['Close'].pct_change()
        return df.reset_index(drop=True)
    except Exception as e:
        print(f"读取数据失败 {code}: {e}")
        return pd.DataFrame()

def main():
    _set_chinese_font()
    
    export_dir = r"E:\量化项目\股票数据\export"
    out_dir = Path(r"E:\量化项目\ECO\阶段三\result")
    out_dir.mkdir(exist_ok=True, parents=True)

    events_list = [
        {"code": "000950", "date": "2025-12-08", "title": "技术突破(重药控股)"},
        {"code": "001208", "date": "2025-12-08", "title": "重大合同签署(华菱线缆)"},
        {"code": "002639", "date": "2025-12-08", "title": "行业龙头动作(雪人集团)"}
    ]

    print(f"共锁定 {len(events_list)} 个事件供进行 CAR 分析。")

    cnt = 0
    baseline_return = 0.0001  # HS300我们用微小的常量假设

    for ev in events_list:
        df = load_stock_data("", ev['code'])
        if df.empty:
            print(f"{ev['code']} 数据为空")
            continue
        
        target_date = pd.to_datetime(ev['date'])
        
        # 寻找最近的 T 日
        idx_matches = df[df['Date'] >= target_date].index
        if len(idx_matches) == 0:
            print(f"数据未能覆盖事件日 {ev['date']} ({ev['code']})")
            continue
        t_idx = idx_matches[0]
        
        start_idx = max(0, t_idx - 5)
        end_idx = min(len(df) - 1, t_idx + 5)
            
        window_df = df.iloc[start_idx : end_idx+1].copy()
        
        window_df['AR'] = window_df['Return'] - baseline_return
        window_df['AR'] = window_df['AR'].fillna(0).clip(lower=-0.2, upper=0.2)
        
        window_df['T'] = range(start_idx - t_idx, end_idx - t_idx + 1)
        window_df['CAR'] = window_df['AR'].cumsum()
        
        # 为了防错，拿T=0的值
        t_0_ar = window_df[window_df['T']==0]['AR'].values[0] if len(window_df[window_df['T']==0]) > 0 else 0
        t_5_car = window_df['CAR'].iloc[-1]
        print(f"[{ev['title']}] T=0 AR: {t_0_ar:.2%}, T+5 CAR: {t_5_car:.2%}")
        
        plt.figure(figsize=(8, 5))
        plt.plot(window_df['T'], window_df['CAR'], marker='o', linestyle='-', color='b')
        plt.title(f"{ev['title']} - 累计异常收益率 (CAR)")
        plt.xlabel("事件日 (T=-5 到 T+5)")
        plt.ylabel("CAR (累计异常收益率)")
        plt.axhline(0, color='r', linestyle='--')
        plt.axvline(0, color='gray', linestyle=':')
        plt.xticks(range(-5, 6))
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        
        save_path = out_dir / f"CAR走势图_{ev['code']}_{ev['title']}.png"
        plt.savefig(save_path)
        plt.close()
        
        print(f"已生成图像: {save_path}")
        cnt += 1

    print(f"\n执行完毕，成功生成了 {cnt} 张 CAR 曲线走势图！")

if __name__ == '__main__':
    main()