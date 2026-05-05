import time
import random
from datetime import datetime
import pandas as pd
from playwright.sync_api import sync_playwright
import hashlib
import re
import sqlite3
import os


class ClsSpiderFinal:

    def __init__(self):
        self.api_url = "https://www.cls.cn/v1/roll/get_roll_list"
        self.data_map = {}

    # ---------------- 签名算法 ----------------
    def _generate_sign(self, params):
        """根据 cls 接口签名算法生成 sign"""
        sorted_keys = sorted(k for k in params if k != "sign")  
        query_string = "&".join(f"{k}={params[k]}" for k in sorted_keys if params[k] is not None)
        sha1_hash = hashlib.sha1(query_string.encode("utf-8")).hexdigest()
        md5_hash = hashlib.md5(sha1_hash.encode("utf-8")).hexdigest()
        return md5_hash

    # ---------------- 数据处理 ----------------
    def process_data(self, roll_data, start_ts, end_ts):
        if not roll_data:
            return False, 0

        roll_data.sort(key=lambda x: x.get("ctime", 0), reverse=True)
        hit_bottom = False
        saved = 0

        for item in roll_data:
            ctime = item["ctime"]
            if ctime > end_ts:
                continue
            if ctime < start_ts:
                hit_bottom = True
                continue

            item["_time_str"] = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M:%S")

            # 爬取时就直接分开标题和正文
            content = item.get("content", "")
            # 如果有全角中括号开头，则认为是标题
            if content.startswith("【") and "】" in content:
                end_idx = content.find("】")
                item["标题"] = content[1:end_idx].strip()
                item["正文"] = content[end_idx + 1:].strip()
            else:
                # 没有标题的情况
                item["标题"] = ""
                item["正文"] = content.strip()

            if item["id"] not in self.data_map:
                self.data_map[item["id"]] = item
                saved += 1

        return hit_bottom, saved

    # ---------------- 加载已有数据的ID（从DB，用于去重） ----------------
    def load_existing_ids_from_db(self, db_file_path="test2.db"):
        """从SQLite数据库加载已有数据的ID，避免重复爬取"""
        existing_ids = set()
        if os.path.exists(db_file_path):
            try:
                conn = sqlite3.connect(db_file_path)
                cursor = conn.cursor()
                
                # 检查表是否存在
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='market_news'")
                if cursor.fetchone():
                    # 注意：原有表可能没有 id 字段，需要检查
                    cursor.execute("PRAGMA table_info(market_news)")
                    columns = [col[1] for col in cursor.fetchall()]
                    
                    if 'id' in columns:
                        cursor.execute("SELECT id FROM market_news")
                    else:
                        # 如果没有 id 字段，使用 publish_time + title 作为唯一标识
                        cursor.execute("SELECT publish_time, title FROM market_news")
                    
                    rows = cursor.fetchall()
                    if 'id' in columns:
                        for row in rows:
                            existing_ids.add(row[0])
                    else:
                        for row in rows:
                            # 用时间和标题组合作为唯一标识
                            existing_ids.add(f"{row[0]}_{row[1]}")
                    
                    print(f"✅ 从数据库加载了 {len(rows)} 条已有数据（用于去重）")
                conn.close()
            except Exception as e:
                print(f"⚠️ 加载数据库失败: {e}")
        return existing_ids

    # ---------------- 导出到数据库（增量追加，保持倒序） ----------------
    def export_to_db(self, db_filename="test2.db"):
        """
        导出数据到 SQLite 数据库
        只保留 title, content, publish_time 三列
        增量追加新数据，最终按发布时间倒序排列（晚发布在前）
        """
        if not self.data_map:
            print("没有抓取到数据，导出跳过")
            return

        # 过滤掉占位数据，只保留完整数据
        full_data = [item for item in self.data_map.values() if "正文" in item]
        
        if not full_data:
            print("没有完整数据可导出")
            return

        # 准备新数据（只保留三列）
        new_data = []
        for item in full_data:
            new_data.append({
                'title': item.get("标题", ""),
                'content': item.get("正文", ""),
                'publish_time': item.get("_time_str", "")
            })
        
        df_new = pd.DataFrame(new_data)
        
        # 连接数据库
        conn = sqlite3.connect(db_filename)
        
        # 读取已有数据
        try:
            df_existing = pd.read_sql("SELECT title, content, publish_time FROM market_news", conn)
            print(f"📖 读取到已有数据: {len(df_existing)} 条")
        except:
            df_existing = pd.DataFrame(columns=['title', 'content', 'publish_time'])
            print(f"📖 数据库为空或不存在，将创建新表")
        
        # 合并数据
        df_combined = pd.concat([df_new, df_existing], ignore_index=True)
        
        # 按 publish_time 倒序排序（晚发布在前）
        df_combined['publish_time'] = pd.to_datetime(df_combined['publish_time'])
        df_combined = df_combined.sort_values(by='publish_time', ascending=False)
        df_combined['publish_time'] = df_combined['publish_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # 去重（基于 title + publish_time）
        df_combined = df_combined.drop_duplicates(subset=['title', 'publish_time'], keep='first')
        
        # 写入数据库（替换整个表，保证倒序）
        df_combined.to_sql('market_news', conn, if_exists='replace', index=False)
        
        conn.commit()
        conn.close()
        
        print(f"\n📁 数据库已更新: {db_filename}")
        print(f"  - 新增数据: {len(df_new)} 条")
        print(f"  - 总记录数: {len(df_combined)} 条")
        print(f"  - 字段: title, content, publish_time")
        if len(df_combined) > 0:
            print(f"  - 最新新闻时间: {df_combined.iloc[0]['publish_time']}")
            print(f"  - 最旧新闻时间: {df_combined.iloc[-1]['publish_time']}")
            print(f"  - 排序验证: 按时间倒序存储 ✓")

    # ---------------- 导出到 CSV/Excel（完整数据） ----------------
    def export_to_csv_excel(self):
        """导出到 CSV 和 Excel 文件（完整数据）"""
        if not self.data_map:
            print("没有抓取到数据，导出跳过")
            return

        # 过滤掉占位数据
        full_data = [item for item in self.data_map.values() if "正文" in item]
        
        if not full_data:
            print("没有完整数据可导出")
            return

        df = pd.DataFrame(full_data)
        # 保留需要的列
        df = df[["id", "_time_str", "标题", "正文"]]
        df.rename(columns={"id": "ID", "_time_str": "时间"}, inplace=True)
        # 按时间倒序排序
        df = df.sort_values(by="时间", ascending=False)
        
        # 导出文件
        csv_filename = f"data_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        excel_filename = f"data_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        df.to_csv(csv_filename, index=False, encoding="utf-8-sig")
        df.to_excel(excel_filename, index=False)
        
        print(f"\n📁 CSV/Excel 文件已导出:")
        print(f"  - CSV文件: {csv_filename}")
        print(f"  - Excel文件: {excel_filename}")
        print(f"  - 共 {len(df)} 条记录")
        print(f"  - 字段: ID, 时间, 标题, 正文")

    # ---------------- 主抓取流程 ----------------
    def run_specific_range(self, start_str, end_str, db_file="test2.db"):
        """
        爬取指定时间范围的数据
        db_file: 已有数据的数据库文件路径，用于去重
        """
        start_ts = int(datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S").timestamp())
        end_ts = int(datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S").timestamp())

        # 加载已有数据的ID（用于去重）
        existing_ids = self.load_existing_ids_from_db(db_file)
        
        # 将已有ID标记到 data_map 中（用于去重）
        for nid in existing_ids:
            self.data_map[nid] = {"id": nid, "exists": True}

        with sync_playwright() as p:
            # 使用 Microsoft Edge 浏览器
            browser = p.chromium.launch(
                executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                headless=True  # 无头模式
            )
            page = browser.new_page()
            page.goto("https://www.cls.cn/telegraph")  # 先打开页面建立会话
            
            print("开始爬取数据...")
            print(f"目标时间范围: {start_str} 至 {end_str}")
            print(f"已有数据: {len(existing_ids)} 条")
            print("-" * 50)

            cursor = end_ts
            page_num = 1

            while True:
                # 构造接口参数
                params = {
                    "app": "CailianpressWeb",
                    "lastTime": cursor,
                    "last_time": cursor,
                    "os": "web",
                    "refresh_type": "1",
                    "rn": "50",
                    "sv": "8.4.6"
                }
                params["sign"] = self._generate_sign(params)

                # 使用浏览器上下文发请求
                response = page.request.get(self.api_url, params=params)
                if response.status != 200:
                    print(f"请求失败，状态码: {response.status}")
                    break

                res_json = response.json()
                if res_json.get("errno") != 0:
                    print(f"接口异常: {res_json}")
                    break

                roll_list = res_json.get("data", {}).get("roll_data", [])
                if not roll_list:
                    print("没有更多数据")
                    break

                hit_bottom, saved = self.process_data(roll_list, start_ts, end_ts)
                print(f"第 {page_num} 页 | 新增 {saved} 条 | 当前游标: {datetime.fromtimestamp(cursor).strftime('%Y-%m-%d %H:%M:%S')}")

                if hit_bottom:
                    print("已到达开始时间，爬取完成！")
                    break

                # 更新游标
                min_ctime = min(item["ctime"] for item in roll_list)
                cursor = min(min_ctime, cursor - 1)

                page_num += 1
                
                if page_num <= 5:
                    print(f"等待 {10} 秒后继续...")
                time.sleep(random.uniform(10, 15))

            print("-" * 50)
            new_count = len([i for i in self.data_map.values() if "正文" in i])
            print(f"抓取完成，本次新增 {new_count} 条数据")
            browser.close()


if __name__ == "__main__":
    spider = ClsSpiderFinal()
    try:
        spider.run_specific_range(
            start_str="2026-04-21 00:00:00",   # 开始时间（较早）
            end_str="2026-04-28 00:00:00",     # 结束时间（较晚）
            db_file="test2.db"                  # 数据库文件
        ) 
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断抓取，正在保存已抓取数据...")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
    finally:
        # 导出到数据库（增量追加，保持倒序）
        spider.export_to_db("test2.db")
        # 导出到 CSV/Excel（完整数据，按时间倒序）
        spider.export_to_csv_excel()