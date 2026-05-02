"""
RiskFilter.py
高阶风控过滤器：从数据库获取股票池，从JSON获取strength，结合基本面和技术面过滤，输出前3名安全股票
"""

import sqlite3
import pandas as pd
import numpy as np
import os
import json
import akshare as ak
import time
from datetime import datetime, timedelta

class RiskFilter:
    """风险过滤器"""
    
    def __init__(self, db_path='structured_events.db', json_file='events_date.json', price_data_file='日线数据.csv'):
        """
        初始化风险过滤器
        
        Args:
            db_path: 数据库路径（获取股票池）
            json_file: 事件JSON文件路径（获取strength）
            price_data_file: 日线数据CSV文件路径
        """
        self.db_path = db_path
        self.json_file = json_file
        self.price_data_file = price_data_file
        self.stock_pool = None  # 原始股票池（含strength）
        self.healthy_stocks = None  # 财务健康的股票
        self.final_stocks = None  # 最终过滤后的股票
        
        # 财务数据缓存
        self.financial_cache = {}
        self.request_interval = 0.5
        self.last_request_time = 0
        
        # 预定义的A股代码范围（用于快速判断）
        self.sh_prefixes = ['600', '601', '603', '605', '688', '689']
        self.sz_prefixes = ['000', '001', '002', '003', '004', '300', '301']
        self.bj_prefixes = ['830', '831', '832', '833', '834', '835', '836', '837', '838', '839',
                           '870', '871', '872', '873', '874', '875', '876', '877', '878', '879',
                           '880', '881', '882', '883', '884', '885', '886', '887', '888', '889',
                           '920', '921', '922', '923', '924', '925', '926', '927', '928', '929']
        
        # 港股常见前缀（需要排除）
        self.hk_prefixes = ['000', '001', '002', '003', '004', '005', '006', '007', '008', '009',
                           '010', '011', '012', '013', '014', '015', '016', '017', '018', '019']
    
    def is_a_share(self, stock_code):
        """判断是否为A股"""
        code = str(stock_code).strip()
        if len(code) < 6:
            code = code.zfill(6)
        prefix = code[:3]
        
        if prefix in self.sh_prefixes:
            return True
        if prefix in self.sz_prefixes:
            return True
        if prefix in self.bj_prefixes:
            return True
        return False
    
    def load_stock_pool_from_db_and_json(self):
        """
        从数据库和JSON文件加载股票池和strength，并记录事件ID
        """
        print("\n" + "="*60)
        print("步骤1: 从数据库和JSON文件加载股票池")
        print("="*60)
        
        # 1. 从数据库获取事件-股票关联
        conn = sqlite3.connect(self.db_path)
        query = """
        SELECT 
            s.event_id,
            s.stock_code,
            s.stock_name
        FROM event_stocks s
        WHERE s.stock_code IS NOT NULL AND s.stock_code != ''
        """
        stock_event_df = pd.read_sql_query(query, conn)
        conn.close()
        
        print(f"从数据库获取了 {len(stock_event_df)} 条股票-事件关联记录")
        
        # 2. 统一股票名称
        name_counts = stock_event_df.groupby(['stock_code', 'stock_name']).size().reset_index(name='count')
        unified_names = {}
        for code in name_counts['stock_code'].unique():
            code_data = name_counts[name_counts['stock_code'] == code]
            code_data = code_data.sort_values('count', ascending=False)
            unified_names[code] = code_data.iloc[0]['stock_name']
        
        stock_event_df['stock_name'] = stock_event_df['stock_code'].map(unified_names)
        
        # 3. 从JSON文件获取事件强度
        with open(self.json_file, 'r', encoding='utf-8') as f:
            events = json.load(f)
        
        print(f"从JSON文件加载了 {len(events)} 个事件")
        
        # 4. 创建事件ID到强度和标题的映射
        event_info = {}
        for i, event in enumerate(events):
            event_id = i + 1
            event_info[event_id] = {
                'strength': event.get('strength', 0),
                'event_title': event.get('event_level_2', '')  # 事件标题
            }
        
        # 5. 计算每只股票的强度和关联的事件ID
        stock_strength = {}
        for _, row in stock_event_df.iterrows():
            event_id = row['event_id']
            stock_code = str(row['stock_code']).strip()
            if len(stock_code) < 6:
                stock_code = stock_code.zfill(6)
            stock_name = row['stock_name']
            
            strength = event_info.get(event_id, {}).get('strength', 0)
            event_title = event_info.get(event_id, {}).get('event_title', '')
            
            if stock_code not in stock_strength:
                stock_strength[stock_code] = {
                    'name': stock_name,
                    'max_strength': strength,
                    'max_strength_event_id': event_id,  # 记录最大strength对应的事件ID
                    'max_strength_event_title': event_title,
                    'all_strengths': [strength],
                    'all_events': [(event_id, strength, event_title)]
                }
            else:
                stock_strength[stock_code]['all_strengths'].append(strength)
                stock_strength[stock_code]['all_events'].append((event_id, strength, event_title))
                if strength > stock_strength[stock_code]['max_strength']:
                    stock_strength[stock_code]['max_strength'] = strength
                    stock_strength[stock_code]['max_strength_event_id'] = event_id
                    stock_strength[stock_code]['max_strength_event_title'] = event_title
        
        # 6. 创建股票池DataFrame
        stocks_data = []
        for code, info in stock_strength.items():
            stocks_data.append({
                'code': code,
                'name': info['name'],
                'strength': info['max_strength'],
                'event_title': info['max_strength_event_title'],  # 新增：事件标题
                'event_id': info['max_strength_event_id'],  # 新增：对应事件ID
                'event_count': len(info['all_strengths'])
            })
        
        self.stock_pool = pd.DataFrame(stocks_data)
        self.stock_pool = self.stock_pool.sort_values('strength', ascending=False)
        
        print(f"\n股票池共有 {len(self.stock_pool)} 只股票")
        print("\n股票池前10只（按strength排序）:")
        for i, row in self.stock_pool.head(10).iterrows():
            print(f"  {row['code']} {row['name']} - strength: {row['strength']} (事件ID: {row['event_id']})")
        
        return self.stock_pool
    
    def _rate_limit(self):
        """限流"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.request_interval:
            time.sleep(self.request_interval - time_since_last)
        self.last_request_time = time.time()
    
    def get_financial_data(self, stock_code):
        """
        获取股票财务数据（净资产和净利润）
        
        Returns:
            dict: {'net_assets': 净资产, 'profits': 净利润列表, 'has_data': bool}
        """
        cache_key = f"finance_{stock_code}"
        if cache_key in self.financial_cache:
            return self.financial_cache[cache_key]
        
        self._rate_limit()
        
        try:
            df = ak.stock_financial_abstract(symbol=stock_code)
            
            if df is None or df.empty:
                result = {'net_assets': None, 'profits': [], 'has_data': False, 'error': '无数据'}
                self.financial_cache[cache_key] = result
                return result
            
            # 提取净利润
            profits = []
            profit_row = None
            for idx, row in df.iterrows():
                if '净利润' in str(row.get('指标', '')) and row.get('选项') == '常用指标':
                    profit_row = row
                    break
            
            if profit_row is not None:
                date_cols = [col for col in df.columns 
                            if col not in ['选项', '指标'] and str(col).isdigit()]
                date_cols.sort(reverse=True)
                
                year_profits = []
                for col in date_cols:
                    if str(col).endswith('1231'):
                        profit = profit_row[col]
                        if pd.notna(profit) and profit != 0:
                            year_profits.append(float(profit))
                        if len(year_profits) >= 2:
                            break
                profits = year_profits
            
            # 提取净资产
            net_assets = None
            for idx, row in df.iterrows():
                if any(kw in str(row.get('指标', '')) for kw in ['净资产', '所有者权益', '股东权益']):
                    date_cols = [col for col in df.columns 
                                if col not in ['选项', '指标'] and str(col).isdigit()]
                    date_cols.sort(reverse=True)
                    if date_cols:
                        value = row[date_cols[0]]
                        if pd.notna(value):
                            net_assets = float(value)
                    break
            
            result = {'net_assets': net_assets, 'profits': profits, 'has_data': True, 'error': None}
            self.financial_cache[cache_key] = result
            return result
            
        except Exception as e:
            result = {'net_assets': None, 'profits': [], 'has_data': False, 'error': str(e)}
            self.financial_cache[cache_key] = result
            return result
    
    def check_financial_health(self, stock_code, stock_name):
        """
        检查股票财务健康（连续两年亏损或净资产为负则淘汰）
        
        Returns:
            bool: True表示健康，False表示有风险
        """
        # 获取财务数据
        finance = self.get_financial_data(stock_code)
        
        # 无财务数据，默认淘汰
        if not finance['has_data']:
            print(f"  {stock_code} {stock_name}: 无财务数据，淘汰")
            return False
        
        # 检查净资产
        if finance['net_assets'] is not None:
            if finance['net_assets'] <= 0:
                print(f"  {stock_code} {stock_name}: 净资产为负({finance['net_assets']:.2f})，淘汰")
                return False
        
        # 检查连续两年亏损
        if len(finance['profits']) >= 2:
            if finance['profits'][0] < 0 and finance['profits'][1] < 0:
                print(f"  {stock_code} {stock_name}: 连续两年亏损({finance['profits']})，淘汰")
                return False
        
        print(f"  {stock_code} {stock_name}: 财务健康 ✅")
        return True
    
    def load_price_data(self):
        """加载日线数据"""
        print("\n" + "="*60)
        print("步骤3: 加载日线数据")
        print("="*60)
        
        if not os.path.exists(self.price_data_file):
            print(f"错误: 找不到日线数据文件 {self.price_data_file}")
            return None
        
        # 尝试多种编码
        encodings = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'gb18030']
        
        df = None
        for enc in encodings:
            try:
                print(f"尝试编码: {enc}")
                # 完整读取，跳过注释行
                df = pd.read_csv(self.price_data_file, encoding=enc, comment='#')
                print(f"  成功使用 {enc} 编码，共 {len(df)} 行")
                break
            except Exception as e:
                print(f"  {enc} 失败: {str(e)[:50]}")
                continue
        
        if df is None:
            print("无法读取日线数据文件，跳过技术面过滤")
            return None
        
        # 查看实际列名
        print(f"\n实际列名: {df.columns.tolist()}")
        
        # 根据实际列名重命名
        if '代码' in df.columns:
            df = df.rename(columns={
                '代码': 'code',
                '日期': 'date',
                '开盘': 'open',
                '最高': 'high',
                '最低': 'low',
                '收盘': 'close',
                '成交量': 'volume',
                '成交额': 'amount',
                '换手率(%)': 'turnover',
                '流通市值': 'market_cap'
            })
        
        # 【关键修复】统一股票代码格式为6位字符串
        df['code'] = df['code'].astype(str).str.strip()
        df['code'] = df['code'].apply(lambda x: x.zfill(6) if x.isdigit() else x)
        
        # 检查是否有空值
        df = df.dropna(subset=['date'])
        
        # 确保date是字符串类型
        df['date'] = df['date'].astype(str)
        
        # 只保留符合日期格式的行
        date_pattern = r'^\d{4}[/-]\d{1,2}[/-]\d{1,2}$'
        mask = df['date'].str.match(date_pattern, na=False)
        df = df[mask].copy()
        
        if len(df) == 0:
            print("没有有效的日期数据")
            return None
        
        # 转换日期格式
        try:
            df['date'] = pd.to_datetime(df['date'], format='%Y/%m/%d', errors='coerce')
            if df['date'].isna().any():
                df['date'] = pd.to_datetime(df['date'], format='%Y-%m-%d', errors='coerce')
            df = df.dropna(subset=['date'])
            print(f"日期范围: {df['date'].min()} 到 {df['date'].max()}")
        except Exception as e:
            print(f"日期转换失败: {e}")
            return None
        
        # 数值列转换
        for col in ['open', 'high', 'low', 'close']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df = df.dropna(subset=['close'])
        
        print(f"\n加载了 {len(df)} 条有效日线数据")
        print(f"涉及股票数量: {df['code'].nunique()} 只")
        print(f"股票代码示例: {df['code'].unique()[:10]}")
        
        # 【调试】检查特定股票是否存在
        test_code = '600292'
        if test_code in df['code'].values:
            print(f"✅ 股票 {test_code} 存在于日线数据中，共 {len(df[df['code'] == test_code])} 条记录")
        else:
            print(f"❌ 股票 {test_code} 不存在于日线数据中")
            # 打印相近的代码
            similar = [c for c in df['code'].unique() if test_code in c]
            if similar:
                print(f"   相近代码: {similar[:5]}")
        
        return df
    
    def calculate_technical_indicators(self, stock_code, price_df):
        """
        计算股票的20日涨幅和20日乖离率
        
        Returns:
            tuple: (20日涨幅, 20日乖离率) 或 (None, None)
        """
        # 获取该股票的数据
        stock_data = price_df[price_df['code'] == stock_code].sort_values('date')
        
        if len(stock_data) < 20:
            return None, None
        
        # 最新价格
        latest = stock_data.iloc[-1]
        latest_price = latest['close']
        
        # 20日前价格
        price_20d_ago = stock_data.iloc[-21]['close']
        
        # 20日涨幅
        return_20d = (latest_price - price_20d_ago) / price_20d_ago * 100
        
        # 20日均线
        ma_20 = stock_data.iloc[-20:]['close'].mean()
        
        # 20日乖离率
        bias_20d = (latest_price - ma_20) / ma_20 * 100
        
        return return_20d, bias_20d
    
    def filter_by_financial(self):
        """步骤2: 财务过滤"""
        print("\n" + "="*60)
        print("步骤2: 财务过滤（检查连续两年亏损、净资产为负、ST股票）")
        print("="*60)
        
        healthy_list = []
        total_a_share = 0
        total_checked = 0
        st_count = 0
        
        # 只保留A股
        a_share_stocks = self.stock_pool[self.stock_pool['code'].apply(self.is_a_share)]
        
        for idx, row in a_share_stocks.iterrows():
            stock_code = row['code']
            stock_name = row['name']
            strength = row['strength']
            event_title = row['event_title']
            event_id = row['event_id']

            total_a_share += 1
            total_checked += 1
            
            # 先检查是否为ST股票
            if self.is_st_stock(stock_name):
                st_count += 1
                print(f"\n[{total_checked}/{len(a_share_stocks)}] 检查: {stock_code} {stock_name} - ST股票，直接淘汰")
                continue
            
            print(f"\n[{total_checked}/{len(a_share_stocks)}] 检查: {stock_code} {stock_name}", end="")
            
            if self.check_financial_health(stock_code, stock_name):
                healthy_list.append({
                    'code': stock_code,
                    'name': stock_name,
                    'strength': strength,
                    'event_title': event_title,
                    'event_id': event_id
                })
            
            # 每10只打印分隔线
            if total_checked % 10 == 0:
                print("-" * 40)
        
        self.healthy_stocks = pd.DataFrame(healthy_list)
        print(f"\n\nA股总数: {total_a_share}")
        print(f"ST股票淘汰: {st_count}")
        print(f"通过财务过滤: {len(self.healthy_stocks)} 只")
        
        # 保存健康股票列表
        self.healthy_stocks.to_csv('healthy_stocks.csv', index=False, encoding='utf-8-sig')
        
        return self.healthy_stocks
    
    def filter_by_technical(self, price_df):
        """步骤4: 技术面过滤"""
        print("\n" + "="*60)
        print("步骤4: 技术面过滤（20日涨幅>30%或乖离率>15%淘汰）")
        print("="*60)
        
        if price_df is None:
            print("无法加载日线数据，跳过技术面过滤")
            self.final_stocks = self.healthy_stocks.copy()
            self.final_stocks['return_20d'] = 0
            self.final_stocks['bias_20d'] = 0
            return self.final_stocks
        
        final_list = []
        
        for idx, row in self.healthy_stocks.iterrows():
            stock_code = row['code']
            stock_name = row['name']
            strength = row['strength']
            event_title = row['event_title']
            event_id = row['event_id']
           
            
            print(f"\n[{idx+1}/{len(self.healthy_stocks)}] 检查: {stock_code} {stock_name}", end="")
            
            # 检查股票是否在日线数据中
            if stock_code not in price_df['code'].values:
                print(f"  不在日线数据中，淘汰")
                continue
            
            stock_data = price_df[price_df['code'] == stock_code].sort_values('date')
            
            if len(stock_data) < 20:
                print(f"  数据不足（{len(stock_data)}天 < 20天），淘汰")
                continue
            
            # 计算20日指标
            latest = stock_data.iloc[-1]
            latest_price = latest['close']
            price_20d_ago = stock_data.iloc[-21]['close']
            ma_20 = stock_data.iloc[-20:]['close'].mean()
            
            return_20d = (latest_price - price_20d_ago) / price_20d_ago * 100
            bias_20d = (latest_price - ma_20) / ma_20 * 100
            
            print(f"  20日涨幅: {return_20d:.2f}%, 乖离率: {bias_20d:.2f}%")
            
            if return_20d > 30:
                print(f"  涨幅过高，淘汰")
                continue
            
            if bias_20d > 15:
                print(f"  乖离率过高，淘汰")
                continue
            
            print(f"  通过 ✅")
            final_list.append({
                'code': stock_code,
                'name': stock_name,
                'strength': strength,
                'event_title': event_title,
                'event_id': event_id,
                'return_20d': return_20d,
                'bias_20d': bias_20d
            })
        
        self.final_stocks = pd.DataFrame(final_list)
        print(f"\n\n通过技术过滤: {len(self.final_stocks)} 只")
        
        return self.final_stocks
    
    def select_top3(self):
        """步骤5: 按strength降序取前3名"""
        print("\n" + "="*60)
        print("步骤5: 按strength排序，取前3名")
        print("="*60)
        
        if self.final_stocks is None or len(self.final_stocks) == 0:
            print("没有通过所有过滤的股票")
            return None
        
        # 按strength降序排列
        top3 = self.final_stocks.sort_values('strength', ascending=False).head(3)
        
        print("\n最终选出的 TOP 3 股票:")
        for i, (idx, row) in enumerate(top3.iterrows(), 1):
            print(f"  {i}. {row['code']} {row['name']} - strength: {row['strength']}")
            print(f"     20日涨幅: {row['return_20d']:.2f}%, 乖离率: {row['bias_20d']:.2f}%")
        
        return top3
    
    def save_result(self, top3, output_file='safe_top3_stocks.csv'):
        """保存结果"""
        if top3 is None or len(top3) == 0:
            print("没有符合条件的股票，不保存文件")
            return
        
        # 添加过滤日期
        top3['filter_date'] = datetime.now().strftime('%Y-%m-%d')
        
        # 保存
        top3.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存到: {output_file}")
        
        # 打印简洁版
        print("\n" + "="*60)
        print("本周推荐买入的3只股票:")
        print("="*60)
        for i, (idx, row) in enumerate(top3.iterrows(), 1):
            print(f"{i}. {row['code']} {row['name']}")
            print(f"   strength: {row['strength']}")
            print(f"   20日涨幅: {row['return_20d']:.2f}%")
            print(f"   20日乖离率: {row['bias_20d']:.2f}%")
            print()
    
    def run(self):
        """运行完整的风控流程"""
        print("="*60)
        print("高阶风控过滤器 RiskFilter")
        print("="*60)
        
        # 1. 加载股票池（从数据库和JSON获取strength）
        self.load_stock_pool_from_db_and_json()
        
        # 2. 财务过滤
        self.filter_by_financial()
        
        # 3. 加载日线数据
        price_df = self.load_price_data()
        
        # 4. 技术面过滤
        self.filter_by_technical(price_df)
        
        # 5. 选前3名
        top3 = self.select_top3()
        
        # 6. 保存结果
        self.save_result(top3)
        
        return top3
    
    def is_st_stock(self, stock_name):
        """
        判断是否为ST股票
        ST股票通常名称中包含 ST、*ST、SST 等字样
        """
        if not stock_name:
            return False
        
        st_patterns = ['ST', '*ST', 'SST', 'ST*']
        stock_name_upper = str(stock_name).upper()
        
        for pattern in st_patterns:
            if pattern in stock_name_upper:
                return True
        return False
    
    def save_result(self, top3, output_file='safe_top3_stocks.csv'):
        """保存结果，包含事件ID"""
        if top3 is None or len(top3) == 0:
            print("没有符合条件的股票，不保存文件")
            return
        
        # 创建新的DataFrame，使用中文列名
        result_df = pd.DataFrame({
            '股票代码': top3['code'],
            '股票名称': top3['name'],
            '强度': top3['strength'],
            '事件标题': top3['event_title'],
            '对应事件ID': top3['event_id'],
            '20日涨幅(%)': top3['return_20d'].round(2),
            '20日乖离率(%)': top3['bias_20d'].round(2)
        })
        
        # 保存
        result_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存到: {output_file}")
        
        # 打印简洁版
        print("\n" + "="*70)
        print("本周推荐买入的3只股票:")
        print("="*70)
        for i, (idx, row) in enumerate(result_df.iterrows(), 1):
            print(f"{i}. {row['股票代码']} {row['股票名称']}")
            print(f"   强度: {row['强度']}")
            print(f"   对应事件ID: {row['事件标题']} - {row['对应事件ID']}")
            print(f"   20日涨幅: {row['20日涨幅(%)']:.2f}%")
            print(f"   20日乖离率: {row['20日乖离率(%)']:.2f}%")
            print()


def main():
    """主函数"""
    # 创建风险过滤器
    filter = RiskFilter(
        db_path='structured_events.db',
        json_file='events_date.json',
        price_data_file='日线数据.csv'
    )
    
    # 运行过滤
    top3 = filter.run()
    
    print("\n" + "="*60)
    print("风控过滤完成！")
    print("="*60)


if __name__ == "__main__":
    main()