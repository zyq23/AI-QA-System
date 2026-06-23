# Thread-Parser 异常页清单

目标文件：`宇树科技知识库/【公司介绍】轩辕网络公司介绍202606.pptx`

基于产物：
- `docs/thread-parser-parse-only-no-ocr.json`
- `docs/thread-parser-parse-only-with-ocr.json`

## 当前结论

当前 parser 已满足“全文 parse-only 可跑完、关键页大多数可读、异常页可点名”的门槛。带 OCR 时仍有少量残余风险，但关键页与图片墙页的 block/chunk 膨胀已明显收敛，建议主线程放行到“入库前检查”下一闸门。

## 异常页

| 页号 | 问题类型 | 影响级别 | 是否属于 parser 边界 | 说明 |
| --- | --- | --- | --- | --- |
| `slide-27` | OCR 资源兼容失败 | 中 | 是 | 出现 `cannot find loader for this WMF file` warning，说明个别图片格式仍存在 OCR 覆盖盲区。 |
| `slide-33` | 教材墙页仍有 OCR 增量 | 中 | 是 | 经过页级合并后，已从早前的 `255 blocks / 238 chunks` 收敛到 `54 blocks / 16 chunks`；正文可读，但教材封面信息仍有一定噪声。 |
| `slide-48` | 奖项/证书型图片 OCR 混入正文 | 低 | 是 | 已从 `43 blocks / 29 chunks` 收敛到 `26 blocks / 6 chunks`，当前更像补充证据，不再是明显污染源。 |
| `slide-74` | 图片页 OCR 增量较高 | 中 | 是 | 带 OCR 后从 `26 blocks` 升到 `38 blocks`，新增内容有价值，但仍需控制图片说明类碎块进入后续 chunk。 |
| `slide-79` | 时间轴页残余 OCR 长文本混入 | 中 | 是 | 已从 `46 blocks / 31 chunks` 收敛到 `15 blocks / 4 chunks`，数字短噪声基本消失，但仍有网页截图型 OCR 长文本混入。 |
| `slide-80` | 大图混排页 OCR 增量偏高 | 中 | 是 | 已从 `125 blocks / 122 chunks` 收敛到 `55 blocks / 35 chunks`，主体文本已可消费，剩余风险主要是图片内补充文案偏多。 |
| `slide-89` | 组织图/Logo OCR 混入弱语义块 | 中 | 是 | 已从 `27 blocks / 24 chunks` 收敛到 `20 blocks / 16 chunks`，但 `師范術`、`網軒絡` 等弱语义块仍需在入库前检查时继续关注。 |

## 非关键页但应升级主线程关注

| 页号 | 问题类型 | 影响级别 | 是否属于 parser 边界 | 说明 |
| --- | --- | --- | --- | --- |
| `slide-5` | 专利墙类页面仍有低置信 OCR | 中 | 是 | 已从 `167 blocks / 141 chunks` 收敛到 `41 blocks / 29 chunks`，仍比无 OCR 明显偏高，但已回到可点名、可审查范围。 |
| `slide-30` | 多图混排页 OCR 增量 | 低 | 是 | 已收敛到 `13 blocks / 5 chunks`，不再是显著阻塞。 |
| `slide-53` | 社会服务图片页 OCR 量偏大 | 低 | 是 | 已从 `115 blocks / 102 chunks` 收敛到 `35 blocks / 23 chunks`，风险仍在但已显著下降。 |
| `slide-56` | 图片墙页 OCR 仍偏多 | 中 | 是 | 已从 `283 blocks / 280 chunks` 收敛到 `32 blocks / 11 chunks`，说明页级合并有效，但此类纯图片案例页仍需在入库前检查里重点观察。 |
| `slide-77` | 图片墙页 OCR 仍偏多 | 中 | 是 | 已从 `307 blocks / 292 chunks` 收敛到 `38 blocks / 13 chunks`，不再属于“必然大面积污染”的级别。 |

## 当前判断

- `placeholder/template` 残留本轮未再成为主导问题，说明模板过滤已基本压住。
- 新增的 OCR 片段压缩与页级合并策略已经显著降低图片墙、教材墙、时间轴页的 block/chunk 膨胀。
- 当前剩余问题仍主要属于 parser/OCR 文本形态治理问题，不是 retrieval / answer / infra 主逻辑问题。
- 现阶段已达到“可进入入库前检查”的条件，但还未等同于“正式入库”或“问答链路稳定”。
