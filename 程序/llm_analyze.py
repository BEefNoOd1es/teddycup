"""
llm_analyze.py
使用DeepSeek API分析 db 中的新闻事件，输出到 json
支持断点续跑（进度文件）
"""

import sqlite3
import json
import time
import os
from openai import OpenAI

# ==================== DeepSeek API配置 ====================
DEEPSEEK_API_KEY = "sk-d421fe382fd64dc58ba915a73a770f50"
BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"

# ==================== 数据库配置 ====================
DB_PATH = "test2.db"
TABLE_NAME = "market_news"
TEXT_COLUMN = "content"
TITLE_COLUMN = "title"

# ==================== 输出文件配置 ====================
OUTPUT_FILE = "test2.json"
PROGRESS_FILE = "progress.json"  # 进度文件

# ==================== 手动强制起始位置（0表示使用进度文件） ====================
FORCE_START_IDX = 0  # 设置为 0 则使用进度文件，设置为数字则强制从该位置开始

# 初始化客户端
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=BASE_URL
)

# ==================== Prompt模板 ====================
PROMPT_TEMPLATE = """
# Role
你是一位资深的A股量化金融分析师和文本数据挖掘专家。你的任务是阅读金融新闻/公告，提取核心事件，并严格按照【主办方事件分类体系】与【A股长板量化打分模型】提取结构化信息，输出合法的 JSON 格式。

# Background Knowledge (主办方分类体系与打分矩阵)

## 一、 主办方标准分类字典（强制匹配，严禁自造词汇！）

### 1. 【一级分类】与【二级分类】映射关系：
- **宏观政策类事件**: [货币政策, 财政政策, 国家发展规划, 国际贸易政策, 领导人重要讲话]
- **行业监管类事件**: [行业新规, 环保/安全检查, 行业标准制定, 反垄断/监管处罚]
- **公司类事件**: [财报发布, 重大资产重组, 管理层变动, 股票回购/分红, 产品发布/召回, 负面舆情, 重大合同签署, 在手订单类, 产品价格类]
- **行业景气事件**: [原材料价格波动, 供应链变化, 技术突破, 行业龙头动作]
- **地缘/国际事件**: [战争/冲突, 外交制裁/反制, 国际组织决议, 贸易协定签署]
- **宏观数据发布**: [经济数据, 就业数据, 消费/投资/出口数据]
- **自然灾害/卫生**: [疫情爆发, 自然灾害, 重大事故]
- **无实质事件/市场噪音**: [散户评论, 盘面描述] (注：此为系统防噪选项，处理主观股评时使用)

### 2. 【影响周期】仅限：[脉冲型, 中期型, 长尾型]

### 3. 【可预测性】仅限：[突发型, 预披露型]

### 4. 【行业属性】仅限：[宏观, 多行业, 周期类, 新能源类, 科技类, 消费类, 医药类, 军工类]

## 二、 核心打分公式（长板模型）

**最终总分 = 方向 × (加权基础分 + 长板增强分) × 确定性系数 × 位置系数 × 行业系数**

### 1. 预期差 (权重0.4, 1-5分): 
   - 5(完全意外)；4(明显超预期)；3(超预期有预热)；2(略超预期)；1(符合预期)

### 2. 深度 (权重0.4, 1-5分): 
   - 5(利润影响>30%)；4(15-30%)；3(5-15%)；2(<5%)；1(无实质影响)

### 3. 持续性 (权重0.2, 1-5分): 
   - 5(>3年)；4(1-3年)；3(6-12个月)；2(1-6个月)；1(数天)

**加权基础分 = (预期差 × 0.4 + 深度 × 0.4 + 持续性 × 0.2)**

### 4. 长板增强分 = 0.3 × max(预期差, 深度)

### 5. 乘数系数:
- **方向**: 利好(+1), 利空(-1)
- **确定性**: 1.0(已落地), 0.8(政策明确), 0.6(预期), 0.3(传闻)
- **位置**: 未提及默认 1.0；明确提及低位(利好1.2, 利空0.5)；高位(利好0.6, 利空1.3)
- **行业阶段与景气**: 综合乘数，默认 1.0。高景气成长期(如AI/新能源)可取 1.1~1.32，衰退期取 0.6~0.9

# Task & Rules

从文本中提取信息，遵循约束填充 JSON：

1. **event_title**: 凝练核心事件（15字以内），概括新闻主要内容。

2. **event_level_1, event_level_2, impact_cycle, predictability, industry_attribute**: 必须且只能从上述【主办方标准分类字典】中精准摘取一词，绝不可更改一字！

3. **sentiment**: 评估短期影响，仅限：[positive, negative, neutral]。

4. **score_breakdown**: 必须是一个包含以下字段的 JSON 对象：
   - expected_difference: {score: 数值, reason: "理由"}
   - depth: {score: 数值, reason: "理由"}
   - sustainability: {score: 数值, reason: "理由"}
   - weighted_base_score: {calculation: "计算公式", score: 数值}
   - long_board_enhancement: {calculation: "计算公式", score: 数值}
   - direction: 1 或 -1
   - certainty: 数值
   - location: 数值
   - industry_stage: 数值
   - final_score_calculation: "完整计算公式（用×号连接）"
   - strength: 数值（保留2位小数）

5. **strength**: 最终分数（带正负号），与 score_breakdown.strength 保持一致。

6. **related_concepts / related_companies**: 最多3个A股概念及提及的客观关联公司。

# Output Format constraints

**绝对要求**：只能输出一个纯粹的 JSON 对象，不能包含 markdown 代码块标记 (如 ```json)。

# Input

【新闻标题】: {title}
【新闻内容】: {content}
"""


# ==================== 进度管理函数 ====================

def save_progress(index):
    """保存当前处理到的索引"""
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump({'last_index': index}, f)

def load_progress():
    """加载上次处理到的索引"""
    # 优先使用强制设置
    if FORCE_START_IDX > 0:
        print(f"⚠️ 强制从第 {FORCE_START_IDX} 条开始")
        return FORCE_START_IDX
    
    # 否则读取进度文件
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('last_index', 0)
        except:
            pass
    return 0

def clear_progress():
    """清除进度文件（处理完成后调用）"""
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)


# ==================== DeepSeek API调用函数 ====================

def call_deepseek(prompt):
    """调用DeepSeek API"""
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=2000,
            stream=False
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"  API调用异常: {e}")
        return None


# ==================== 单条新闻分析 ====================

def analyze_news(news_title: str, news_content: str) -> dict:
    """分析单条新闻，返回结构化结果，失败返回 None"""
    prompt = PROMPT_TEMPLATE.replace("{title}", news_title).replace("{content}", news_content)
    
    max_retries = 3
    for attempt in range(max_retries):
        result_text = call_deepseek(prompt)
        
        if result_text:
            try:
                result_text = result_text.replace("```json", "").replace("```", "").strip()
                result = json.loads(result_text)
                
                if 'strength' in result:
                    result['strength'] = float(result['strength'])
                else:
                    result['strength'] = 0
                
                return result
            except json.JSONDecodeError:
                print(f"  JSON解析失败 (尝试 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2)
        else:
            print(f"  API调用失败 (尝试 {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(5)
    
    print(f"  所有重试失败，跳过此新闻")
    return None


# ==================== 读取数据库 ====================

def load_news():
    """从数据库加载所有新闻（标题+内容+发布时间）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = f"SELECT {TITLE_COLUMN}, {TEXT_COLUMN}, publish_time FROM {TABLE_NAME} WHERE {TEXT_COLUMN} IS NOT NULL"
    cursor.execute(query)

    rows = cursor.fetchall()
    conn.close()

    news_list = []
    for row in rows:
        title = row[0] if row[0] else ''
        content = row[1] if row[1] else ''
        publish_time = row[2] if row[2] else ''
        if content:
            news_list.append({
                'title': title,
                'content': content,
                'publish_time': publish_time
            })

    print(f"数据库新闻总数: {len(rows)}")
    print(f"待处理新闻数量: {len(news_list)}")
    return news_list


# ==================== 批量处理 ====================

def process_all_news():
    """处理所有新闻，支持断点续跑"""
    print("="*60)
    print("开始处理新闻事件 (DeepSeek API)")
    print(f"模型: {MODEL}")
    print("="*60)
    
    # 加载新闻
    all_news = load_news()
    
    # 加载已有结果
    results = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                results = json.load(f)
                print(f"发现已有结果，当前有 {len(results)} 条记录")
        except:
            pass
    
    # 加载进度（已处理的总条数，包括失败的）
    start_idx = load_progress()
    print(f"将从第 {start_idx + 1} 条开始处理")
    
    # 如果已经处理完所有新闻，提示并退出
    if start_idx >= len(all_news):
        print("✅ 所有新闻已处理完成！")
        return
    
    # 处理新闻
    success_count = 0
    fail_count = 0
    
    for i, news in enumerate(all_news[start_idx:], start_idx + 1):
        print(f"\n[{i}/{len(all_news)}] 处理: {news['title'][:50] if news['title'] else '无标题'}...")
        
        result = analyze_news(news['title'], news['content'])
        
        if result:
            # 添加原始信息
            result['original_title'] = news['title']
            result['original_content'] = news['content'][:500] + "..." if len(news['content']) > 500 else news['content']
            result['publish_time'] = news['publish_time']
            
            results.append(result)
            success_count += 1
            print(f"  ✅ 成功 (strength={result.get('strength', 0):.2f})")
        else:
            fail_count += 1
            print(f"  ❌ 失败，跳过")
        
        # 每处理一条，保存进度（无论成功还是失败）
        save_progress(i)
        
        # 每10条保存结果文件
        if i % 10 == 0:
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"\n📁 已保存 {len(results)} 条结果，进度已更新到第 {i} 条")
        
        # 避免请求过快
        time.sleep(1)
    
    # 最终保存
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # 处理完成，清除进度文件
    clear_progress()
    
    print("\n" + "="*60)
    print("处理完成！")
    print(f"✅ 成功: {success_count} 条")
    print(f"❌ 失败: {fail_count} 条")
    print(f"📁 输出文件: {OUTPUT_FILE}")
    print("="*60)


# =========================
# 主程序
# =========================

def main():
    process_all_news()


if __name__ == "__main__":
    main()