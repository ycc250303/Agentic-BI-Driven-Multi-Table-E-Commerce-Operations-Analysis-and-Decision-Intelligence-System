# Agentic BI 驱动的多表电商运营分析与决策智能系统

面向电商运营分析与决策支持：用自然语言完成跨表指标统计、原因下钻与趋势观察，并按需输出图表与可落地的运营建议。

![Python](https://img.shields.io/badge/Python-3.11+-3776AB)
![LangChain](https://img.shields.io/badge/LangChain-1.4-1C3C3C)
![LangGraph](https://img.shields.io/badge/LangGraph-1.2-1C3C3C)
![MySQL](https://img.shields.io/badge/MySQL-8-4479A1)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## 项目介绍

本系统基于巴西 [Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) 电商公开数据（约 11 万订单、9 张业务表，2016–2018），支持描述、诊断、预测与决策类分析。

它针对三类常见痛点：

- 非技术人员难以直接查询多表关联数据
- 传统看板只能被动看数，无法按问题动态分析
- 诊断结论与运营建议缺乏可核对的上游证据

业务人员可以这样提问：「2017 年哪个州的销售额最高？」「人们对某品类的评价如何，入行是否有前景？」「那 SP 州呢？」

此前实现的说明与运行方式见 [`README_legacy.md`](README_legacy.md)，代码在 `legacy/`。

---

## 技术栈

| 技术 | 版本 | 说明 |
| --- | --- | --- |
| Python | ≥ 3.11 | 运行时 |
| LangChain | 1.4 | LLM 调用与结构化输出 |
| LangGraph | 1.2 | 状态图 |
| DeepSeek / 通义千问 | deepseek-v4-flash / qwen3.8-max | 默认与可选模型 |
| MySQL | 8.0 | 业务库 |
| PyMySQL | 1.2 | 数据库访问 |
| Pydantic | 2.13 | 结构化契约 |

---

## 使用场景

| 角色 | 可以做什么 |
| --- | --- |
| 运营 / 分析 | 用自然语言查 GMV、州排名、品类趋势、配送准时率、支付结构 |
| 品类 / 商家运营 | 结合差评主题与评分，看问题集中在物流、品质还是履约 |
| 决策支持 | 在查数与评论证据齐备后，要改进建议或有限的 What-if 推演 |

示例问题：

- 2017 年哪个州的销售额最高？交付准时率是多少？
- 哪些品类近期在下滑？差评主要集中在什么主题？
- 如果缩短配送时长，准时率大概会怎么变？

---

## 许可证

[MIT License](LICENSE)
