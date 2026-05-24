-- =============================================================================
--  review_sentiment 表 DDL
--  ---------------------------------------------------------------------------
--  归属：NLP / 评论洞察 Agent (`agents/nlp_agent`)
--
--  作用：
--    存放对 `order_reviews.review_comment_message`（葡语评论文本）做情感分析后
--    的预测结果。NLP Agent 采用「**离线灌库 + 在线读库**」模式：
--
--    1) 离线灌库（耗时操作，约 7 分钟）：
--         python -m agents.nlp_agent.tools.sentiment --backfill
--       会一次性对 `order_reviews` 全量带文本评论（约 4 万条）跑葡语情感模型
--       `pysentimiento/bertweet-pt-sentiment`（运行在 Apple Silicon MPS GPU 上），
--       将每条评论的极性 / 三分类概率 / 综合分数写入本表。
--
--    2) 在线读库（毫秒级）：
--       NLP Agent 接收用户提问时，不再调用模型推理；而是直接 SELECT 本表做
--       聚合（按品类 / 按州 / 按 review_score 交叉），输出 `state["review_insights"]
--       ["sentiment"]` 给 Decision Agent 消费。
--
--  与原始表的关系：
--    - 通过 `review_id` 与 `order_reviews` 1:1 关联
--    - 不修改 / 不依赖任何原始表结构；本表纯属增量
--    - 可被 Data Analysis Agent JOIN 查询，例如：
--        SELECT s.polarity, AVG(r.review_score)
--        FROM review_sentiment s JOIN order_reviews r USING(review_id)
--        GROUP BY s.polarity;
--
--  幂等性：
--    - 灌库脚本使用 `INSERT ... ON DUPLICATE KEY UPDATE`，重复执行只会刷新分数
--    - 默认只跑还未落库的 review_id（断点续跑友好）；`--force` 强制重跑
--
--  字段口径：
--    - polarity_score = pos_prob - neg_prob，落在 [-1, +1]
--    - polarity 取三分类概率最大者
--    - 灌库时不会处理 review_comment_message 为 NULL / 空字符串 的评论
-- =============================================================================

DROP TABLE IF EXISTS review_sentiment;

CREATE TABLE review_sentiment (
    review_id       VARCHAR(64) NOT NULL COMMENT '评论ID（与 order_reviews.review_id 1:1）',
    polarity        ENUM('POS','NEU','NEG') NOT NULL COMMENT '情感极性（三分类概率最大者）',
    polarity_score  FLOAT       NOT NULL COMMENT '综合极性分数：pos_prob - neg_prob，∈ [-1, +1]',
    pos_prob        FLOAT       NOT NULL COMMENT '正面概率',
    neu_prob        FLOAT       NOT NULL COMMENT '中性概率',
    neg_prob        FLOAT       NOT NULL COMMENT '负面概率',
    model_name      VARCHAR(64) NOT NULL COMMENT '推理模型名称（如 pysentimiento/bertweet-pt-sentiment）',
    model_version   VARCHAR(32) DEFAULT NULL COMMENT '模型版本（可选）',
    created_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '推理时间',

    PRIMARY KEY (review_id),
    KEY idx_polarity   (polarity),
    KEY idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='评论情感分数（NLP Agent 离线灌库；与 order_reviews 通过 review_id 关联）';
