# 开发指南

`docstring-checker` 第一版保持轻量：只依赖 Python 标准库完成源码解析和检查，测试依赖为 `pytest`。

## 本地安装

安装包本体：

```bash
pip install -e .
```

安装开发依赖：

```bash
pip install -e .[dev]
```

运行测试：

```bash
python -m pytest -q
```

运行 CLI：

```bash
python -m python_docstring_checker --help
python -m python_docstring_checker examples/sd_webui_all_in_one/downloader/aria2_server.py
```

## 项目结构

```text
python_docstring_checker/
  checker.py      # AST 遍历、检查策略、诊断生成
  cli.py          # 命令行参数、配置读取、退出码
  google.py       # Google 风格 docstring parser
  models.py       # Issue 模型
  output.py       # text/json/compact/json-lines 输出
  types.py        # 类型归一化和类型比较
tests/
  test_checker.py # 单元测试和 CLI 行为测试
docs/
  *.md            # 用户文档
```

## 新增检查规则

新增规则时建议按这个顺序：

1. 在 `checker.py` 中找到对应检查阶段，例如参数、返回值、属性或文档缺失。
2. 选择新的诊断码，保持三字母前缀和三位数字格式。
3. 用 `_add_issue(...)` 生成 `Issue`，消息要直接说明“代码实际情况”和“docstring 中的问题”。
4. 在 `tests/test_checker.py` 中添加最小复现测试。
5. 在 `docs/rules.md` 的诊断码表中补充说明。

诊断码建议：

- `DOCxxx`：模块、类、函数、方法文档缺失。
- `ARGxxx`：参数文档问题。
- `RETxxx`：返回值或生成器文档问题。
- `ATRxxx`：属性文档问题。
- `SYNxxx`：源码解析问题。

## 新增 CLI 参数或配置项

新增用户可见选项时需要同步更新：

1. `cli.py` 中的 `argparse` 参数。
2. `CheckOptions` 或输出选项的数据结构。
3. `pyproject.toml` 配置读取逻辑。
4. `tests/test_checker.py` 中的 CLI/config 覆盖测试。
5. `README.md`、`docs/usage.md`、`docs/configuration.md`。

命令行参数应优先于配置文件。布尔选项优先使用 `argparse.BooleanOptionalAction`，同时提供 `--foo` 和 `--no-foo`。

## 修改 Google parser

`google.py` 只解析当前检查器需要的 Google 风格段落，不追求完整 docstring 规范实现。

修改 parser 时要覆盖：

- `Args:` / `Arguments:` / `Parameters:` 的参数名称、类型和描述。
- `Returns:` / `Yields:` 的 `Type: desc` 和 `Type:\n    desc` 形式。
- 缩进的大写类型名，例如 `Path:`、`Any:`，不能被误判为段落标题。
- 近似写法 `name: (type): desc`。

## 修改类型归一化

`types.py` 使用 `ast.parse(..., mode="eval")` 解析类型字符串。新增等价写法时，需要同时测试：

- `typing.` 前缀。
- 内置泛型和 `typing` 泛型的等价关系。
- `Optional`、`Union`、`|` 联合类型。
- 字符串前向引用。
- 无法解析类型的低置信度回退。

## 当前约束

- 不执行被检查代码。
- 不依赖第三方 parser。
- 不把函数内部局部变量作为文档检查对象。
- 保持默认 `balanced` 策略适合真实项目，避免把噪声作为默认行为。
