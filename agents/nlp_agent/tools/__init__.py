"""NLP Agent 内部工具集合。

| 模块 | 作用 | 重型依赖 |
|------|------|----------|
| `topic_keyword` | 葡萄牙语关键词主题分类（差评 review_score<=2，9 个业务可解释主题） | 无（PyYAML 可选） |
| `sentiment`     | 葡语情感分析；离线灌库 `review_sentiment` 表，在线毫秒级聚合     | torch / transformers / pysentimiento（仅 --backfill 时） |
| `topic_model`   | BERTopic 无监督主题；离线灌库 `review_topics(_meta)` 表，在线毫秒级聚合 | sentence-transformers / bertopic / hdbscan（仅 --backfill 时） |
| `wordcloud_data`| 好评 / 差评对比词云数据（1-gram + 葡语停用词），输出 `{word: weight}` | 无 |

约定：
- 所有重型依赖均**懒加载**（在需要训练 / 灌库的函数内部 `import`），
  以保证仅做"在线聚合 / 关键词分类 / 词云"时不需要安装 NLP 重型依赖。
- 重型依赖清单见项目根目录 `requirements-nlp.txt`。
"""