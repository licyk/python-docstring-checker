# 配置说明

配置写在 `pyproject.toml` 的 `[tool.python-docstring-checker]` 中。默认会读取当前目录下的 `pyproject.toml`，也可以通过 `--config` 指定文件。

```bash
python -m python_docstring_checker --config pyproject.toml src
```

命令行参数优先级高于配置文件。列表型选项会在默认值和配置值基础上追加命令行参数。

## 配置项

| 配置项 | 默认值 | CLI 参数 | 说明 |
| --- | --- | --- | --- |
| `include` | `["."]` | `--include` | 未传位置路径时默认检查的文件或目录路径。 |
| `strictness` | `"balanced"` | `--strictness` | 检查策略，可选 `strict`、`balanced`、`public`。 |
| `exclude` | 内置排除列表 | `--exclude` | 额外排除路径，支持 `fnmatch` 风格。 |
| `ignore-codes` | `[]` | `--ignore-code` | 忽略指定诊断码，CLI 支持逗号分隔。 |
| `ignore-names` | `[]` | `--ignore-name` | 忽略属性名、函数名、类名，可使用通配符。 |
| `ignore-paths` | `[]` | `--ignore-path` | 忽略路径，可使用通配符。 |
| `ignore-decorators` | `[]` | `--ignore-decorator` | 跳过带指定装饰器的函数或类。 |
| `attribute-policy` | `strict` 模式为 `"strict"`，其他模式为 `"documented"` | `--attribute-policy` | 属性检查策略，可选 `strict`、`documented`、`off`。 |
| `ignore-method-names` | `balanced` / `public` 默认忽略常见框架覆写方法 | `--ignore-method-name` | 忽略指定方法名，可使用通配符。 |
| `require-docstring-types` | `strict` 模式为 `true`，其他模式为 `false` | `--require-docstring-types` / `--no-require-docstring-types` | 是否要求 Args/Returns 中显式写类型。 |
| `ignore-empty-init-modules` | `true` | `--ignore-empty-init-modules` / `--no-ignore-empty-init-modules` | 空 `__init__.py` 是否允许没有模块 docstring。 |
| `check-tests` | `strict` 模式为 `true`，其他模式为 `false` | `--check-tests` / `--no-check-tests` | 是否检查测试文件。 |
| `check-private` | `strict` 模式为 `true`，其他模式为 `false` | `--check-private` / `--no-check-private` | 是否检查私有和 dunder 对象。 |
| `check-nested` | `strict` 模式为 `true`，其他模式为 `false` | `--check-nested` / `--no-check-nested` | 是否检查嵌套函数和嵌套类。 |
| `format` | `"text"` | `--format` | 输出格式，可选 `text`、`compact`、`json`、`json-lines`。 |
| `show-source` | `false` | `--show-source` / `--no-show-source` | 是否在 text/compact 输出中显示源码上下文。 |
| `source-context` | `1` | `--source-context` | 源码上下文行数，必须大于等于 `0`。 |

内置排除列表为：

```toml
exclude = [".git/*", "__pycache__/*", ".venv/*", "venv/*", "build/*", "dist/*"]
```

`balanced` 和 `public` 默认忽略这些常见框架覆写方法：

```toml
ignore-method-names = ["format", "emit", "handle", "invalidate_caches"]
```

`include` 只在命令行没有传位置路径时生效。传了位置路径时，只检查位置路径指定的文件或目录；未传位置路径时，配置中的 `include` 会和 CLI 的 `--include` 追加合并。如果最终没有任何 include，检查器会回退到当前目录 `.`。

## 推荐配置

### balanced：真实项目默认选择

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

特点：

- 默认跳过测试文件、私有对象、嵌套对象。
- 默认只校验已经文档化的属性。
- 不强制 Args/Returns 写类型，但如果写了类型，会继续检查类型一致性。

### strict：新项目或强约束代码库

```toml
[tool.python-docstring-checker]
include = ["src", "tests"]
strictness = "strict"
attribute-policy = "strict"
require-docstring-types = true
check-tests = true
check-private = true
check-nested = true
```

特点：

- 要求模块、类、函数、方法都有 docstring。
- 检查测试文件、私有对象、嵌套对象。
- 属性缺文档会报 `ATR001`。
- Args/Returns 缺类型会报 `ARG004` / `RET004`。

### public：只看公开 API

```toml
[tool.python-docstring-checker]
include = ["src"]
strictness = "public"
attribute-policy = "documented"
format = "compact"
```

特点：

- 未定义 `__all__` 时，按无下划线公开对象检查。
- 定义静态 `__all__` 时，只检查导出的模块级函数、类和变量。
- 适合库项目在发布前检查外部 API 文档。

## 示例：CI 友好配置

```toml
[tool.python-docstring-checker]
include = ["src"]
strictness = "balanced"
format = "json-lines"
show-source = false
exclude = ["build/*", "dist/*", "src/generated/*"]
ignore-codes = []
```

CI 命令：

```bash
python -m python_docstring_checker
```
