-- =============================================================================
--  review_topics + review_topic_meta 双表 DDL
--  ---------------------------------------------------------------------------
--  归属：NLP / 评论洞察 Agent (`agents/nlp_agent`)
--  作用：存放 BERTopic 无监督主题建模的离线训练结果，供在线 Agent 毫秒级查询。
--
--  与关键词法的区别：
--    - 关键词法（topic_keyword.py）：8 类预设主题，覆盖率约 35%，60% 评论落到 other
--    - BERTopic（topic_model.py）：自动从葡语原文里发现 15-25 个真实主题（无预设）
--
--  灌库流程：
--    python -m agents.nlp_agent.tools.topic_model --backfill
--      ├─ 抽取 review_score<=2 的差评（约 1.4 万条带文本）
--      ├─ 多语种 sentence-transformers embedding（paraphrase-multilingual-MiniLM-L12-v2）
--      ├─ UMAP 降维 → HDBSCAN 聚类 → 每条评论得到 topic_id
--      ├─ c-TF-IDF 给每个主题提取 Top 关键词
--      └─ 双表落库：评论级 review_topics + 主题级 review_topic_meta
--
--  在线读取：
--    aggregate_bertopic() 直接 JOIN review_topics + order_reviews + products，
--    按 (品类, 主题) 双维度 GROUP BY，输出"X 品类的差评 38% 是物流损坏"这种结论。
-- =============================================================================

DROP TABLE IF EXISTS review_topics;
DROP TABLE IF EXISTS review_topic_meta;

-- ── 表 1：评论 → 主题 ID（每条差评一行）────────────────────────────
CREATE TABLE review_topics (
    review_id     VARCHAR(64) NOT NULL COMMENT '评论ID（与 order_reviews.review_id 1:1）',
    topic_id      INT         NOT NULL COMMENT '主题ID（-1 表示离群点 / 未归类）',
    probability   FLOAT       DEFAULT NULL COMMENT '评论属于该主题的置信度（HDBSCAN 软概率）',
    model_name    VARCHAR(64) NOT NULL COMMENT '模型 + embedding 标识',
    created_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '推理时间',

    PRIMARY KEY (review_id),
    KEY idx_topic_id (topic_id),
    KEY idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='每条差评的 BERTopic 主题归属（NLP Agent 离线灌库）';


-- ── 表 2：主题 → 关键词 / 大小（每个主题一行）─────────────────────
CREATE TABLE review_topic_meta (
    topic_id       INT          NOT NULL COMMENT '主题ID（-1 = 离群点）',
    label          VARCHAR(128) NOT NULL COMMENT '主题人类可读标签（取 Top 3 关键词拼接）',
    top_words_json TEXT         NOT NULL COMMENT '主题 Top N 关键词及其 TF-IDF 权重，JSON 数组',
    sample_count   INT          NOT NULL COMMENT '该主题包含的评论数',
    model_name     VARCHAR(64)  NOT NULL COMMENT '模型 + embedding 标识（与 review_topics 一致）',
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '训练完成时间',

    PRIMARY KEY (topic_id, model_name),
    KEY idx_sample (sample_count)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='BERTopic 主题元信息（每主题一行，含 Top 关键词）';
