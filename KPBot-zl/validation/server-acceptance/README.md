# P0/P1 服务器实测验收方案

## 1. 验收目标

使用真实工作负载证明：P0 能正确计算并呈现测量波动；P1 能读取真实数据，以用户配置的指标、组数、维度、统计量和坐标范围生成正确图表。

核心负载采用 Python 标准库 zlib 压缩。矩阵为三种输入大小 × 三种压缩等级 × 两种数据类型 × 七次独立运行，共 126 个进程。它覆盖三组对照、多维、多个量纲、重复波动及已有统计值。不是向量检索业务收益验证，也不证明 KPBot 已优化了压缩算法。

每个进程使用同一固定种子生成数据，预热一次，再测量至少三次压缩操作，通常持续约 0.3 秒，最多 10000 次操作。结束后解压检查数据一致。每次进程的内循环统计是一个独立运行的汇总；内循环不是多个独立运行。保存所有内循环原始值。

七次是本验收选择的采样量，不代表显著性保证。候选慢于基线、没有明显波动或收益为负，都不意味着验收失败；真实波动不可预先保证。

## 2. 文件与所需环境

从本地上传整个 `KPBot-zl` 目录，所需入口：

```text
KPBot-zl/
├── Plugins/code-optimizer/skills/
│   ├── vector-experiment-methodology/scripts/compare_results.py
│   └── benchmark-visualization/scripts/visualize.py
├── tests/
└── validation/server-acceptance/
    ├── collect.py
    ├── check_p0.py
    └── README.md
```

服务器需要 Python 3.10+；采集和 P0 只使用标准库，绘图另需 Matplotlib。建议 Linux/鲲鹏服务器；无须 root，不修改 governor、NUMA 或服务配置。选择有空闲资源的测试时段，避免与生产负载争用。

正式结果应记录服务器型号、CPU 型号、OS、Python/zlib 版本、CPU 亲和性及是否存在竞争负载。采集器自动记录基础环境；补充业务和机器描述到 `notes.md`。可以在现有调优测试环境中运行，但各轮环境应保持一致。

## 3. 传输和准备

本地 PowerShell（将占位符替换为实际信息）：

```powershell
scp -r D:/workspace/KPBot/KPBot-zl USER@SERVER:/home/USER/
```

服务器 Bash：

```bash
cd /home/USER/KPBot-zl
python3 --version
python3 -m venv .venv
. .venv/bin/activate
python -m pip install matplotlib
python -m pip freeze > validation/python-packages.txt
uname -a > validation/uname.txt
lscpu > validation/lscpu.txt
```

离线服务器可使用已有 Matplotlib，或由具备同架构兼容环境准备离线 wheel。采集器不依赖绘图包，也可仅在服务器采集，将结果传回本地绘图。不要为了本测试修改系统级 Python。

## 4. 先冒烟，再正式采集

在 `KPBot-zl` 根目录执行：

```bash
python validation/server-acceptance/collect.py \
  --output validation/smoke \
  --sizes 4096,65536 --levels 1,6 --workloads compressible \
  --repeats 3 --seconds 0.02
```

确认没有失败后执行正式矩阵：

```bash
python validation/server-acceptance/collect.py --output validation/real-run
```

通常数分钟内完成，实际取决于机器；不是固定时限。所有输出目录必须不存在，防止覆盖旧实验。重复正式实验使用 `validation/real-run-02` 等新目录。

可选：经确认可用的 CPU 编号后，用 `taskset -c <CPU_ID> python ...` 固定采集器及其子进程的亲和性；将命令记入 notes。不要把示例 CPU 编号当成机器必然可用的核。

脚本按每轮随机排列整个配置矩阵，种子和实际顺序保存在 schedule.json。失败进程会保留 stderr，环境状态不会标记 complete；发生失败时检查原因并用新目录完整复测，不将不完整结果包装成完整矩阵。

## 5. 采集产物和含义

| 文件/字段 | 内容 |
| --- | --- |
| environment.json | 环境、命令、采样口径和完成状态 |
| schedule.json | 实际独立进程执行顺序 |
| raw/NNNN.json | 每个进程的全部操作耗时、输入哈希、正确性与汇总 |
| samples.csv | 每个进程一行，包含配置和独立 run_id |
| latency_ms | 本次进程内操作耗时中位数 |
| throughput_mib_s | 输入 MiB / 本次进程内中位耗时；与 latency 派生相关，不是独立指标 |
| min_ms/max_ms | 本次进程内操作最小/最大耗时，不能解释为跨轮最小/最大 |
| cpu_seconds/cpu_pct | 测量循环的进程 CPU 时间、相对单核墙钟占比；包含 Python 计时与循环开销 |
| compressed_ratio | 压缩后字节数 / 输入字节数，体现配置取舍 |
| correctness | 解压回读是否一致，必须为 1 |
| p0-*.json | 耗时与吞吐两种 P0 输入，level 6 为 baseline，level 1 为 candidate |
| chart-spec.json | 根据矩阵自动生成的十幅图配置，可编辑 |

level 6 与 level 1 是配置对照，压缩结果字节长度可能不同。correctness=1 只证明本次数据往返一致，不等于全面软件正确性证明。

## 6. P0 实际运行和独立复核

```bash
python Plugins/code-optimizer/skills/vector-experiment-methodology/scripts/compare_results.py \
  validation/real-run/p0-latency_ms.json \
  --output validation/real-run/p0-latency-result.json

python validation/server-acceptance/check_p0.py \
  validation/real-run/p0-latency_ms.json validation/real-run/p0-latency-result.json

python Plugins/code-optimizer/skills/vector-experiment-methodology/scripts/compare_results.py \
  validation/real-run/p0-throughput_mib_s.json \
  --output validation/real-run/p0-throughput-result.json

python validation/server-acceptance/check_p0.py \
  validation/real-run/p0-throughput_mib_s.json validation/real-run/p0-throughput-result.json

python -B -m unittest discover -s tests -p test_faiss_comparison_contract.py -v
```

独立核算脚本不导入生产脚本，用排序和公式重新计算。验收记录同时保存命令输出；不能只写“脚本正常结束”。

| 用例 | 输入/操作 | 预期 |
| --- | --- | --- |
| P0-01 实测离散度 | 正式六个 workload×size 数据集 | 双侧 n=7；min≤median≤max，MAD 与独立核算一致 |
| P0-02 指标方向 | 分别运行 latency 和 throughput | 耗时用 A/B，吞吐用 B/A，百分比和几何平均独立核算通过 |
| P0-03 小样本 | 将输入副本每侧截取 1、2 条，保留原文件 | flag=true；一个样本 MAD=0，但不称稳定 |
| P0-04 保留慢样本 | 原始实测全量；另用单元测试固定离群值 | 没有静默删除慢轮，n 不减，max 与来源一致 |
| P0-05 错误数据 | 自动测试中混入 0、负数、NaN、缺失字段 | 非零退出，明确报错，不生成成功摘要 |
| P0-06 正确性边界 | 自动测试检查零 recall、缺失正确性字段 | 不误用性能正数约束；缺失标不可用 |
| P0-07 兼容字段 | 查看结果与原输出约定 | 原字段仍存在，新增两个 statistics 对象 |

P0-03 可复制 JSON 后使用 `datasets` 中每侧列表的 `[:1]`、`[:2]` 截取；命名为 derived-one/derived-two，注明来自正式数据子集，不宣称新采集轮次。固定异常值测试属于合成边界测试，不可混入实测报告。

## 7. P1 实际运行和检查

```bash
python Plugins/code-optimizer/skills/benchmark-visualization/scripts/visualize.py \
  --spec validation/real-run/chart-spec.json \
  --output-dir validation/real-run/charts

python -B -m unittest discover -s tests -p test_benchmark_visualization.py -v
```

打开 `validation/real-run/charts/index.md`，核对每幅图和 data、summary。各轮数据声明为 summary，跨轮取中位数显式使用 aggregate_summary=true。标题/说明应理解为“各独立运行内统计值”的展示。

| 用例 | 具体操作 | 判定标准 |
| --- | --- | --- |
| P1-01 多组多维 | 默认三等级、三规模、两数据类型 | 三个系列、两个分面；散点每系列每规模七条，不把内循环操作当独立进程 |
| P1-02 多种指标 | 查看 latency、throughput、CPU 时间、压缩比 | 单位正确、轴不是写死 QPS；压缩比为实际结果 |
| P1-03 波动 | 查看 scatter、box、line 范围带 | 原始点、跨轮中位数及 min/max 与 CSV 一致，无静默离群删除 |
| P1-04 已有统计 | 查看 min_ms/max_ms 图 | 每轮现成值直接画点，能追溯到 raw；没有还原虚构请求分布 |
| P1-05 图型覆盖 | 查看十幅图（八类） | 所有 SVG/PNG 可读，标签不重叠，图例不遮住主要结果 |
| P1-06 动态组数 | 新采集 `--levels 1,3,6,9` | 不修改 Python，自动四系列；配置与数据一一对应 |
| P1-07 新维度组合 | 在数据副本新增 compiler 或机器维度，series 配置数组 | 按数据分组；副本标为变换测试，不冒充另一台实测机器 |
| P1-08 拉大纵轴 | 复制配置，给 scatter 加 ylim=[0, 原最高值×1.5] | 图的显示范围改变；summary 的统计、观测数和 data 内容不变 |
| P1-09 改统计与图型 | 单图 line 改 point；median 改 mean；spread 改 sd | 不改源码即可运行；mean/SD 与独立核算一致 |
| P1-10 过滤 | filter 固定一个 workload 或 level（CSV 使用字符串） | 选中记录数等于原表匹配行数，未选值不出现 |
| P1-11 分布 | hist/ecdf 固定最大输入大小 | 同条件下的跨运行统计值分布，不混合不同大小造成假波动 |
| P1-12 缺失组合 | 从副本删除一个 level×size 的全部记录 | 热力图单元留空，不填零；其余值不变 |
| P1-13 复现 | 同一配置与原始文件输出到另一个目录 | 数据和统计一致；图语义一致，不要求图片逐字节一致 |
| P1-14 错误配置 | 拼错 ylim 为 ylimit；不聚合重复 x；重复 unit_id | 明确错误，不偷偷忽略关键配置或宣称完成 |

扩大纵轴示例，在服务器根目录执行（自动读取观测最大值，不固定为某个毫秒范围）：

```bash
python - <<'PY'
import csv,json
from pathlib import Path
p=Path('validation/real-run')
spec=json.loads((p/'chart-spec.json').read_text())
rows=list(csv.DictReader((p/'samples.csv').open()))
spec['charts']=[c for c in spec['charts'] if c['id']=='scatter']
spec['charts'][0]['ylim']=[0,max(float(r['latency_ms']) for r in rows)*1.5]
(p/'chart-spec-expanded.json').write_text(json.dumps(spec,indent=2))
PY
python Plugins/code-optimizer/skills/benchmark-visualization/scripts/visualize.py \
  --spec validation/real-run/chart-spec-expanded.json \
  --output-dir validation/real-run/charts-expanded
```

比较两个输出的 data/scatter.csv，应完全一致；对 summary 仅比较 scatter 项，因为新配置只生成一幅图。

## 8. 可选但有说服力的微架构补充

若服务器已有授权使用的 perf/DevKit，可采集 cycles、instructions、cache miss 等。工具权限、PMU 可用性和计数器复用会影响结果，先按服务器的既有采集规范确认。

建议额外采集一个较长的固定负载，保留工具原始日志，然后整理成列：run_id、level、size、workload、cycles、instructions、ipc、计数器覆盖率/有效性。IPC 按同一次计量窗口的 instructions/cycles 计算；不把整个进程计数与仅压缩循环的耗时混称同一窗口。

在配置中新增这些指标的 column/unit/sample_level，复制 point 或 scatter 配置引用它们即可。无 PMU 权限时记录该项未测；不要把 cpu_pct 改名为 IPC，也不要人为填充计数器数据。

## 9. 自有业务数据验证

通用压缩实验说明核心功能可用；为了贴近 KPBot，再增加一份真实 Faiss/VSAG、sysbench、TF 或服务压测结果更有说服力。

把原始结果解析成一行一个独立运行的 CSV，最少包含 run_id、版本/配置、规模或负载、指标列。保留转换脚本及原始日志。复制生成的 chart-spec，只修改 mapping.metrics、x、series、facet 与过滤规则即可。

没有独立重复运行的数据只能验证汇总展示；不得复制同一条记录七次冒充重复实验。不同量纲分图；同名指标但测量口径不同先分组说明。

## 10. 收集结果并回传

从本地执行：

```powershell
scp -r USER@SERVER:/home/USER/KPBot-zl/validation/real-run D:/workspace/KPBot/KPBot-zl/validation/server-results
```

回传前保留原始内容；脱敏时记录改动，不修改实际数值。结果包应包括原始日志、CSV、环境、schedule、P0 输入输出、独立核算日志、P1 配置与图表，以及 notes.md。

验收表按 `用例 ID | 环境/命令 | 数据文件 | 实际结果 | PASS/FAIL/PENDING | 证据` 填写。没有明确证据的项标 PENDING。真实实验不要以“加速超过某个百分比”作为技能通过标准。

## 11. 当前本地验证与服务器执行的区别

本测试工具可以先在本地小规模运行以核查脚本链路；服务器正式矩阵由使用者执行。文档中的样本数、图形数量是预期，不代表服务器已实测通过。

本方案补的是数据和绘图验收，不替代完整 install.sh 回归。服务器测试可直接使用文件路径运行技能；验证 Agent 发现和调用时，再在完整项目副本中执行安装流程。
