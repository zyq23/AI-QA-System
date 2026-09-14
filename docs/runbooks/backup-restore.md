# 备份与恢复运行手册

## 目标

- RPO：24 小时以内；RTO：4 小时以内。
- 备份同时包含 SQLite、Chroma 和 uploads，并由 manifest 校验。

## 日常备份

```bash
./.venv/bin/python scripts/backup_runtime.py --backup-dir data/backups
./.venv/bin/python scripts/verify_backup.py data/backups/backup-<timestamp> --json
```

备份成功后，将备份目录复制到受控的异地/对象存储。不要将密钥写入 manifest。

## 恢复前

1. 确认目标服务停止或从流量池摘除。
2. 对当前 data/runtime、data/chroma、data/uploads 做第二份备份。
3. 验证备份 manifest 和 SHA256，确认 schema version。

## 恢复

```bash
./.venv/bin/python scripts/restore_runtime.py data/backups/backup-<timestamp> --target-root /srv/yushu --force
EVAL_API_BASE_URL= USE_STUB_ML=true DISABLE_LLM=true ./.venv/bin/python scripts/check_data_consistency.py --db /srv/yushu/data/runtime/app.db --chroma /srv/yushu/data/chroma --uploads /srv/yushu/data/uploads --json
./.venv/bin/python scripts/migrate.py --db /srv/yushu/data/runtime/app.db status
```

一致性检查失败时禁止恢复上线；需要保留报告并回滚到恢复前快照。

## 演练记录

每季度执行一次恢复演练，记录开始/结束时间、备份版本、恢复耗时、校验结果、缺陷和改进项。
