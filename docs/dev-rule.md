# Dev Rule — 开发细则

> 项目级约束在 `CLAUDE.md`。本文是 AI 交付时的操作清单。

---

## 1. 交付前检查清单

- [ ] `bash scripts/lint.sh` 退出码为 0
- [ ] 相关验证脚本跑过且通过
- [ ] 没有中文注释、中文日志字符串、中文变量名
- [ ] 没有硬编码密钥
- [ ] 没有遗留调试代码（`print`、`TODO`、临时文件）
- [ ] 新增/修改的文件已更新 `docs/status.md`
- [ ] 已写 `docs/changelog.md`
- [ ] 用户验收步骤写清楚（点哪里、看什么现象）

---

## 2. 语法检查命令

```bash
bash scripts/lint.sh
```

包含：

```bash
# Python 语法
python -m compileall -q botoffice server.py

# JavaScript 语法（逐文件）
node --check <file>

# JSON 语法
python -c "import json,sys; json.load(open(sys.argv[1], encoding='utf-8'))" <file>
```

退出码非 0 ⇒ **不得交付**。

---

## 3. 禁止事项

1. 禁止要求用户改代码、看报错、自己 debug。
2. 禁止把运行时日志写进 `docs/`。
3. 禁止 3D/2.5D 层承担业务逻辑。
4. 禁止为单个角色硬编码专属工具。
5. 禁止提交真实 API Key。
6. 禁止引入数据库。
7. 禁止在 GUI 线程做网络/LLM 调用。
8. 禁止编造未验证的技术结论（版本号、性能数字、跑通结论）。

---

## 4. 每次只改一件事

多个独立问题时拆成多次交付，每次只改一个，便于回滚与验收。

---

## 5. 测试数据

- 测试若写 `data/*.json`，**必须备份、测后逐字节还原**。
- 测试用 `mock` 平台，不消耗真实 token。
