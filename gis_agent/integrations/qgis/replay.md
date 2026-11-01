# 局部修订

local_replay 是可选能力。源执行 ID 来自 execution_history。它在当前会话运行确定的局部阶段，保留旧目录。普通脚本可继续直接编辑和执行。

## QGIS

plan 包含 repair_id、parent_repair、reason、accepted_inputs、steps、targets。每个步骤引用真实 source_execution。

```json
{
  "repair_id":"distance_fix","parent_repair":null,"reason":"修正距离",
  "accepted_inputs":{"points":{"path":"<absolute>/projected.gpkg"}},
  "steps":[{"step_id":"buffer","source_execution":"<execution_id>",
    "inputs":{"INPUT":{"accepted":"points"}},
    "changes":{"parameter_overrides":{"DISTANCE":500}},
    "outputs":{"OUTPUT":"buffer.gpkg"}}],"targets":["buffer"]
}
```

后继输入用 `{"step":"buffer","output":"OUTPUT"}`。已有历史输入可以用 `{"execution_id":"...","output":"OUTPUT","adopt_current":true,"reason":"采用当前成果"}`。这不能证明旧文件从未改变。

首版受控QGIS覆盖 native:reprojectlayer、buffer、intersection、clip、dissolve、fixgeometries。其他算法仍可用普通工具或受控Python；本接口暂不封存数据库、工程变量和插件副作用。

## Python

Python 步骤的 changes 必须声明 `job_contract:true`、`side_effects:"outputs_only"`。脚本读取 `sys.argv[1]` 的 JSON，其中有 inputs、parameters、outputs，值为明确文件路径或参数。cwd 和 __file__ 都指向新 attempt。需旁置的辅助文件用 dependencies 声明。

使用 patches：`[{"expected_sha256":"<历史快照指纹>","old_text":"<唯一原文>","new_text":"<修正原文>"}]`。后续补丁的 expected_sha256 可以省略。

或使用 `candidate_script:"<绝对路径>"` 和 `expected_sha256:"<候选指纹>"`。两种修改方式互斥。

`dependencies` 示例：`{"helper.py":{"path":"<绝对路径>","expected_sha256":"<指纹>"}}`。job_parameters 传递业务参数。明确无随机性和隐藏输入时可声明 `deterministic:true`，以允许修复家族内复用。程序无法静态证明这个声明；不确定时保持关闭。

脚本只能写声明 outputs 和 GIS_AGENT_RESULT_PATH。脚本应显式读取 job 中的输入；原目录相对依赖需要外置。没有保存的内存数据无法恢复。

## 版本和故障

只接受关闭的本地 GPKG、自包含 TIFF、JSON、CSV、NPY 和明确代码依赖。活动日志、栅格 sidecar、网络和数据库不自动复用。输入封存到新修订目录，实际输出按内容核验。

修订继承用新的 repair_id 和 parent_repair；同 ID 的不同计划会拒绝。成功子阶段可复用，失败和 unknown 不作缓存。相同 ID 的终态请求不重新执行。unknown 需要人工核对现场或新修订明确采用已核对输入。

本工具信任本机脚本的依赖和副作用声明，未提供操作系统沙箱。是否需要修复、如何修复和专业核查仍由当前 Agent 判断。
