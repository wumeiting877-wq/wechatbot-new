# P8-G2 Classifier Call Path Audit

> 日期：2026-09-23  
> Gate 0。只审计现有模型调用，不新增 Provider，不新增 API Key。

---

## 1. 现有客户端

`bot.py` 用项目已有配置构造主客户端：

```text
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
```

这里没有传入 `timeout`。当前环境的 OpenAI SDK 是 1.84.0，客户端默认值是：

```text
timeout = Timeout(connect=5.0, read=600, write=600, pool=600)
max_retries = 2
```

模型名、温度、`max_tokens` 来自已有配置：`MODEL`、`TEMPERATURE`、`MAX_TOKEN`。没有第二套模型配置。

`llm_client.install_into` 会把导出函数重绑到 `bot.py` 的全局命名空间。安装之后，这些函数看到的 `client` / `MODEL` / `runtime` 就是主程序那一份。

## 2. 不能复用 get_deepseek_response

`get_deepseek_response` 会：

```text
load_chat_contexts
get_user_prompt / Chat Prompt
把 chat_contexts 里的 history 放进 messages
把本轮 user / assistant 写回 chat_contexts
save_chat_contexts
```

`store_context=False` 时仍然只发一条 user 消息，不带独立 system prompt，而且返回值就是聊天答案。分类器不能走这条函数。

## 3. call_chat_api_with_retry 不能直接当分类器

它本身不加载 history，也不加载 memory。调用方如果只传入 `[system, user]`，请求体里就没有历史。

但它不适合分类：

```text
没有单次 timeout 参数，沿用客户端 read=600 秒
函数自己还有 max_retries=2
CONTENT_FILTER 分支会 clear_chat_context，并 clear_memory_temp_files
temperature / max_tokens 用的是聊天配置
```

一条分类因此可能占住几十秒，并且在内容过滤时改写聊天上下文。这不满足「短超时、无 history、无 memory、不改全局 Chat timeout」。

## 4. get_extractor_response 也不直接复用

它已经会：

```text
复用同一个 client / MODEL
with_options(timeout=...)
线程 join 作为第二道时限
不读 Chat Prompt，不写 chat_contexts
```

但它的返回整理在找 `"decision"`，空内容还会再打一次，日志 purpose 也锁在四个 Extractor 名字上。分类器文件不能包含 Extractor，也不能复用四个 Extractor Prompt。

所以 Gate 0 的结论是：底层客户端可以安全复用，聊天封装和 Extractor 封装都不能直接当分类器。

## 5. 采用的调用

新增 `llm_client.call_narrow_completion`，并放进现有 `EXPORTS`，安装后仍走主 `client`。

```text
实际复用：bot.py 里已经构造的 OpenAI client，以及已有 MODEL
客户端缺失时：沿用 _resolver_extractor_client 的现有配置回退
不新建 API Key
不新建 Provider 配置
不新建模型管理页面
```

分类器请求：

```text
messages = [
  {"role": "system", "content": 独立分类 prompt},
  {"role": "user", "content": 当前这一句}
]
temperature = 0
max_tokens = 128
timeout = 8 秒，with_options(timeout=8, max_retries=0)
线程 join(8) 作为调用方上限
purpose = query_intent，只进 note_llm_call，不进 HTTP body
```

返回结构是 `choices[0].message.content` 的字符串。空字符串交给上层判 `CLASSIFIER_INVALID`。不重试。

明确不做：

```text
不调用 get_deepseek_response
不读 Chat Prompt
不读、不写 chat_contexts
不读、不写 memory
不调用 clear_chat_context / clear_memory_temp_files
不修改全局 Chat timeout、TEMPERATURE、MAX_TOKEN
```

8 秒只包这一次分类。聊天调用仍然是 SDK 默认 read 600 秒。

## 6. 和会话锁的关系

P8-G1 的 `try_acquire_session` 在 `_send` 里，位于规则和 Query Service 之后。

P8-G2 的分类发生在 `route_hybrid`，也就是 `_dispatch` / `_send` 之前：

```text
规则
↓
candidate
↓
call_narrow_completion
↓
Query Service
↓
allow_reply
↓
session lock
↓
send_reply
```

慢分类不会占住 Chat 会话锁。会话忙时的行为不改：本轮不发送，不退回 Chat，不加队列。
