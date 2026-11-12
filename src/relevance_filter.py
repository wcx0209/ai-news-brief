"""Deterministic editorial relevance gates for broad feeds.

Topic-labelled RSS feeds can still contain cross-promoted general business or
technology stories. These broad sources must carry an explicit registered-field
signal in the headline before an item reaches the LLM or a public export.
"""

import re


TITLE_GATED_SOURCES = {
    "SCMP China Tech",
    "GeekPark 极客公园",
    "TMTPost 钛媒体",
    "iFanr 爱范儿",
    "ITmedia AI+",
    "The Guardian AI",
    "Ars Technica AI",
    "Dwarkesh Patel",
    "No Priors",
    "Latent Space",
    "Sequoia Capital",
    "Redpoint AI",
    "硅谷101",
    "十字路口 Crossing",
    "Sequoia Capital Articles",
    "Y Combinator Blog",
    "a16z Podcast",
    "Y Combinator",
    "Bessemer Venture Partners",
    "US NIST",
    "European Commission Digital Strategy",
    "UK AI Security Institute",
    "UK Science and Technology",
    "IMDA Singapore",
    "Tencent Newsroom",
    "SK hynix Newsroom",
    "Databricks",
    "Vercel",
    "EIA Today in Energy",
    "UK Atomic Energy Authority",
    "Utility Dive",
    "Advanced Science News",
    "NIMS Materials News",
    "Neuroscience News Neurotech",
    "The Transmitter",
    "International Water Management Institute",
    "Yale Environment 360",
    "Environmental Protection",
    "AgFunderNews",
    "FoodNavigator",
    "Green Queen",
    "Siemens Blog",
}

EDITORIAL_TITLE_PATTERN = re.compile(
    r"(?i)(?:\b(?:ai|a\.i\.|artificial intelligence|machine learning|deep learning|"
    r"generative|llm|large language model|foundation model|agent(?:s|ic)?|chatbot|copilot|"
    r"robot(?:ics)?|robotaxi(?:s)?|autonomous driving|self-driving|gpu|npu|hbm|ai accelerator|semiconductor|chip|openai|coreai|anthropic|claude|gemini|deepseek|qwen|mistral|grok|xai|"
    r"hugging face|nvidia|sora|midjourney|stable diffusion)\b|"
    r"人工智能|大模型|机器学习|深度学习|生成式|智能体|机器人|人形机器人|算力|芯片|半导体|加速器|存储|自动驾驶|无人驾驶|智能驾驶|具身智能|"
    r"AI时代|AI 时代|Claude Code|Codex|AGI|模型训练|推理模型|数据中心|"
    r"深度求索|通义千问|豆包|文心一言|混元|盘古|百川|智谱|"
    r"biotech(?:nology)?|synthetic biology|gene edit(?:ing)?|crispr|genomics?|"
    r"cell therapy|protein design|programmable life|biomanufacturing|"
    r"energy storage|solid.state batter(?:y|ies)|sodium.ion|geothermal|small modular reactor|nuclear fusion|"
    r"\b(?:batter(?:y|ies)|fusion|photovoltaics?|solar cells?|wind turbines?|renewables?|nuclear|smart grids?|virtual power plants?|hydrogen)\b|"
    r"quantum comput(?:ing|er)|quantum sens(?:ing|or)|quantum communication|quantum network|qubit|"
    r"reusable rocket|satellite internet|earth observation|in.orbit|launch vehicle|space economy|"
    r"advanced materials?|materials science|nanotechnology|two.dimensional materials?|self.healing materials?|metamaterials?|"
    r"\b(?:nanomaterials?|nanoelectronics|nanodevices?|bioelectronics|composites?|polymers?)\b|"
    r"neurotechnology|brain.computer interface|brain.machine interface|neural interface|neurostimulation|neural implant|"
    r"\b(?:neurotech|neuroengineering|neurodata|BCI|EEG|neuroprosthetics?|neuromodulation|neural decoding|neural recording|brain implants?|brain stimulation)\b|"
    r"carbon removal|direct air capture|desalination|water technology|green steel|climate engineering|"
    r"carbon capture|water treatment|wastewater|PFAS|pollution control|remediation|smart irrigation|water monitoring|recycling technolog|"
    r"agritech|foodtech|precision fermentation|cultivated meat|gene.edited crops?|agricultural robots?|alternative proteins?|"
    r"food technolog|food science|cell.cultured|plant.based|precision agriculture|crop sensing|autonomous tractors?|fermentation|"
    r"advanced manufacturing|additive manufacturing|3d print(?:ing|er)|digital twin|advanced packaging|smart factory|"
    r"industrial automation|smart factories|factory automation|digital fabrication|"
    r"生物技术|合成生物|基因编辑|基因组|细胞治疗|蛋白质设计|生物制造|可编程生命|"
    r"储能|固态电池|钠离子|地热|小型核反应堆|核聚变|"
    r"量子计算|量子传感|量子通信|量子网络|量子比特|"
    r"太空经济|可重复使用火箭|卫星互联网|地球观测|在轨|运载火箭|"
    r"新材料|材料科学|纳米技术|二维材料|自修复材料|超材料|"
    r"神经科技|脑机接口|神经刺激|神经植入|感觉恢复|"
    r"碳移除|直接空气捕集|海水淡化|水技术|工业脱碳|绿色钢铁|气候工程|"
    r"农业科技|食品科技|精准发酵|培养肉|基因编辑作物|农业机器人|替代蛋白|"
    r"新制造|先进制造|增材制造|3d打印|数字孪生|先进封装|自动化实验室|智能工厂)",
)

# Compatibility for existing imports and tests.
AI_TITLE_PATTERN = EDITORIAL_TITLE_PATTERN


def passes_source_ai_filter(source_name, title):
    """Return False when a broad source lacks an in-scope headline signal."""
    return source_name not in TITLE_GATED_SOURCES or bool(
        EDITORIAL_TITLE_PATTERN.search(title or "")
    )
