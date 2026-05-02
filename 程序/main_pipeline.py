"""
main_pipeline.py
系统集成脚本：从JSON文件读取事件 -> 调用选股脚本 -> 筛选有匹配结果的事件 -> 存入结果库
"""

import sqlite3
import json
import time
import logging
import subprocess
import os
from typing import Dict, List, Any

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== 配置文件路径 ====================
EVENTS_FILE = "test2.json"           # 输入：事件JSON文件
SELECTED_JSON = "selected_stocks2.json"     # 中间：选股结果JSON
TARGET_DB = "selected_events2.db"           # 输出：结果数据库


# ==================== 数据库连接 ====================
class DatabaseManager:
    """数据库管理类"""
    
    def __init__(self, target_db: str):
        self.target_db = target_db
        
    def get_target_connection(self):
        """连接目标数据库"""
        return sqlite3.connect(self.target_db)
    
    def init_target_db(self):
        """初始化目标数据库表结构"""
        conn = self.get_target_connection()
        cursor = conn.cursor()
        
        # 先删除旧表（如果存在）
        cursor.execute('DROP TABLE IF EXISTS selected_events')
        
        # 创建selected_events表（修改字段：news_title -> event_title，新增 publish_time）
        cursor.execute('''
        CREATE TABLE selected_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_title TEXT,           -- 事件标题（来自JSON的event_title）
            event_index INTEGER,        -- 事件索引
            publish_time TEXT,          -- 发布时间（来自JSON的publish_time）
            stock_code TEXT,            -- 股票代码
            stock_name TEXT,            -- 股票名称
            matched_by TEXT,            -- 匹配方式 (company/concept)
            matched_value TEXT          -- 匹配到的值
        )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"目标数据库初始化完成: {self.target_db}")


# ==================== 主流程 ====================
class NewsPipeline:
    """新闻处理流水线"""
    
    def __init__(self, events_file: str, target_db: str):
        self.events_file = events_file
        self.db = DatabaseManager(target_db)
        self.db.init_target_db()
    
    def run_select_stocks_script(self):
        """
        调用 select_stocks_from_events.py 脚本
        生成 selected_stocks.json 文件
        """
        logger.info("调用选股脚本 select_stocks_from_events.py...")
        
        # 检查脚本是否存在
        if not os.path.exists("select_stocks_from_events.py"):
            logger.error("找不到 select_stocks_from_events.py 文件")
            return False
        
        try:
            # 运行选股脚本
            result = subprocess.run(
                ["python", "select_stocks_from_events.py"],
                capture_output=True,
                text=True,
                timeout=600  # 10分钟超时
            )
            
            if result.returncode == 0:
                logger.info("选股脚本执行成功")
                logger.debug(f"脚本输出: {result.stdout[-500:]}")
                return True
            else:
                logger.error(f"选股脚本执行失败: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("选股脚本执行超时")
            return False
        except Exception as e:
            logger.error(f"执行选股脚本时出错: {e}")
            return False
    
    def check_selected_stocks_exists(self):
        """
        检查 selected_stocks.json 是否已存在
        """
        if os.path.exists(SELECTED_JSON):
            logger.info(f"发现已存在的选股结果文件: {SELECTED_JSON}")
            # 可选：检查文件是否为空
            try:
                with open(SELECTED_JSON, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data:
                        logger.info(f"文件非空，包含 {len(data)} 条记录，将直接使用")
                        return True
                    else:
                        logger.warning("文件为空，将重新运行选股脚本")
                        return False
            except:
                logger.warning("文件读取失败，将重新运行选股脚本")
                return False
        else:
            logger.info(f"未找到选股结果文件: {SELECTED_JSON}")
            return False
    
    def load_selected_results(self) -> List[Dict]:
        """
        加载选股结果
        Returns:
            选股结果列表，只包含 status='ok' 的记录
        """
        if not os.path.exists(SELECTED_JSON):
            logger.error(f"找不到选股结果文件: {SELECTED_JSON}")
            return []
        
        with open(SELECTED_JSON, 'r', encoding='utf-8') as f:
            all_results = json.load(f)
        
        # 只保留有匹配结果的（status='ok'）
        matched_results = [r for r in all_results if r.get('status') == 'ok']
        
        logger.info(f"总事件数: {len(all_results)}, 有匹配结果: {len(matched_results)}")
        
        return matched_results
    
    def save_to_db(self, event: Dict) -> int:
        """
        将匹配成功的事件保存到数据库
        
        Args:
            event: 选股结果中的一条记录
        
        Returns:
            event_id
        """
        conn = self.db.get_target_connection()
        cursor = conn.cursor()
        
        
        cursor.execute('''
        INSERT INTO selected_events (
            event_title, event_index, publish_time, stock_code, stock_name,
            matched_by, matched_value
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            event.get('event_title', ''),           # event_title（来自JSON的event_title）
            event.get('event_index'),               # event_index
            event.get('event_date', ''),            # publish_time（选股脚本中已映射为event_date）
            event.get('stock_code', ''),            # stock_code
            event.get('stock_name', ''),            # stock_name
            event.get('matched_by', ''),            # matched_by
            event.get('matched_value', '')          # matched_value
        ))
        
        event_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        
        logger.info(f"已保存事件 #{event_id}: {event.get('event_title')} -> {event.get('stock_code')} {event.get('stock_name')}")
        
        return event_id
    
    def run(self):
        """
        运行完整流水线
        """
        logger.info("="*60)
        logger.info("开始处理流水线")
        logger.info("="*60)
        
        # 步骤1: 检查是否存在已生成的选股结果
        if self.check_selected_stocks_exists():
            logger.info("使用已有选股结果，跳过脚本执行")
        else:
            # 步骤2: 调用选股脚本
            if not self.run_select_stocks_script():
                logger.error("选股脚本执行失败，流水线终止")
                return
        
        # 步骤3: 加载选股结果
        matched_events = self.load_selected_results()
        
        if not matched_events:
            logger.warning("没有匹配到任何股票，流水线终止")
            return
        
        # 步骤4: 存入数据库
        logger.info(f"开始保存 {len(matched_events)} 条匹配结果到数据库...")
        
        saved_count = 0
        for i, event in enumerate(matched_events, 1):
            logger.info(f"[{i}/{len(matched_events)}] 保存: {event.get('event_title')} -> {event.get('stock_code')}")
            try:
                self.save_to_db(event)
                saved_count += 1
            except Exception as e:
                logger.error(f"保存失败: {e}")
        
        logger.info(f"流水线完成！成功保存 {saved_count}/{len(matched_events)} 条记录")
        
        return matched_events


# ==================== 主程序入口 ====================
def main():
    """主函数"""
    print("="*60)
    print("事件选股流水线 main_pipeline")
    print("="*60)
    
    # 检查输入文件是否存在
    if not os.path.exists(EVENTS_FILE):
        print(f"错误: 找不到事件文件 {EVENTS_FILE}")
        return
    
    # 创建流水线并运行
    pipeline = NewsPipeline(EVENTS_FILE, TARGET_DB)
    results = pipeline.run()
    
    # 打印简要结果
    print("\n" + "="*60)
    print("处理结果汇总:")
    print(f"  输出数据库: {TARGET_DB}")
    if results:
        print(f"  成功匹配事件数: {len(results)}")
        print("\n匹配示例:")
        for r in results[:5]:
            print(f"    - {r.get('event_title')} -> {r.get('stock_code')} {r.get('stock_name')} ({r.get('matched_by')})")
    else:
        print("  没有匹配到任何股票")
    print("="*60)


if __name__ == "__main__":
    main()