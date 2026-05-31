# 使用指南

`python-docstring-checker` 提供两个等价入口：

```bash
python-docstring-checker src
python -m python_docstring_checker src
```

位置参数可以是 Python 文件或目录。目录会递归扫描 `.py` 文件；不存在的路径、非 `.py` 文件会被跳过。

未传位置参数时，默认扫描当前目录。也可以通过配置项 `include` 或命令行 `--include` 指定默认扫描路径：

```bash
python -m python_docstring_checker --include src --include tests
```

如果已经传入位置参数，则只检查位置参数指定的文件或目录，`include` 不会额外生效。

## 退出码

- `0`：没有发现问题。
- `1`：发现至少一个问题。
- 参数错误或配置错误由 `argparse` 处理，通常返回 `2`。

CI 中可以直接使用退出码阻断流程：

```bash
python -m python_docstring_checker src
```

检查器也会识别常见的结构性误写。例如函数没有参数却把 `list[Item]:` 写进 `Args:` 时，会报告 `ARG005`，并提示该条目可能应该移动到 `Returns:` 或 `Yields:`。如果 `Args:` 已经为参数写了类型，但函数签名缺少注解，会报告 `ARG006`。函数体中明确的 `raise` 没有对应 `Raises:` 时，会报告 `RAI001`。

## 路径与排除

默认扫描路径：

```toml
[tool.python-docstring-checker]
include = ["src", "tests"]
```

`include` 表示默认要检查的文件或目录路径，仅在命令行没有传位置路径时使用。它不是通配符过滤规则；不存在的路径、非 `.py` 文件会沿用普通路径参数的行为被跳过。

默认排除：

- `.git/*`
- `__pycache__/*`
- `.venv/*`
- `venv/*`
- `build/*`
- `dist/*`

额外排除路径：

```bash
python -m python_docstring_checker src --exclude "src/generated/*" --exclude "*/migrations/*"
```

`--exclude` 使用 `fnmatch` 风格匹配，会匹配完整路径、文件名，以及路径中的后缀片段。

## 输出格式

默认 `text` 面向人阅读：

```bash
python -m python_docstring_checker src
```

`compact` 保留一行一条问题的紧凑格式，适合 grep 或简单脚本：

```bash
python -m python_docstring_checker --format compact src
```

`json` 输出增强 JSON 对象：

```bash
python -m python_docstring_checker --format json src
```

结构为：

```json
{
  "summary": {
    "total": 1,
    "files": 1,
    "codes": {
      "RET001": 1
    },
    "confidence": {
      "high": 1
    },
    "low_confidence": 0
  },
  "issues": [
    {
      "file": "src/example.py",
      "line": 10,
      "code": "RET001",
      "object": "build",
      "message": "Function returns a value but is missing a Returns section.",
      "confidence": "high"
    }
  ]
}
```

`json-lines` 每行输出一个 issue，适合日志采集：

```bash
python -m python_docstring_checker --format json-lines src
```

## 源码上下文

`--show-source` 会在 `text` 和 `compact` 输出中附带问题行附近源码：

```bash
python -m python_docstring_checker --show-source src
```

控制上下文行数：

```bash
python -m python_docstring_checker --show-source --source-context 0 src
python -m python_docstring_checker --show-source --source-context 2 src
```

`--source-context 0` 只显示问题行。源码读取失败时会静默降级为无源码片段。

## 检查策略

默认策略为 `balanced`，适合真实项目：

```bash
python -m python_docstring_checker --strictness balanced src
```

严格策略会检查更多对象，包括测试文件、私有对象、嵌套对象和未文档化属性：

```bash
python -m python_docstring_checker --strictness strict src
```

公开 API 策略优先检查对外可见对象；如果模块中有静态 `__all__`，只检查其中导出的顶层对象：

```bash
python -m python_docstring_checker --strictness public src
```

## 常见本地流程

先用默认策略发现高价值问题：

```bash
python -m python_docstring_checker src
```

想看具体源码位置：

```bash
python -m python_docstring_checker --show-source src
```

只看公开 API：

```bash
python -m python_docstring_checker --strictness public src
```

CI 中使用结构化输出：

```bash
python -m python_docstring_checker --format json-lines src
```
