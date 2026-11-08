#!/usr/bin/env python3
"""Idempotently seed a reliable, free, browserless source set."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from user_db import UserDatabase


SOURCES = [
    ("https://openai.com/news/rss.xml", "OpenAI News", "Official lab announcements", "news"),
    ("https://deepmind.google/blog/rss.xml", "Google DeepMind", "Official research and product updates", "news"),
    ("https://research.google/blog/rss/", "Google Research", "Official research updates", "news"),
    ("https://machinelearning.apple.com/rss.xml", "Apple Machine Learning", "Official ML research", "news"),
    ("https://blogs.microsoft.com/ai/feed/", "Microsoft AI", "Official AI announcements", "news"),
    ("https://blogs.nvidia.com/blog/category/deep-learning/feed/", "NVIDIA AI", "AI chips and infrastructure", "news"),
    ("https://huggingface.co/blog/feed.xml", "Hugging Face", "Open-source AI ecosystem", "news"),
    ("https://huggingface.co/api/daily_papers", "Hugging Face Daily Papers", "Community-ranked research", "news"),
    ("https://news.ycombinator.com/rss", "Hacker News", "High-signal technology discussion", "discussion"),
    ("https://www.technologyreview.com/topic/artificial-intelligence/feed/", "MIT Technology Review AI", "Independent technology reporting", "news"),
    ("https://techcrunch.com/category/artificial-intelligence/feed/", "TechCrunch AI", "Companies, funding, and products", "news"),
]


def main():
    db = UserDatabase()
    for url, name, description, category in SOURCES:
        source_id = db.get_or_create_rss_source(url, name, description, category)
        print(f"{source_id}: {name}")


if __name__ == "__main__":
    main()
