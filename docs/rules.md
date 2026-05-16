# 规则与诊断码

检查器解析 Google 风格 docstring，并和 AST 中的真实代码结构对比。它不会导入或执行被检查代码。

## 支持的 Google 风格段落

支持以下段落标题：

- `Args:`、`Arguments:`、`Parameters:`
- `Returns:`
- `Yields:`
- `Raises:`
- `Attributes:`

参数和属性支持：

```python
def download(url: str, retry_count: int = 3) -> Path:
    """下载文件。

    Args:
        url (str):
            下载链接。
        retry_count (int):
            重试次数。

    Returns:
        Path:
            下载后的文件路径。
    """
```

也支持项目中常见的近似写法：

```python
def parse(value: str | None) -> None:
    """解析输入。

    Args:
        value: (str | None):
            输入值。
    """
```

属性可以写在类 `Attributes:` 中：

```python
class Client:
    """客户端。

    Attributes:
        endpoint (str):
            服务地址。
    """

    endpoint: str
```

也可以使用相邻属性 docstring：

```python
DEFAULT_TIMEOUT = 30
"""默认超时时间。"""
```

生成器应使用 `Yields:`，不要只写 `Returns:`：

```python
def numbers():
    """生成数字。

    Yields:
        int:
            下一个数字。
    """
    yield 1
```

明确抛出的异常应使用 `Raises:`：

```python
def load_config(path: Path) -> dict[str, Any]:
    """加载配置。

    Args:
        path (Path):
            配置文件路径。

    Returns:
        dict[str, Any]:
            配置内容。

    Raises:
        RuntimeError:
            配置读取失败。
    """
    try:
        return json.loads(path.read_text())
    except OSError as exc:
        raise RuntimeError("配置读取失败") from exc
```

## 类型比较

类型比较会做常见归一化：

- `Optional[T]` 等价于 `T | None`。
- `Union[A, B]` 等价于 `A | B`。
- `List[str]` 等价于 `list[str]`。
- 忽略 `typing.` 前缀。
- union 成员会排序，避免 `A | B` 和 `B | A` 的顺序误报。
- 字符串前向引用会尝试按类型继续归一化。

如果类型字符串无法被 `ast` 解析，检查器会退回到清理空白后的字符串比较，并把类型不匹配标记为低置信度。

## 策略差异

`balanced` 是默认策略，更适合真实项目：

- 跳过测试文件、私有对象、dunder 对象、嵌套对象。
- 默认属性策略为 `documented`，只校验已经出现在 `Attributes:` 或相邻属性 docstring 中的属性。
- 不强制 Args/Returns 写类型，但写了类型就会检查一致性。
- 忽略常见框架覆写方法：`format`、`emit`、`handle`、`invalidate_caches`。

`strict` 更适合新项目或强约束代码库：

- 检查测试文件、私有对象、dunder 对象、嵌套对象。
- 默认属性策略为 `strict`，未文档化属性会报错。
- 要求 docstring 中显式写参数和返回类型。

`public` 更适合库项目：

- 优先检查公开对象。
- 如果模块定义了静态 `__all__`，只检查导出的模块级对象。
- 默认属性策略为 `documented`。

## 诊断码

| 代码 | 含义 | 常见模式 |
| --- | --- | --- |
| `SYN001` | 源文件存在语法错误，无法解析。 | 所有模式 |
| `DOC001` | 模块缺少 docstring。空 `__init__.py` 默认不报。 | `strict` 更常见 |
| `DOC002` | 类缺少 docstring。 | 所有模式，取决于对象是否被策略检查 |
| `DOC003` | 函数或方法缺少 docstring。 | `strict` 更常见 |
| `ARG001` | 签名中存在参数，但 `Args:` 中缺失。 | 所有模式 |
| `ARG002` | `Args:` 中记录了签名不存在的参数。 | 所有模式 |
| `ARG003` | 参数 docstring 类型和签名注解不一致。 | 所有模式 |
| `ARG004` | 参数有签名注解，但 docstring 未写类型。 | 默认只在 `strict` 或显式开启类型要求时出现 |
| `ARG005` | `Args:` 中存在看起来像类型、但不是参数的条目，常见于把返回值误写进 `Args:`。 | 所有模式 |
| `ARG006` | 参数在 `Args:` 中声明了类型，但函数签名缺少对应类型注解。 | 所有模式 |
| `RAI001` | 函数明确抛出异常，但 `Raises:` 缺失或未记录该异常。 | 所有模式 |
| `RAI002` | `Raises:` 中记录了异常，但当前函数体没有直接抛出该异常。 | 默认只在 `strict` 出现 |
| `RAI003` | 存在无法静态确认类型的 `raise`，例如 `raise exc` 或 `raise make_error()`。 | 低置信度；无 `Raises:` 时默认出现，`strict` 总是出现 |
| `RET001` | 函数返回值或生成器缺少 `Returns:` / `Yields:`。 | 所有模式 |
| `RET002` | 函数不返回值，却写了非 `None` 的 `Returns:`。 | 所有模式 |
| `RET003` | `Returns:` / `Yields:` 类型和返回注解不一致。 | 所有模式 |
| `RET004` | 返回注解存在，但 `Returns:` / `Yields:` 未写类型。 | 默认只在 `strict` 或显式开启类型要求时出现 |
| `RET005` | 生成器使用了 `Returns:`，应改用 `Yields:`。 | 所有模式 |
| `ATR001` | 属性缺少文档。 | `strict` 或 `attribute-policy = "strict"` |
| `ATR002` | 属性文档类型和赋值注解不一致。 | 所有模式，只要该属性被检查 |

## 正确示例

```python
from pathlib import Path


def build_path(name: str, base: Path | None = None) -> Path:
    """构建路径。

    Args:
        name (str):
            文件名。
        base (Path | None):
            基础路径。为 None 时使用当前目录。

    Returns:
        Path:
            构建后的路径。
    """
    return (base or Path.cwd()) / name
```

## 错误示例

```python
def build_path(name: str, base: Path | None = None) -> Path:
    """构建路径。

    Args:
        filename (str):
            文件名。
        base (Path):
            基础路径。
    """
    return (base or Path.cwd()) / name
```

这个函数会触发：

- `ARG001`：`name` 没有出现在 `Args:` 中。
- `ARG002`：`filename` 不存在于真实签名。
- `ARG003`：`base` 的 docstring 类型少了 `None`。
- `RET001`：函数返回 `Path`，但缺少 `Returns:`。

另一个常见错误是把返回值写进 `Args:`：

```python
def get_gpu_list() -> list[GPUDeviceInfo]:
    """获取显卡列表。

    Args:
        list[GPUDeviceInfo]:
            显卡信息列表。
    """
    return []
```

这个函数会触发：

- `ARG005`：`list[GPUDeviceInfo]` 不是参数名，且和返回注解一致，应移动到 `Returns:`。
- `RET001`：函数返回列表，但缺少 `Returns:`。

如果 docstring 已经声明了参数类型，函数签名也应该同步写出类型注解：

```python
def add(a, b: str) -> None:
    """相加。

    Args:
        a (int):
            第一个数字。
        b (str):
            第二个值。

    Returns:
        int:
            相加结果。
    """
    return a + b
```

这个函数会触发：

- `ARG006`：`a` 在 `Args:` 中写了 `int`，但签名中缺少 `a: int`。
- `RET003`：`Returns:` 写了 `int`，但签名返回注解是 `None`。

如果函数体明确抛出异常，也需要记录 `Raises:`：

```python
def fail() -> None:
    """失败。"""
    raise RuntimeError("boom")
```

这个函数会触发：

- `RAI001`：函数抛出 `RuntimeError`，但缺少 `Raises: RuntimeError:`。

当前异常检查只分析函数体内明确的 `raise`、`except SomeError: raise` 和 `raise NewError(...) from exc`。它不会推断普通函数调用、装饰器或上下文管理器内部可能抛出的异常。`Exception` / `BaseException` 可覆盖具体异常；`module.CustomError` 和 `CustomError` 视为同一类异常。
