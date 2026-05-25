# 测试报告

## 测试岗位->公司链路(验证中转站token能用)

### `tests/test_relay_connection.py`

#### 测试目标

验证“岗位输入 -> 模型筛选公司 -> 输出候选公司列表”链路是否可用，确保系统能够基于 `config.yaml` 中配置的岗位名称和候选公司数量，通过 OpenAI-compatible Relay 模型接口返回有效的公司候选结果。

#### 测试范围

- 读取项目配置文件 `config.yaml`，获取岗位名称、候选公司数量和模型后端配置。
- 支持通过环境变量 `JOB_WATCH_API_BASE_URL`、`JOB_WATCH_API_KEY`、`JOB_WATCH_MODEL` 覆盖本地配置，便于不同环境执行集成测试。
- 初始化 `JobWatchWorkflow`，调用筛选阶段 `_select_companies()`。
- 将模型原始输出和解析后的候选公司列表写入 `output/test_output/test_relay_connect.json`，用于测试结果留档和人工排查。

#### 验证点

- 模型后端返回内容不为空。
- 候选公司列表至少包含一条有效记录。
- 第一条候选公司必须包含非空公司名称。
- 第一条候选公司必须包含非空招聘页面 URL。
- 第一条候选公司的排序值 `rank` 必须大于或等于 1。

#### 跳过条件

- 未配置有效的 `JOB_WATCH_API_BASE_URL` 或 `JOB_WATCH_API_KEY`。
- 当前配置仍为示例地址或占位 API Key。

#### 测试价值

该测试用于验证系统第一阶段核心能力是否正常，即模型能否根据目标岗位筛选出可用于后续官网抓取和招聘时间分析的公司列表。它属于外部模型接口集成测试，可用于发现模型服务不可用、Relay 配置错误、返回结构异常或候选公司解析失败等问题。
