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
import baostock as bs
import time
import pickle
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
        
        # ========== 缓存配置 ==========
        self.cache_file = 'finance_cache.pkl'
        self.cache_expiry_days = 15  # 缓存有效期15天
        
        # ========== 请求控制 ==========
        self.request_interval = 1.0  # 请求间隔1秒
        self.max_retries = 3         # 最大重试次数
        self.retry_delay = 1.5       # 重试间隔1.5秒
        self.last_request_time = 0
        
        # ========== Baostock 连接状态 ==========
        self.bs_logged_in = False
        self._init_baostock()
        
        # ========== 加载持久化缓存 ==========
        self.financial_cache = self._load_cache()
        self._clean_expired_cache()
        
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
    
    # ========== 缓存管理方法 ==========
    
    def _load_cache(self):
        """从文件加载缓存"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'rb') as f:
                    cache = pickle.load(f)
                    print(f"📦 从文件加载了 {len(cache)} 条财务数据缓存")
                    return cache
            except Exception as e:
                print(f"⚠️ 加载缓存文件失败: {e}")
                return {}
        return {}
    
    def _save_cache(self):
        """保存缓存到文件"""
        try:
            with open(self.cache_file, 'wb') as f:
                pickle.dump(self.financial_cache, f)
        except Exception as e:
            print(f"⚠️ 保存缓存文件失败: {e}")
    
    def _clean_expired_cache(self):
        """清理过期的缓存条目"""
        if not self.financial_cache:
            return
        
        expired_keys = []
        current_time = datetime.now()
        
        for key, value in self.financial_cache.items():
            if isinstance(value, dict) and 'cached_time' in value:
                cached_time = value['cached_time']
                days_old = (current_time - cached_time).days
                if days_old > self.cache_expiry_days:
                    expired_keys.append(key)
        
        for key in expired_keys:
            del self.financial_cache[key]
        
        if expired_keys:
            print(f"🧹 清理了 {len(expired_keys)} 条过期缓存（超过{self.cache_expiry_days}天）")
            self._save_cache()
    
    # ========== Baostock 初始化 ==========
    
    def _init_baostock(self):
        """初始化 Baostock 连接"""
        try:
            lg = bs.login()
            if lg.error_code == '0':
                self.bs_logged_in = True
                print("✅ Baostock 登录成功")
            else:
                print(f"⚠️ Baostock 登录失败: {lg.error_msg}")
        except Exception as e:
            print(f"⚠️ Baostock 初始化异常: {e}")
    
    def _logout_baostock(self):
        """登出 Baostock"""
        if self.bs_logged_in:
            try:
                bs.logout()
                self.bs_logged_in = False
                print("🔌 Baostock 已登出")
            except:
                pass
    
    def __del__(self):
        """析构函数：登出 Baostock"""
        self._logout_baostock()
    
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
            s.event_index as event_id,
            s.stock_code,
            s.stock_name
        FROM selected_events s
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
                'event_title': event.get('event_level_2', '')
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
                    'max_strength_event_id': event_id,
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
                'event_title': info['max_strength_event_title'],
                'event_id': info['max_strength_event_id'],
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
    
    # ========== 财务数据获取（级联 + 重试） ==========
    
    def get_financial_data(self, stock_code):
        """
        获取股票财务数据（净资产和净利润）
        先用 AKShare（带重试），失败则用 Baostock
        成功后自动保存到持久化缓存
        
        Returns:
            dict: {'net_assets': 净资产, 'profits': 净利润列表, 'has_data': bool, 'source': str}
        """
        cache_key = f"finance_{stock_code}"
        
        # 1. 先查缓存
        if cache_key in self.financial_cache:
            cached = self.financial_cache[cache_key]
            # 返回时移除时间戳，保持接口一致
            result = cached.copy()
            result.pop('cached_time', None)
            return result
        
        # 2. 尝试 AKShare（带重试）
        result = self._get_financial_data_akshare(stock_code)
        if result['has_data']:
            result['source'] = 'akshare'
            result['cached_time'] = datetime.now()
            self.financial_cache[cache_key] = result.copy()
            self._save_cache()
            result.pop('cached_time', None)
            return result
        
        # 3. AKShare 失败，尝试 Baostock
        print(f"    🔄 AKShare无数据，尝试Baostock...", end="")
        result = self._get_financial_data_baostock(stock_code)
        if result['has_data']:
            result['source'] = 'baostock'
            print(f" ✅")
            result['cached_time'] = datetime.now()
            self.financial_cache[cache_key] = result.copy()
            self._save_cache()
            result.pop('cached_time', None)
        else:
            print(f" ❌")
            result['source'] = 'none'
            # 失败的结果不缓存
        
        return result
    
    def _get_financial_data_akshare(self, stock_code):
        """使用 AKShare 获取财务数据，带重试机制"""
        
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                df = ak.stock_financial_abstract(symbol=stock_code)
                
                if df is None or df.empty:
                    if attempt < self.max_retries - 1:
                        print(f"  ⏳ 第{attempt+1}次无数据，{self.retry_delay}秒后重试...", end="")
                        time.sleep(self.retry_delay)
                        continue
                    return {'net_assets': None, 'profits': [], 'has_data': False, 'error': 'AKShare无数据'}
                
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
                
                has_data = net_assets is not None or len(profits) > 0
                return {'net_assets': net_assets, 'profits': profits, 'has_data': has_data, 'error': None}
                
            except Exception as e:
                if attempt < self.max_retries - 1:
                    print(f"  ⏳ 第{attempt+1}次异常，{self.retry_delay}秒后重试...", end="")
                    time.sleep(self.retry_delay)
                    continue
                return {'net_assets': None, 'profits': [], 'has_data': False, 'error': f'AKShare异常: {str(e)}'}
        
        return {'net_assets': None, 'profits': [], 'has_data': False, 'error': 'AKShare重试耗尽'}
    
    def _get_financial_data_baostock(self, stock_code):
        """使用 Baostock 获取财务数据"""
        if not self.bs_logged_in:
            return {'net_assets': None, 'profits': [], 'has_data': False, 'error': 'Baostock未登录'}
        
        try:
            # 转换股票代码格式：baostock 需要 sh.600000 或 sz.000001
            if stock_code.startswith('6'):
                bs_code = f"sh.{stock_code}"
            elif stock_code.startswith('0') or stock_code.startswith('3'):
                bs_code = f"sz.{stock_code}"
            elif stock_code.startswith('8') or stock_code.startswith('9'):
                bs_code = f"bj.{stock_code}"
            else:
                bs_code = f"sz.{stock_code}"
            
            # 1. 获取资产负债表数据（净资产）
            net_assets = None
            balance_rs = bs.query_balances_data(code=bs_code, year=datetime.now().year, quarter=4)
            if balance_rs.error_code == '0':
                balance_list = []
                while balance_rs.next():
                    balance_list.append(balance_rs.get_row_data())
                if balance_list:
                    balance_df = pd.DataFrame(balance_list, columns=balance_rs.fields)
                    if 'totalEquity' in balance_df.columns:
                        balance_df = balance_df.sort_values('statDate', ascending=False)
                        net_assets = float(balance_df.iloc[0]['totalEquity']) / 10000  # 转换为万元
            
            # 2. 获取利润表数据（净利润）
            profits = []
            profit_rs = bs.query_profit_data(code=bs_code, year=datetime.now().year, quarter=4)
            if profit_rs.error_code == '0':
                profit_list = []
                while profit_rs.next():
                    profit_list.append(profit_rs.get_row_data())
                if profit_list:
                    profit_df = pd.DataFrame(profit_list, columns=profit_rs.fields)
                    if 'netProfit' in profit_df.columns:
                        profit_df = profit_df.sort_values('statDate', ascending=False)
                        for _, row in profit_df.head(6).iterrows():
                            stat_date = row['statDate']
                            if str(stat_date).endswith('1231'):
                                profit_val = float(row['netProfit']) / 10000  # 转换为万元
                                profits.append(profit_val)
                                if len(profits) >= 2:
                                    break
            
            has_data = net_assets is not None or len(profits) > 0
            return {'net_assets': net_assets, 'profits': profits, 'has_data': has_data, 'error': None}
            
        except Exception as e:
            return {'net_assets': None, 'profits': [], 'has_data': False, 'error': f'Baostock异常: {str(e)}'}
    
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
            source = finance.get('source', 'unknown')
            error = finance.get('error', '无数据')
            print(f"  ❌ 无财务数据（来源:{source}）")
            return False
        
        source = finance.get('source', 'unknown')
        
        # 检查净资产
        if finance['net_assets'] is not None:
            if finance['net_assets'] <= 0:
                print(f"  ❌ 净资产为负({finance['net_assets']:.2f}万)")
                return False
        
        # 检查连续两年亏损
        if len(finance['profits']) >= 2:
            if finance['profits'][0] < 0 and finance['profits'][1] < 0:
                print(f"  ❌ 连续两年亏损({finance['profits']})")
                return False
        
        print(f"  ✅ 财务健康 (数据源:{source})")
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
                # 🔑 header=None 因为CSV文件没有表头
                df = pd.read_csv(self.price_data_file, encoding=enc, header=None)
                print(f"  成功使用 {enc} 编码，共 {len(df)} 行")
                break
            except Exception as e:
                print(f"  {enc} 失败: {str(e)[:50]}")
                continue
        
        if df is None:
            print("无法读取日线数据文件，跳过技术面过滤")
            return None
        
        # 🔑 手动指定列名（根据你提供的数据格式）
        df.columns = ['code', 'date', 'open', 'high', 'low', 'close', 
                    'volume', 'amount', 'turnover', 'market_cap']
        
        print(f"\n列名: {df.columns.tolist()}")
        
        # 统一股票代码格式为6位字符串
        df['code'] = df['code'].astype(str).str.strip()
        df['code'] = df['code'].apply(lambda x: x.zfill(6) if x.isdigit() else x)
        
        # 确保date是字符串类型
        df['date'] = df['date'].astype(str)
        
        # 🔑 关键：不指定format，让pandas自动识别日期格式
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        
        # 删除日期无效的行
        df = df.dropna(subset=['date'])
        
        if len(df) == 0:
            print("没有有效的日期数据")
            return None
        
        print(f"日期范围: {df['date'].min().strftime('%Y-%m-%d')} 到 {df['date'].max().strftime('%Y-%m-%d')}")
        
        # 数值列转换
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount', 'turnover', 'market_cap']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 删除收盘价为空的行
        df = df.dropna(subset=['close'])
        
        print(f"\n加载了 {len(df)} 条有效日线数据")
        print(f"涉及股票数量: {df['code'].nunique()} 只")
        
        # 显示前几只股票代码
        sample_codes = df['code'].unique()[:10]
        print(f"股票代码示例: {sample_codes.tolist()}")
        
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
        
        return self.healthy_stocks
    
    def filter_by_technical(self, price_df):
        """步骤4: 技术面过滤（使用事件发布时间计算20日指标）"""
        print("\n" + "="*60)
        print("步骤4: 技术面过滤（20日涨幅>30%或乖离率>15%淘汰）")
        print("="*60)
        
        if price_df is None:
            print("无法加载日线数据，跳过技术面过滤")
            self.final_stocks = self.healthy_stocks.copy()
            self.final_stocks['return_20d'] = 0
            self.final_stocks['bias_20d'] = 0
            self.final_stocks['avg_turnover'] = 0
            self.final_stocks.to_csv('healthy_stocks.csv', index=False, encoding='utf-8-sig')
            return self.final_stocks
        
        # 1. 从数据库获取事件发布时间
        conn = sqlite3.connect(self.db_path)
        query = """
        SELECT 
            event_index,
            publish_time
        FROM selected_events
        """
        event_time_df = pd.read_sql_query(query, conn)
        conn.close()
        
        # 创建 event_index 到 publish_time 的映射
        event_time_map = dict(zip(event_time_df['event_index'], event_time_df['publish_time']))
        
        final_list = []
        
        for idx, row in self.healthy_stocks.iterrows():
            stock_code = row['code']
            stock_name = row['name']
            strength = row['strength']
            event_title = row['event_title']
            event_id = row['event_id']
            
            # 2. 获取事件发布时间
            publish_time_str = event_time_map.get(event_id, '')
            if not publish_time_str:
                print(f"\n[{idx+1}/{len(self.healthy_stocks)}] 检查: {stock_code} {stock_name} - 无发布时间，淘汰")
                continue
            
            # 3. 提取日期部分（只取 YYYY-MM-DD）
            event_date = pd.to_datetime(publish_time_str.split(' ')[0], errors='coerce')
            if pd.isna(event_date):
                print(f"\n[{idx+1}/{len(self.healthy_stocks)}] 检查: {stock_code} {stock_name} - 发布时间无效({publish_time_str})，淘汰")
                continue
            
            print(f"\n[{idx+1}/{len(self.healthy_stocks)}] 检查: {stock_code} {stock_name} (事件日期: {event_date.strftime('%Y-%m-%d')})", end="")
            
            # 4. 检查股票是否在日线数据中
            if stock_code not in price_df['code'].values:
                print(f"  不在日线数据中，淘汰")
                continue
            
            stock_data = price_df[price_df['code'] == stock_code].sort_values('date')
            
            # 5. 找到事件日期之前的最新交易日
            data_before_event = stock_data[stock_data['date'] <= event_date]
            
            if len(data_before_event) < 20:
                print(f"  数据不足（{len(data_before_event)}天 < 20天），淘汰")
                continue
            
            # 6. 取事件日前的最新价格
            latest_before_event = data_before_event.iloc[-1]
            latest_price = latest_before_event['close']
            
            # 7. 取20个交易日前的价格（往前数20根K线）
            price_20d_ago = data_before_event.iloc[-21]['close']
            
            # 8. 计算20日涨幅（事件发生时）
            return_20d = (latest_price - price_20d_ago) / price_20d_ago * 100
            
            # 9. 计算20日均线（事件日前的最近20个交易日）
            ma_20 = data_before_event.iloc[-20:]['close'].mean()
            
            # 10. 计算20日乖离率（事件发生时）
            bias_20d = (latest_price - ma_20) / ma_20 * 100
            
            # 11. 计算事件日前20个交易日的平均换手率
            recent_20d = data_before_event.iloc[-20:]
            avg_turnover = recent_20d['turnover'].mean() if 'turnover' in recent_20d.columns else 0
            
            print(f"  20日涨幅: {return_20d:.2f}%, 乖离率: {bias_20d:.2f}%, 均换手率: {avg_turnover:.2f}%")
            
            # 12. 过滤条件
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
                'bias_20d': bias_20d,
                'avg_turnover': avg_turnover
            })
        
        self.final_stocks = pd.DataFrame(final_list)
        self.final_stocks.to_csv('healthy_stocks_news.csv', index=False, encoding='utf-8-sig')
        
        print(f"\n\n通过技术过滤: {len(self.final_stocks)} 只")
        
        return self.final_stocks
    
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
    
    # ========== BIAS区间判断方法 ==========
    
    def _get_bias_priority(self, bias):
        """
        获取BIAS区间优先级
        返回 int: 数字越小优先级越高
        """
        if 3 <= bias <= 8:
            return 1  # 最优区间
        elif 0 <= bias < 3:
            return 2  # 次优区间
        else:
            return 3  # 其他区间
    
    def _is_extreme_bias(self, bias):
        """
        判断是否为极端BIAS（需要回避）
        """
        return bias < -5 or bias > 12
    
    def _get_bias_zone_name(self, bias):
        """获取BIAS区间名称"""
        if 3 <= bias <= 8:
            return "最优区间(3%-8%)"
        elif 0 <= bias < 3:
            return "次优区间(0%-3%)"
        elif bias < -5:
            return "回避区间(<-5%)"
        elif bias > 12:
            return "回避区间(>12%)"
        else:
            return "其他区间"
    
    def select_top3(self):
        """
        步骤5: 按strength降序选TOP3
        当strength相同时，在同strength股票中按以下规则优选：
        1. 优先BIAS在3%-8%区间
        2. 其次BIAS在0%-3%区间
        3. 回避BIAS < -5% 或 > 12%
        4. 同区间按20日涨幅升序（小者优先）
        5. 最后按换手率降序
        """
        print("\n" + "="*60)
        print("步骤5: 按strength降序选TOP3（相同strength时多条件优选）")
        print("="*60)
        
        if self.final_stocks is None or len(self.final_stocks) == 0:
            print("没有通过所有过滤的股票")
            return None
        
        # 复制数据，避免修改原数据
        stocks = self.final_stocks.copy()
        
        # 先按 strength 降序排列
        stocks = stocks.sort_values('strength', ascending=False)
        
        # 获取所有不同的 strength 值，从高到低
        strength_values = sorted(stocks['strength'].unique(), reverse=True)
        
        selected_list = []  # 最终选出的股票
        
        print(f"\n共有 {len(stocks)} 只股票参与排序")
        print(f"不同strength值（从高到低）: {strength_values}\n")
        
        for strength_val in strength_values:
            # ========== 终止条件：已选满3只 ==========
            if len(selected_list) >= 3:
                break
            
            # 取当前strength的所有股票
            same_strength = stocks[stocks['strength'] == strength_val].copy()
            need_count = 3 - len(selected_list)  # 还需要选几只
            
            print(f"--- strength={strength_val}, 共{len(same_strength)}只, 还需选{need_count}只 ---")
            
            # ========== 情况1：只有1只，直接入选 ==========
            if len(same_strength) == 1:
                stock = same_strength.iloc[0]
                selected_list.append(stock)
                zone = self._get_bias_zone_name(stock['bias_20d'])
                print(f"  ✅ 唯一股票直接入选: {stock['code']} {stock['name']} | BIAS:{stock['bias_20d']:.2f}%({zone}) | 涨幅:{stock['return_20d']:.2f}%")
                print()
                continue
            
            # ========== 情况2：多只股票，触发多条件优选 ==========
            # 分离正常BIAS和极端BIAS
            same_strength['is_extreme'] = same_strength['bias_20d'].apply(self._is_extreme_bias)
            normal_stocks = same_strength[~same_strength['is_extreme']].copy()
            extreme_stocks = same_strength[same_strength['is_extreme']].copy()
            
            if len(extreme_stocks) > 0:
                print(f"  ⚠️ 极端BIAS股票({len(extreme_stocks)}只，优先回避):")
                for _, row in extreme_stocks.iterrows():
                    print(f"      {row['code']} {row['name']} | BIAS:{row['bias_20d']:.2f}%")
            
            # 正常股票足够，从正常股票中排序选出
            if len(normal_stocks) >= need_count:
                # 添加BIAS区间优先级
                normal_stocks['bias_priority'] = normal_stocks['bias_20d'].apply(self._get_bias_priority)
                
                # 🔑 多条件联合排序
                # 1: BIAS区间优先级升序(3%-8% → 0%-3% → 其他)
                # 2: 20日涨幅升序
                # 3: 换手率降序
                normal_stocks = normal_stocks.sort_values(
                    by=['bias_priority', 'return_20d', 'avg_turnover'],
                    ascending=[True, True, False]
                )
                
                chosen = normal_stocks.head(need_count)
                for _, stock in chosen.iterrows():
                    selected_list.append(stock)
                    zone = self._get_bias_zone_name(stock['bias_20d'])
                    print(f"  ✅ 入选: {stock['code']} {stock['name']} | BIAS:{stock['bias_20d']:.2f}%({zone}) | 涨幅:{stock['return_20d']:.2f}% | 换手率:{stock['avg_turnover']:.2f}%")
                
                # 显示未入选的
                not_chosen = normal_stocks.iloc[len(chosen):]
                if len(not_chosen) > 0:
                    print(f"  ❌ 未入选:")
                    for _, row in not_chosen.iterrows():
                        zone = self._get_bias_zone_name(row['bias_20d'])
                        print(f"      {row['code']} {row['name']} | BIAS:{row['bias_20d']:.2f}%({zone}) | 涨幅:{row['return_20d']:.2f}%")
            
            # 正常股票不够，先全选正常股票，再从极端中补充
            elif len(normal_stocks) > 0:
                # 正常股票全要，按同样规则排序
                normal_stocks['bias_priority'] = normal_stocks['bias_20d'].apply(self._get_bias_priority)
                normal_stocks = normal_stocks.sort_values(
                    by=['bias_priority', 'return_20d', 'avg_turnover'],
                    ascending=[True, True, False]
                )
                
                for _, stock in normal_stocks.iterrows():
                    selected_list.append(stock)
                    zone = self._get_bias_zone_name(stock['bias_20d'])
                    print(f"  ✅ 入选: {stock['code']} {stock['name']} | BIAS:{stock['bias_20d']:.2f}%({zone}) | 涨幅:{stock['return_20d']:.2f}%")
                
                # 还差几只，从极端BIAS中补充
                still_need = need_count - len(normal_stocks)
                if still_need > 0 and len(extreme_stocks) > 0:
                    print(f"  ⚠️ 正常股票不足，从极端BIAS中补充{still_need}只:")
                    # 极端BIAS中按涨幅升序、换手率降序排序
                    extreme_stocks = extreme_stocks.sort_values(
                        by=['return_20d', 'avg_turnover'],
                        ascending=[True, False]
                    )
                    chosen = extreme_stocks.head(still_need)
                    for _, stock in chosen.iterrows():
                        selected_list.append(stock)
                        zone = self._get_bias_zone_name(stock['bias_20d'])
                        print(f"  ✅ 补充: {stock['code']} {stock['name']} | BIAS:{stock['bias_20d']:.2f}%({zone}) | 涨幅:{stock['return_20d']:.2f}%")
            
            # 全部是极端BIAS，直接从极端中排序选出
            else:
                print(f"  ⚠️ 该strength下全部为极端BIAS，直接排序选择:")
                extreme_stocks = extreme_stocks.sort_values(
                    by=['return_20d', 'avg_turnover'],
                    ascending=[True, False]
                )
                chosen = extreme_stocks.head(need_count)
                for _, stock in chosen.iterrows():
                    selected_list.append(stock)
                    zone = self._get_bias_zone_name(stock['bias_20d'])
                    print(f"  ✅ 入选: {stock['code']} {stock['name']} | BIAS:{stock['bias_20d']:.2f}%({zone}) | 涨幅:{stock['return_20d']:.2f}%")
            
            print()  # 空行
        
        # ========== 输出最终结果 ==========
        top3 = pd.DataFrame(selected_list)
        
        print("\n" + "="*60)
        print(f"最终选出 {len(top3)} 只股票:")
        print("="*60)
        for i, (idx, row) in enumerate(top3.iterrows(), 1):
            zone = self._get_bias_zone_name(row['bias_20d'])
            print(f"\n  {i}. {row['code']} {row['name']}")
            print(f"     strength: {row['strength']}")
            print(f"     BIAS: {row['bias_20d']:.2f}% ({zone})")
            print(f"     20日涨幅: {row['return_20d']:.2f}%")
            print(f"     均换手率: {row['avg_turnover']:.2f}%")
        
        return top3[['code', 'name', 'strength', 'event_title', 'event_id',
                     'return_20d', 'bias_20d', 'avg_turnover']]
    
    def save_result(self, top3, output_file='safe_top3_stocks_news.csv'):
        """保存结果，包含事件ID和排序指标"""
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
            '20日乖离率(%)': top3['bias_20d'].round(2),
            '平均换手率(%)': top3['avg_turnover'].round(2)
        })
        
        # 保存
        result_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n结果已保存到: {output_file}")
        
        # 打印简洁版
        print("\n" + "="*70)
        print("本周推荐买入的3只股票（多条件优选出品）:")
        print("="*70)
        for i, (idx, row) in enumerate(result_df.iterrows(), 1):
            bias_zone = self._get_bias_zone_name(row['20日乖离率(%)'])
            print(f"{i}. {row['股票代码']} {row['股票名称']}")
            print(f"   强度: {row['强度']}")
            print(f"   对应事件: {row['事件标题']} (ID: {row['对应事件ID']})")
            print(f"   20日涨幅: {row['20日涨幅(%)']:.2f}%")
            print(f"   20日乖离率: {row['20日乖离率(%)']:.2f}% ({bias_zone})")
            print(f"   平均换手率: {row['平均换手率(%)']:.2f}%")
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
        
        # 7. 登出 Baostock
        self._logout_baostock()
        
        return top3


def main():
    """主函数"""
    # 创建风险过滤器
    filter = RiskFilter(
        db_path='selected_events2.db',
        json_file='test2.json',
        price_data_file='新日线数据.csv'
    )
    
    # 运行过滤
    top3 = filter.run()
    
    print("\n" + "="*60)
    print("✅ 风控过滤完成！")
    print("="*60)


if __name__ == "__main__":
    main()