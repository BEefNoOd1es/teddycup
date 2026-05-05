# 泰迪杯数据挖掘挑战赛 - 赛题项目说明文档

## 1. 项目简介

本项目为泰迪杯数据挖掘挑战赛的量化投资与事件驱动分析方案。项目核心分为两个阶段：早期验证阶段的基础回测模块，以及后续加入数据抓取、大语言模型分析和事件图谱构建的完整系统。

为方便评委和测试人员快速运行本项目，我们提供了 `示例/`文件夹。该文件夹包含了处理好的本地数据源，无需配置爬虫环境或 API Key 即可直接运行回测流水线，复现结果。

---

## 2. 目录结构说明

项目中包含三个主要的文件夹，分别对应不同的开发阶段和运行环境：

### 2.1 原始版本 (`程序原始版本/`)
包含了项目早期搭建的基础量化回测框架，主要用于初期代码逻辑的验证。使用固定的本地明文 JSON 和 DB 数据库流转。
```text
程序原始版本/
├── events_date.json        # 原始事件日期记录
├── structured_events.db    # 本地SQLite数据库源文件
├── main.py                 # 回测启动入口
├── BacktestEngine.py       # 基础回测引擎（包含基本收益率计算）
├── PortfolioManager.py     # 基础仓位及资金管理
├── RiskFilter.py           # 风险过滤组件模块
└── MetricsPlotter.py       # 回测结果指标绘图模块
```

### 2.2 完整系统源码 (`程序/`)
在该版本中，我们基于赛事要求新增了数据前置处理模块（爬虫与大模型抽取），并对回测引擎进行了大幅扩充：
```text
程序/
├── cls.py                       # [新增] 基于 Playwright 的舆情资讯爬虫模块
├── llm_analyze.py               # [新增] 接入大语言模型进行文本情感与实体提取
├── select_stocks_from_events.py # [新增] 通过事件筛选相关股票标的
├── main_pipeline.py             # [新增] 前置数据处理主干道，整合上述相关输出
├── Task2_KnowledgeGraph.py      # [新增] 基于 NetworkX 构建实体关联分析图谱
├── EventStudy_CAR.py            # [新增] 计算事件发生前后的异常收益率(CAR/AR)
├── main.py                      # [修改] 重构后的回测调度入口
├── BacktestEngine.py            # [修改] 扩充了更多绩效统计指标的回测引擎
├── PortfolioManager.py          # [修改] 增加换手率控制与滑点的投资组合管理
├── RiskFilter.py                # [修改] 新增波动率惩罚、熔断等风险过滤机制
└── MetricsPlotter.py            # [修改] 视觉与排版优化后的图表绘制代码
```

### 2.3 运行示例 (`示例/`)
为了解决代码运行时受限于网络环境、API Key 授权等问题，我们将 `程序/` 文件夹中的核心代码与静态脱敏数据组合，形成了一个开箱即用的脱机运行版本。
```text
程序跑通/
├── 日线数据.csv / 概念板块.csv    # 预先处理好的行情与板块特征数据
├── test2.json / *.db            # 经大模型标注后留存的本地样例数据集
├── main_pipeline.py             # 事件入库执行脚本
├── main.py                      # 回测与结果输出主程序
└── result/                      # 资金曲线、评价指标与交易日志的最终输出目录
```

---

## 3. 快速运行指南（以示例目录为例）

推荐在独立的 Python 环境（如 Conda 创建的 `python 3.9` / `3.10` 环境）下进行以下测试。

### 3.1 环境安装

打开终端/命令行，在项目根目录运行以下命令安装基础依赖库：

```bash
pip install pandas numpy matplotlib networkx
```

> **注意：** 示例文件夹由于使用的是本地处理好的数据，因此可以免安装 `playwright` 和 `openai` 等爬虫/大模型依赖包；如果需要运行 `程序/` 目录下的完整在线流程，则需额外安装并在代码内配置 API Key。

### 3.2 运行流程

我们将通过调用 `示例/` 目录中的主入口来复现测试结果。

**步骤 1：进入示例目录**
```bash
cd 程序跑通
```

**步骤 2：执行事件匹配流水线**
该步骤将读取 `test2.json` 中的缓存数据，根据知识图谱和相关性模块将事件映射到具体股票，并保存到数据库（`selected_events2.db`）。
```bash
python main_pipeline.py
```
*(如果该目录下已经存在结果数据库，也可跳过此步骤)*

**步骤 3：启动量化回测引擎**
该步骤依次调用风控过滤 (`RiskFilter`)、回测引擎 (`BacktestEngine`) 和图表生成 (`MetricsPlotter`)。
```bash
python main.py
```

运行完成后：
- 终端会打印出如最大回撤、夏普比率、年化收益率等回测指标。
- 程序的运行图表会弹出展示。
- 数据维度的结果（如 `account_value.csv`、`metrics_summary.csv` 以及各项交易明细）会自动保存在 `程序跑通/result/` 子目录中。

## 4. 如何一次性跑通全项目 (新环境运行指南)

为保证评委及其他合作者能够在本地**无报错、一次性跑通**全部流程，强烈建议基于干净的 `Conda` 环境进行部署。

### 第 1 步：环境隔离与创建
在命令行/终端中运行（需已安装 Anaconda/Miniconda，Python版本推荐 3.9 或 3.10）：
```bash
# 创建独立环境
conda create -n teddy_env python=3.10 -y
# 激活环境
conda activate teddy_env
```

### 第 2 步：安装依赖库与内核
在项目根目录（或新建一个 `requirements.txt` 并写入以下内容）：
```txt
pandas
numpy
matplotlib
networkx
playwright
openai
```
随后执行以下命令安装 Python 库，并配置浏览器内核：
```bash
pip install -r requirements.txt
# 这一步非常重要，用于安装 cls.py 需要的无头浏览器依赖！
playwright install  
```

### 第 3 步：配置 API Key (重要)
在运行前，请打开 `程序/llm_analyze.py` 和可能调用的 API 脚本，在代码内找到 `API_KEY = "你的密钥"` 或者设定系统环境变量，替换为实际的 OpenAI/DeepSeek 鉴权密钥。如无环境生成新事件，这一步可选。

### 第 4 步：顺序执行全流水线
1. **[生成端/非必循] 数据爬取与情绪标注：**
   ```bash
   python 程序/llm_analyze.py
   python 程序/Task2_KnowledgeGraph.py
   ```
2. **[集成干线] 将分析所得数据自动化过滤并组装至回测数据库：**
   ```bash
   python 程序/main_pipeline.py
   ```
3. **[回测终端] 运行核心选股及风控回测以输出可视化：**
   ```bash
   python 程序/main.py
   ```
*运行结束后，程序的表现（累积净值曲线、夏普、最大回撤等）都将在图形界面及终端依次抛出。*
