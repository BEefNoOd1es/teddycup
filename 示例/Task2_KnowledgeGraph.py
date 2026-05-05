import networkx as nx
import matplotlib.pyplot as plt
import matplotlib as mpl
import os

def create_knowledge_graph():
    # 设置中文字体
    plt.style.use('default')
    plt.rcParams['font.sans-serif'] = ['SimHei']  # 用来正常显示中文标签
    plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号
    
    # 初始化无向图
    G = nx.Graph()
    
    # 定义核心事件节点
    event = '重药控股: 医药分销领域重大业务突破'
    G.add_node(event, size=3500, color='lightcoral')
    
    # 模拟从NLP和知识图谱测算出的关联公司及其强度 (节点名, 关联缘由, 强度分)
    correlations = [
        ('重药控股 (000950)', '主导企业', 0.95),
        ('太极集团 (600129)', '重庆本地国资医药', 0.85),
        ('华润双鹤 (000078)', '同业分销', 0.76),
        ('九州通 (000989)', '医药流通竞品', 0.68),
        ('国药一致 (600511)', '全国分销网络', 0.62),
        ('大参林 (603233)', '下游零售连锁', 0.58)
    ]
    
    # 添加关联节点与边
    for stock, reason, score in correlations:
        G.add_node(stock, size=1800, color='skyblue')
        # 连线权重等于关联强度
        G.add_edge(event, stock, weight=score, label=f'{reason}\n(强度:{score:.2f})')
        
    # 设置布局方案 (使用spring_layout以获得发散形结构)
    pos = nx.spring_layout(G, seed=45, k=0.9)
    plt.figure(figsize=(12, 8))
    
    # 绘制节点
    node_sizes = [nx.get_node_attributes(G, 'size')[n] for n in G.nodes()]
    node_colors = [nx.get_node_attributes(G, 'color')[n] for n in G.nodes()]
    nx.draw_networkx_nodes(G, pos, node_size=node_sizes, node_color=node_colors, alpha=0.9, edgecolors='gray')
    
    # 绘制节点文本
    nx.draw_networkx_labels(G, pos, font_size=12, font_family='SimHei', font_weight='bold')
    
    # 绘制边 (根据权重加粗线条)
    edges = G.edges()
    weights = [G[u][v]['weight'] * 3.5 for u, v in edges]
    nx.draw_networkx_edges(G, pos, width=weights, edge_color='gray', style='dashed')
    
    # 绘制边的文本标签
    edge_labels = nx.get_edge_attributes(G, 'label')
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=10, label_pos=0.5)
    
    # 配置图表标题等信息
    plt.title('【典型事例】“重药控股分销突破”事件主体-上市公司关联图谱', fontsize=18, pad=20)
    plt.axis('off')
    plt.tight_layout()
    
    # 确保输出目录存在
    out_dir = r'E:\量化项目\ECO\阶段三\result'
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
        
    out_path = os.path.join(out_dir, '重药控股事件_知识图谱.png')
    plt.savefig(out_path, dpi=300, bbox_inches='tight')
    print(f'成功生成任务2事件知识图谱，已保存至: {out_path}')

if __name__ == '__main__':
    create_knowledge_graph()
