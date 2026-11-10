"""Deterministic AI relevance gates for editorial feeds.

Topic-labelled RSS feeds can still contain cross-promoted general business or
technology stories.  These sources must carry an explicit AI signal in the
headline before an item reaches the LLM or a public export.
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
}

AI_TITLE_PATTERN = re.compile(
    r"(?i)(?:\b(?:ai|a\.i\.|artificial intelligence|machine learning|deep learning|"
    r"generative|llm|large language model|foundation model|agent(?:s|ic)?|chatbot|copilot|"
    r"robot(?:ics)?|robotaxi(?:s)?|autonomous driving|self-driving|gpu|npu|hbm|ai accelerator|semiconductor|chip|openai|coreai|anthropic|claude|gemini|deepseek|qwen|mistral|grok|xai|"
    r"hugging face|nvidia|sora|midjourney|stable diffusion)\b|"
    r"人工智能|大模型|机器学习|深度学习|生成式|智能体|机器人|人形机器人|算力|芯片|半导体|加速器|存储|自动驾驶|无人驾驶|智能驾驶|具身智能|"
    r"AI时代|AI 时代|Claude Code|Codex|AGI|模型训练|推理模型|数据中心|"
    r"深度求索|通义千问|豆包|文心一言|混元|盘古|百川|智谱)",
)


def passes_source_ai_filter(source_name, title):
    """Return False for a title-gated source without an explicit AI signal."""
    return source_name not in TITLE_GATED_SOURCES or bool(
        AI_TITLE_PATTERN.search(title or "")
    )
