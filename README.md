# python-docstring-checker

> [!WARNING]  
> 这是一个 Python Google 风格 docstring 检查器的实验项目，用于验证和落地相关检查规则，并非官方 Google docstring 规范或官方工具。

`python-docstring-checker` 是一个基于标准库 `ast` 的 Python Google 风格 docstring 检查器。它不导入、不执行被检查代码，只静态解析源码，并检查函数参数、返回值、生成器、属性文档和类型注解是否一致。

适合用于：

- 在本地或 CI 中检查 Google 风格 docstring 是否和真实签名同步。
- 发现参数漏写、多写、改名、类型漂移，以及 docstring 有类型但签名缺少注解的问题。
- 发现返回值缺少 `Returns:`、生成器误用 `Returns:`、明确抛出的异常缺少 `Raises:`、属性文档类型不一致。
- 识别把返回值类型误写进 `Args:` 的常见错误，并给出迁移到 `Returns:` / `Yields:` 的提示。
- 在真实项目中使用默认降噪策略，同时保留严格模式。

## 安装

从 PyPI 安装：

```bash
pip install python-docstring-checker
```

升级到最新版本：

```bash
pip install -U python-docstring-checker
```

如需安装仓库中的最新代码：

```bash
pip install git+https://github.com/licyk/python-docstring-checker.git
```

也可以指定分支或提交安装：

```bash
pip install git+https://github.com/licyk/python-docstring-checker.git@main
```

本地开发安装：

```bash
git clone https://github.com/licyk/python-docstring-checker.git
cd python-docstring-checker
pip install -e .[dev]
```

安装后可使用脚本入口：

```bash
python-docstring-checker path/to/file.py
```

也可以直接使用模块入口：

```bash
python -m python_docstring_checker path/to/file.py
```

## 快速开始

扫描单个文件：

```bash
python -m python_docstring_checker examples/sd_webui_all_in_one/downloader/aria2_server.py
```

扫描目录：

```bash
python -m python_docstring_checker src tests
```

未传文件或目录时，默认扫描当前目录。也可以在配置中用 `include` 指定默认扫描路径。

默认输出为适合阅读的 `text` 格式，包含摘要和按文件分组的问题列表。发现问题时退出码为 `1`，没有问题时退出码为 `0`。

示例输出：

```text
Docstring Check Report
Total issues: 1
Files affected: 1
By code: ARG003=1
By confidence: high=1

examples/sd_webui_all_in_one/downloader/aria2_server.py
  L101: ARG003 [high] Aria2RpcServer.__init__
    Parameter 'log_file' type mismatch: docstring has 'Path | None', signature has 'Path | str | None'.
```

## 常用命令

显示当前安装版本：

```bash
python-docstring-checker --version
```

显示源码上下文：

```bash
python -m python_docstring_checker --show-source --source-context 2 src
```

输出 JSON：

```bash
python -m python_docstring_checker --format json src
```

输出一行一个 JSON，适合日志采集：

```bash
python -m python_docstring_checker --format json-lines src
```

使用旧式紧凑输出，适合 `grep` 或简单脚本：

```bash
python -m python_docstring_checker --format compact src
```

切换检查策略：

```bash
python -m python_docstring_checker --strictness strict src
python -m python_docstring_checker --strictness public src
```

指定配置文件：

```bash
python -m python_docstring_checker --config pyproject.toml src
```

指定默认扫描路径，仅在未传位置路径时生效：

```bash
python -m python_docstring_checker --include src --include tests
```

## 最小配置

在 `pyproject.toml` 中添加：

```toml
[tool.python-docstring-checker]
include = ["src"]
strictness = "balanced"
format = "text"
show-source = false
source-context = 1
exclude = ["build/*", "dist/*"]
ignore-codes = []
```

命令行参数优先级高于 `pyproject.toml`。传入位置路径时会忽略 `include`；未传位置路径时，配置中的 `include` 会和 CLI 的 `--include` 追加合并。列表型选项会在默认值和配置值基础上继续追加命令行参数。

## 文档

- [使用指南](docs/usage.md)
- [配置说明](docs/configuration.md)
- [规则与诊断码](docs/rules.md)
- [开发指南](docs/development.md)

## 当前约束

- 目标 Python 版本为 `3.10+`。
- 第一版只使用标准库实现，不引入运行时代码执行。
- Google 风格解析以 `Args:` / `Returns:` / `Yields:` / `Raises:` / `Attributes:` 为主要格式。
- 检查器只覆盖模块、类、函数、方法、属性等结构，不检查函数内部局部变量的文档。
