#!/usr/bin/env python3
"""Idempotently seed a reliable, free, browserless source set."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from user_db import UserDatabase


SOURCES = [
    ("https://openai.com/news/rss.xml", "OpenAI News", "Official model and company announcements", "news", 95),
    ("https://deepmind.google/blog/rss.xml", "Google DeepMind", "Official model, research, and product updates", "news", 95),
    ("https://blog.google/technology/ai/rss/", "Google AI", "Official AI model and product announcements", "news", 92),
    ("https://news.microsoft.com/source/topics/ai/feed/", "Microsoft AI", "Official AI company and product announcements", "news", 90),
    ("https://blogs.nvidia.com/blog/category/generative-ai/feed/", "NVIDIA Generative AI", "Official model, chip, and infrastructure news", "news", 88),
    ("https://engineering.fb.com/category/ai-research/feed/", "Meta AI Engineering", "Official AI research and engineering updates", "news", 88),
    ("https://aws.amazon.com/blogs/machine-learning/feed/", "AWS Machine Learning", "Official model platform and enterprise AI updates", "news", 84),
    ("https://research.google/blog/rss/", "Google Research", "Official research updates", "news", 82),
    ("https://machinelearning.apple.com/rss.xml", "Apple Machine Learning", "Official ML research", "news", 82),
    ("https://huggingface.co/blog/feed.xml", "Hugging Face", "Model releases and the open-source AI ecosystem", "news", 78),
    ("https://www.technologyreview.com/topic/artificial-intelligence/feed/", "MIT Technology Review AI", "Independent AI industry reporting", "news", 76),
    ("https://techcrunch.com/category/artificial-intelligence/feed/", "TechCrunch AI", "AI companies, funding, and products", "news", 74),
    ("https://huggingface.co/api/daily_papers", "Hugging Face Daily Papers", "Community-ranked research", "news", 65),
    ("https://news.ycombinator.com/rss", "Hacker News", "High-signal technology discussion", "discussion", 50),
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
