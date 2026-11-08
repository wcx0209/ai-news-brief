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
    ("https://raw.githubusercontent.com/alan-turing-institute/ai-rss-feeds/main/feeds/anthropic-news.xml", "Anthropic News", "Official Anthropic announcements via the Alan Turing Institute maintained feed", "news", 95),
    ("https://deepmind.google/blog/rss.xml", "Google DeepMind", "Official model, research, and product updates", "news", 95),
    ("https://blog.google/technology/ai/rss/", "Google AI", "Official AI model and product announcements", "news", 92),
    ("https://raw.githubusercontent.com/alan-turing-institute/ai-rss-feeds/main/feeds/mistral-news.xml", "Mistral AI", "Official French AI lab announcements via the Alan Turing Institute maintained feed", "news", 92),
    ("https://news.microsoft.com/source/topics/ai/feed/", "Microsoft AI", "Official AI company and product announcements", "news", 90),
    ("https://raw.githubusercontent.com/alan-turing-institute/ai-rss-feeds/main/feeds/spacex-ai-news.xml", "xAI News", "Official xAI announcements via the Alan Turing Institute maintained feed", "news", 90),
    ("https://blogs.nvidia.com/blog/category/generative-ai/feed/", "NVIDIA Generative AI", "Official model, chip, and infrastructure news", "news", 88),
    ("https://raw.githubusercontent.com/alan-turing-institute/ai-rss-feeds/main/feeds/cohere-blog.xml", "Cohere", "Official Canadian enterprise AI company updates via the Alan Turing Institute maintained feed", "news", 88),
    ("https://engineering.fb.com/category/ai-research/feed/", "Meta AI Engineering", "Official AI research and engineering updates", "news", 88),
    ("https://aws.amazon.com/blogs/machine-learning/feed/", "AWS Machine Learning", "Official model platform and enterprise AI updates", "news", 84),
    ("https://research.google/blog/rss/", "Google Research", "Official research updates", "news", 82),
    ("https://machinelearning.apple.com/rss.xml", "Apple Machine Learning", "Official ML research", "news", 82),
    ("https://huggingface.co/blog/feed.xml", "Hugging Face", "Model releases and the open-source AI ecosystem", "news", 78),

    # China: official channels and influential technology media
    ("https://github.com/deepseek-ai/DeepSeek-R1/releases.atom", "DeepSeek Releases", "Official DeepSeek model release announcements", "news", 94),
    ("https://seed.bytedance.com/en/", "ByteDance Seed", "Official ByteDance model and research announcements", "news", 94),
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
