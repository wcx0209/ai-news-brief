#!/usr/bin/env python3
"""Idempotently seed a reliable, free, browserless source set."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from user_db import UserDatabase


SOURCES = [
    # Global AI companies and labs
    ("https://openai.com/news/rss.xml", "OpenAI News", "Official model and company announcements", "news", 95),
    ("https://www.anthropic.com/news", "Anthropic News", "[FIRST_PARTY] Official Anthropic company and model announcements", "news", 98),
    ("https://www.anthropic.com/research", "Anthropic Research", "[FIRST_PARTY] Official Anthropic research, engineering, safety, and societal-impact updates", "research", 94),
    ("https://raw.githubusercontent.com/alan-turing-institute/ai-rss-feeds/main/feeds/anthropic-news.xml", "Anthropic News Mirror", "Fallback Anthropic announcements via the Alan Turing Institute maintained mirror", "news", 78),
    ("https://deepmind.google/blog/rss.xml", "Google DeepMind", "Official model, research, and product updates", "news", 95),
    ("https://blog.google/technology/ai/rss/", "Google AI", "Official AI model and product announcements", "news", 92),
    ("https://mistral.ai/news/", "Mistral AI News", "[FIRST_PARTY] Official Mistral model, product, research, and company announcements", "news", 96),
    ("https://raw.githubusercontent.com/alan-turing-institute/ai-rss-feeds/main/feeds/mistral-news.xml", "Mistral AI Mirror", "Fallback Mistral announcements via the Alan Turing Institute maintained mirror", "news", 76),
    ("https://news.microsoft.com/source/topics/ai/feed/", "Microsoft AI", "Official AI company and product announcements", "news", 90),
    ("https://x.ai/news", "xAI News", "[FIRST_PARTY] Official xAI model, product, research, and company announcements", "news", 96),
    ("https://raw.githubusercontent.com/alan-turing-institute/ai-rss-feeds/main/feeds/spacex-ai-news.xml", "xAI News Mirror", "Fallback xAI announcements via the Alan Turing Institute maintained mirror", "news", 74),
    ("https://blogs.nvidia.com/blog/category/generative-ai/feed/", "NVIDIA Generative AI", "Official model, chip, and infrastructure news", "news", 88),
    ("https://cohere.com/blog", "Cohere Blog", "[FIRST_PARTY] Official Cohere model, product, research, and company updates", "news", 92),
    ("https://raw.githubusercontent.com/alan-turing-institute/ai-rss-feeds/main/feeds/cohere-blog.xml", "Cohere Blog Mirror", "Fallback Cohere updates via the Alan Turing Institute maintained mirror", "news", 74),
    ("https://research.meta.ai/", "Meta AI Research", "[FIRST_PARTY] Official Meta frontier-model and AI research announcements", "models", 98),
    ("https://about.fb.com/news/tag/ai/", "Meta Newsroom AI", "[FIRST_PARTY] Official Meta AI product and company announcements", "news", 94),
    ("https://engineering.fb.com/category/ai-research/feed/", "Meta AI Engineering", "[FIRST_PARTY] Official Meta AI research and engineering updates", "research", 90),
    ("https://aws.amazon.com/blogs/machine-learning/feed/", "AWS Machine Learning", "Official model platform and enterprise AI updates", "news", 84),
    ("https://research.google/blog/rss/", "Google Research", "Official research updates", "news", 82),
    ("https://machinelearning.apple.com/rss.xml", "Apple Machine Learning", "Official ML research", "news", 82),
    ("https://huggingface.co/blog/feed.xml", "Hugging Face", "Model releases and the open-source AI ecosystem", "news", 78),

    # Founder-led "neolabs": first-party updates from young frontier labs whose
    # founding teams have led major models, landmark research, or AI products.
    # Most publish HTML indexes rather than RSS; rss_fetcher has a narrow,
    # same-domain adapter for these official pages.
    ("https://thinkingmachines.ai/news/", "Thinking Machines Lab", "[FIRST_PARTY] Founder-led frontier lab; official model, product, and company announcements", "news", 94),
    ("https://www.worldlabs.ai/blog", "World Labs", "[FIRST_PARTY] Fei-Fei Li's spatial-intelligence lab; official research and product updates", "news", 94),
    ("https://sakana.ai/feed.xml", "Sakana AI", "[FIRST_PARTY] Founder-led Japanese frontier lab; official model, agent, product, and research updates", "news", 94),
    ("https://www.pi.website/blog", "Physical Intelligence", "[FIRST_PARTY] Founder-led robotics foundation-model lab; official model and research updates", "news", 92),
    ("https://reflection.ai/blog", "Reflection AI", "[FIRST_PARTY] Former DeepMind-led open frontier intelligence lab; official model and research updates", "news", 92),
    ("https://www.lila.ai/news", "Lila Sciences", "[FIRST_PARTY] Founder-led scientific-superintelligence lab; official autonomous-science updates", "news", 90),
    ("https://oumi.ai/blog/rss.xml", "Oumi", "[FIRST_PARTY] Former Google Gemini and AI Safety leaders; official open-model platform updates", "news", 88),

    # Official model release channels. GitHub Atom feeds are used where a
    # vendor does not publish a stable newsroom RSS feed.
    ("https://github.com/meta-llama/llama-models/releases.atom", "Meta Llama Releases", "[FIRST_PARTY] Official Meta Llama model releases", "models", 94),
    ("https://github.com/Stability-AI/generative-models/releases.atom", "Stability AI Releases", "[FIRST_PARTY] Official Stability AI model releases", "models", 88),
    ("https://stability.ai/news-updates?format=rss", "Stability AI News", "[FIRST_PARTY] Official Stability AI model, product, partnership, and company announcements", "news", 92),

    # China: official channels and influential technology media
    ("https://github.com/deepseek-ai/DeepSeek-R1/releases.atom", "DeepSeek Releases", "Official DeepSeek model release announcements", "news", 94),
    ("https://seed.bytedance.com/en/", "ByteDance Seed", "Official ByteDance model and research announcements", "news", 94),
    ("https://www.tencent.com/zh-cn/newsroom/", "Tencent Newsroom", "[FIRST_PARTY] Official Tencent corporate, Hunyuan model, product, and research announcements", "news", 98),
    ("https://github.com/QwenLM/Qwen3/releases.atom", "Qwen Releases", "[FIRST_PARTY] Official Alibaba Qwen model releases", "models", 96),
    ("https://qwen.ai/blog", "Qwen Blog", "[FIRST_PARTY] Official Alibaba Qwen model, product, and research announcements", "models", 98),
    ("https://github.com/moonshotai/Kimi-K2/releases.atom", "Kimi Releases", "[FIRST_PARTY] Official Moonshot AI Kimi model releases", "models", 94),
    ("https://github.com/zai-org/GLM-4.5/releases.atom", "Z.ai GLM Releases", "[FIRST_PARTY] Official Z.ai GLM model releases", "models", 94),
    ("https://github.com/MiniMax-AI/MiniMax-M2/releases.atom", "MiniMax Releases", "[FIRST_PARTY] Official MiniMax model releases", "models", 92),
    ("https://www.minimax.io/news", "MiniMax News", "[FIRST_PARTY] Official MiniMax model, product, research, and company announcements", "models", 96),
    ("https://github.com/Tencent-Hunyuan/Hunyuan-A13B/releases.atom", "Tencent Hunyuan Releases", "[FIRST_PARTY] Official Tencent Hunyuan open-model releases", "models", 94),
    ("https://github.com/PaddlePaddle/ERNIE/releases.atom", "Baidu ERNIE Releases", "[FIRST_PARTY] Official Baidu ERNIE model releases", "models", 92),
    ("https://ernie.baidu.com/", "Baidu ERNIE Blog", "[FIRST_PARTY] Official Baidu ERNIE model and research announcements", "models", 96),
    ("https://www.qbitai.com/feed", "QbitAI 量子位", "Influential Chinese AI industry and model reporting", "news", 90),
    ("https://www.scmp.com/rss/36/feed", "SCMP China Tech", "China and Asian technology industry reporting", "news", 88),
    ("https://www.geekpark.net/rss", "GeekPark 极客公园", "Chinese technology companies, products, and startup reporting", "news", 84),
    ("https://www.tmtpost.com/rss", "TMTPost 钛媒体", "Chinese technology, business, and policy reporting", "news", 83),
    ("https://www.ifanr.com/feed", "iFanr 爱范儿", "Chinese technology products and AI industry reporting", "news", 82),

    # High-impact media beyond the United States
    ("https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", "ITmedia AI+", "Japanese AI industry and product reporting", "news", 86),
    ("https://www.theguardian.com/technology/artificialintelligenceai/rss", "The Guardian AI", "UK and global AI policy, business, and society reporting", "news", 85),
    ("https://www.lemonde.fr/en/artificial-intelligence/rss_full.xml", "Le Monde AI", "French and European AI policy and society reporting", "news", 84),
    ("https://analyticsindiamag.com/feed", "Analytics India Magazine", "Indian AI companies, models, and enterprise adoption", "news", 84),
    ("https://www.livemint.com/rss/AI", "Mint AI", "Indian business and policy reporting on artificial intelligence", "news", 82),
    ("https://aisingapore.org/feed/", "AI Singapore", "Official Singapore AI ecosystem, research, and industry updates", "news", 82),

    # AI infrastructure and accelerator vendors: official engineering blogs,
    # newsrooms, and product release feeds.
    ("https://www.graphcore.ai/posts/rss.xml", "Graphcore", "[FIRST_PARTY] Official Graphcore AI accelerator and software updates", "business", 88),
    ("https://sambanova.ai/blog/rss.xml", "SambaNova", "[FIRST_PARTY] Official SambaNova AI systems, models, and enterprise platform updates", "business", 88),
    ("https://news.skhynix.com/feed/", "SK hynix Newsroom", "[FIRST_PARTY] Official SK hynix AI memory and semiconductor announcements", "business", 86),
    ("https://github.com/ROCm/ROCm/releases.atom", "AMD ROCm Releases", "[FIRST_PARTY] Official AMD AI compute software-stack releases", "open_source", 92),
    ("https://www.amd.com/en/blogs.html", "AMD Blogs", "[FIRST_PARTY] Official AMD AI accelerator, data-center, client-AI, and software announcements", "business", 90),
    ("https://github.com/openvinotoolkit/openvino/releases.atom", "Intel OpenVINO Releases", "[FIRST_PARTY] Official Intel AI inference software releases", "open_source", 90),
    ("https://github.com/quic/ai-hub-models/releases.atom", "Qualcomm AI Hub Releases", "[FIRST_PARTY] Official Qualcomm on-device AI model releases", "open_source", 90),
    ("https://www.qualcomm.com/news/onq", "Qualcomm OnQ", "[FIRST_PARTY] Official Qualcomm on-device, edge, and physical-AI announcements", "business", 90),
    ("https://github.com/Cerebras/modelzoo/releases.atom", "Cerebras Model Zoo Releases", "[FIRST_PARTY] Official Cerebras AI model and training-stack releases", "open_source", 90),
    ("https://www.cerebras.ai/blog", "Cerebras Blog", "[FIRST_PARTY] Official Cerebras AI chip, inference, model, and company announcements", "business", 92),
    ("https://github.com/groq/groq-python/releases.atom", "Groq Platform Releases", "[FIRST_PARTY] Official Groq inference-platform SDK releases", "open_source", 88),
    ("https://groq.com/blog", "Groq Blog", "[FIRST_PARTY] Official Groq inference, infrastructure, partnership, and company announcements", "business", 90),
    ("https://github.com/tenstorrent/tt-metal/releases.atom", "Tenstorrent TT-Metal Releases", "[FIRST_PARTY] Official Tenstorrent accelerator software releases", "open_source", 88),
    ("https://github.com/aws-neuron/aws-neuron-sdk/releases.atom", "AWS Neuron Releases", "[FIRST_PARTY] Official AWS Trainium and Inferentia software releases", "open_source", 90),
    ("https://github.com/ARM-software/kleidiai/releases.atom", "Arm KleidiAI Releases", "[FIRST_PARTY] Official Arm edge-AI kernel releases", "open_source", 86),

    # AI software, data, cloud, and developer-platform vendors.
    ("https://github.blog/ai-and-ml/feed/", "GitHub AI", "[FIRST_PARTY] Official GitHub AI, Copilot, and developer-platform updates", "news", 90),
    ("https://blog.cloudflare.com/tag/ai/rss/", "Cloudflare AI", "[FIRST_PARTY] Official Cloudflare AI infrastructure and developer-platform updates", "news", 88),
    ("https://www.databricks.com/feed", "Databricks", "[FIRST_PARTY] Official Databricks data and AI platform updates", "news", 90),
    ("https://www.pinecone.io/blog/rss/", "Pinecone", "[FIRST_PARTY] Official Pinecone vector database and AI retrieval updates", "news", 84),
    ("https://wandb.ai/fully-connected/rss.xml", "Weights & Biases", "[FIRST_PARTY] Official Weights & Biases model-development platform updates", "news", 84),
    ("https://vercel.com/atom", "Vercel", "[FIRST_PARTY] Official Vercel AI SDK and application-platform updates", "news", 84),
    ("https://github.com/langchain-ai/langchain/releases.atom", "LangChain Releases", "[FIRST_PARTY] Official LangChain agent framework releases", "open_source", 86),
    ("https://www.langchain.com/blog", "LangChain Blog", "[FIRST_PARTY] Official LangChain, LangGraph, LangSmith, and company announcements", "news", 88),
    ("https://github.com/run-llama/llama_index/releases.atom", "LlamaIndex Releases", "[FIRST_PARTY] Official LlamaIndex data and agent framework releases", "open_source", 84),
    ("https://www.llamaindex.ai/blog", "LlamaIndex Blog", "[FIRST_PARTY] Official LlamaIndex product, agent, parsing, and research announcements", "news", 86),
    ("https://github.com/microsoft/autogen/releases.atom", "Microsoft AutoGen Releases", "[FIRST_PARTY] Official Microsoft AutoGen agent framework releases", "open_source", 88),
    ("https://github.com/crewAIInc/crewAI/releases.atom", "CrewAI Releases", "[FIRST_PARTY] Official CrewAI multi-agent platform releases", "open_source", 84),
    ("https://crewai.com/blog", "CrewAI Blog", "[FIRST_PARTY] Official CrewAI platform, enterprise, evaluation, and company announcements", "news", 84),
    ("https://github.com/vllm-project/vllm/releases.atom", "vLLM Releases", "[FIRST_PARTY] Official vLLM inference-engine releases", "open_source", 88),
    ("https://github.com/huggingface/transformers/releases.atom", "Hugging Face Transformers Releases", "[FIRST_PARTY] Official Hugging Face model-library releases", "open_source", 88),
    ("https://github.com/ollama/ollama/releases.atom", "Ollama Releases", "[FIRST_PARTY] Official Ollama local-model runtime releases", "open_source", 86),
    ("https://ollama.com/blog", "Ollama Blog", "[FIRST_PARTY] Official Ollama model support, product, cloud, and company announcements", "news", 88),

    # High-impact international AI media
    ("https://www.technologyreview.com/topic/artificial-intelligence/feed/", "MIT Technology Review AI", "Independent AI industry reporting", "news", 76),
    ("https://techcrunch.com/category/artificial-intelligence/feed/", "TechCrunch AI", "AI companies, funding, and products", "news", 74),
    ("https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "The Verge AI", "High-impact AI product, company, and policy reporting", "news", 86),
    ("https://www.wired.com/feed/tag/ai/latest/rss", "WIRED AI", "AI technology, business, and society reporting", "news", 85),
    ("https://feeds.arstechnica.com/arstechnica/technology-lab", "Ars Technica AI", "Technical AI products, research, and industry analysis", "news", 83),
    # Academic AI: primary paper feeds and university research communities.
    # These sources use a dedicated academic prompt. Publication is capped at
    # two high-confidence items in the public feed; source prestige affects
    # confidence only, never the Polyemergence importance score.
    ("https://huggingface.co/api/daily_papers", "Hugging Face Daily Papers", "Community-ranked AI papers with code and public artifacts", "academia", 72),
    ("https://rss.arxiv.org/rss/cs.AI", "arXiv Artificial Intelligence", "Primary preprints in artificial intelligence", "academia", 76),
    ("https://rss.arxiv.org/rss/cs.LG", "arXiv Machine Learning", "Primary preprints in machine learning", "academia", 76),
    ("https://rss.arxiv.org/rss/cs.CL", "arXiv Computation and Language", "Primary preprints in language models and computational linguistics", "academia", 76),
    ("https://bair.berkeley.edu/blog/feed.xml", "Berkeley AI Research", "First-party research explanations from the Berkeley AI Research Lab", "academia", 90),
    ("https://blog.ml.cmu.edu/feed/", "Carnegie Mellon ML Blog", "First-party machine-learning research from Carnegie Mellon", "academia", 90),
    ("https://www.csail.mit.edu/rss.xml", "MIT CSAIL", "First-party AI and computer-science research from MIT CSAIL", "academia", 90),

    # Biotechnology and programmable life: primary research, academic labs,
    # and specialist industry reporting. Ordinary healthcare and pharma news
    # remains out of scope unless a platform technology is the core subject.
    ("https://www.nature.com/nbt.rss", "Nature Biotechnology", "Peer-reviewed biotechnology research and analysis", "biotech", 94),
    ("https://www.broadinstitute.org/rss/news-blog-feed", "Broad Institute", "[FIRST_PARTY] Official genomics, gene editing, therapeutic platform, and computational biology research", "biotech", 92),
    ("https://news.mit.edu/topic/biological-engineering", "MIT Biological Engineering", "[FIRST_PARTY] Official MIT biological engineering, synthetic biology, and programmable-life research", "biotech", 90),
    ("https://www.statnews.com/category/biotech/feed", "STAT Biotech", "High-impact biotechnology science, company, and policy reporting", "biotech", 84),
    ("https://www.fiercebiotech.com/rss/biotech/xml", "Fierce Biotech", "Biotechnology platforms, clinical science, companies, and financing", "biotech", 82),
    ("https://www.biospace.com/drug-development.rss", "BioSpace Drug Development", "Drug-development platforms, translational science, and biotechnology industry reporting", "biotech", 76),

    # Venture capital and startup ecosystem: first-party market theses, founder
    # guidance, and interviews. These are broad feeds, so the pipeline applies
    # the title-level AI gate before spending an LLM call on an item.
    ("https://www.sequoiacap.com/feed/", "Sequoia Capital Articles", "Official investment perspectives on AI companies, markets, and infrastructure", "news", 86),
    ("https://www.ycombinator.com/blog/rss.xml", "Y Combinator Blog", "Official startup, founder, and AI ecosystem updates", "news", 84),
    ("https://feeds.simplecast.com/JGE3yC0V", "a16z Podcast", "Official technology and investment conversations from Andreessen Horowitz", "interviews", 80),

    # Government technology and AI governance: official primary sources from
    # high-impact regulatory jurisdictions. Broad departmental feeds remain
    # subject to the same AI-title gate to exclude unrelated announcements.
    ("https://www.nist.gov/news-events/news/rss.xml", "US NIST", "Official US AI standards, safety, evaluation, and technology policy updates", "news", 90),
    ("https://digital-strategy.ec.europa.eu/en/rss.xml", "European Commission Digital Strategy", "Official EU AI Office, AI Act, digital policy, and regulatory updates", "news", 92),
    ("https://www.gov.uk/government/organisations/ai-security-institute.atom", "UK AI Security Institute", "Official frontier AI safety research, evaluations, and policy updates", "news", 92),
    ("https://www.gov.uk/government/organisations/department-for-science-innovation-and-technology.atom", "UK Science and Technology", "Official UK technology, innovation, and AI policy announcements", "news", 84),

    # High-signal AI interviews and long-form conversations. Keep this set small:
    # video transcripts are expensive to collect and should complement, not crowd out, news.
    ("https://www.youtube.com/feeds/videos.xml?channel_id=UCKV2yWPB3wn0RTZh3cTD8YA", "硅谷101", "Original Chinese long-form interviews on AI research, companies, infrastructure, and markets", "interviews", 92),
    ("https://www.youtube.com/feeds/videos.xml?channel_id=UCqoy3g7ZH24j2mLOq_nbKrQ", "十字路口 Crossing", "Original Chinese video-podcast interviews with AI founders, researchers, builders, and creators", "interviews", 88),
    ("https://www.youtube.com/feeds/videos.xml?channel_id=UCZa18YV7qayTh-MRIrBhDpA", "Dwarkesh Patel", "Long-form interviews with AI researchers, founders, and policymakers", "interviews", 88),
    ("https://www.youtube.com/feeds/videos.xml?channel_id=UCSI7h9hydQ40K5MJHnCrQvw", "No Priors", "Interviews with AI founders, researchers, and investors", "interviews", 86),
    ("https://www.youtube.com/feeds/videos.xml?channel_id=UCxBcwypKK-W3GHd_RZ9FZrQ", "Latent Space", "AI engineering interviews and technical conversations", "interviews", 84),
    ("https://www.youtube.com/feeds/videos.xml?channel_id=UCWrF0oN6unbXrWsTN7RctTw", "Sequoia Capital", "Training Data interviews on AI companies, products, and markets", "interviews", 82),
    ("https://www.youtube.com/feeds/videos.xml?channel_id=UCUl-s_Vp-Kkk_XVyDylNwLA", "Redpoint AI", "Unsupervised Learning interviews with AI builders and researchers", "interviews", 82),
    ("https://www.youtube.com/feeds/videos.xml?channel_id=UCcefcZRL2oaA_uBNeo5UOWg", "Y Combinator", "Official AI startup, founder, and technical interviews", "interviews", 84),
    ("https://www.youtube.com/feeds/videos.xml?channel_id=UCKuHAxZoh99t8uyPQhoDR3A", "Bessemer Venture Partners", "Official cloud, vertical AI, and startup market conversations", "interviews", 78),
    ("https://www.youtube.com/feeds/videos.xml?channel_id=UCeW5IMmy5uUzEv3f4ijV2cg", "IMDA Singapore", "Official Singapore AI adoption, governance, and digital policy updates", "news", 88),
]


def main():
    db = UserDatabase()
    for url, name, description, category, importance in SOURCES:
        source_id = db.get_or_create_rss_source(
            url, name, description, category, importance_score=importance
        )
        print(f"{source_id}: {name}")


if __name__ == "__main__":
    main()
