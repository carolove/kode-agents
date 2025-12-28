在claude-code-deepagents中是我现在正想要开发的项目，是一个研究agentic应用开发的项目，base在deepagents框架上，我现在已经完成了两个版本，第一个版本支持了简单的工具使用、第二个版本实现了todos，现在我希望参考claude-code-mini.py的改动，增加subagents 的能力，
1、在claude-code-mini.py这次的改动中，核心就是实现了将tasks分装为subagents的能力，将独立的功能部分切分为sub agents，这样就可以有效的降低主agent中上下文的长度
2、我这个claude-code-deepagents项目，依赖deepagents框架，这个框架的代码位于thirdparts/deepagents，如果对deepagents框架能够提供的能力需要了解可以遍历这个代码仓库，但是在使用deepagents的时候不需要引用源代码导入，在python 环境venv中已经安装该框架了
3、其次在thirdparts/open-ptc-agent中，是另一个使用deepagents框架的成功应用，已经实现了使用deepagents框架实现subagents的应用能力，也可以借鉴，但是不要引入thirdparts/open-ptc-agentz作为软件包，可以把可用的代码直接在claude-code-deepagents/claude_code_deepagents重新实现一次即可



实现总结
我已经成功为 claude-code-deepagents 项目添加了 subagents 能力。以下是主要的修改和新增文件：

新增文件
claude_code_deepagents/subagents/__init__.py - subagents 模块入口
定义了 SUBAGENT_REGISTRY 注册表
提供了 create_subagent_by_name() 和 create_subagents_from_names() 辅助函数
claude_code_deepagents/subagents/explore.py - 探索型子代理
只读代理，用于探索代码、查找文件、搜索
不能修改文件，适合在做修改前的侦察任务
claude_code_deepagents/subagents/code.py - 编码型子代理
完整的编码代理，用于实现功能和修复 bug
有完整的文件读写和 shell 执行权限
claude_code_deepagents/subagents/plan.py - 规划型子代理
规划代理，用于分析代码库和设计实现策略
只读，输出编号的实现计划
修改的文件
claude_code_deepagents/config.py
添加了 enable_subagents 和 subagent_types 配置选项
更新了系统提示，包含 subagent 使用说明
claude_code_deepagents/agent.py
导入 subagents 模块
在 create_coding_agent() 中创建并传递 subagents 到 deepagents 框架
架构说明
这个实现参考了：

claude-code-mini.py 中的 subagent 设计理念（上下文隔离、工具过滤）
open-ptc-agent 的 subagent 实现模式（注册表、配置字典）
deepagents 框架的 SubAgentMiddleware（通过 task 工具调用子代理）
主要优势：

上下文隔离 - 子代理有独立的上下文窗口，避免主代理上下文污染
工具过滤 - explore/plan 类型限制为只读，code 类型有完整权限
易于扩展 - 可通过 SUBAGENT_REGISTRY 轻松添加新的子代理类型

```
# 测试prompt
帮我分析分析thirdparts/open-ptc-agent/libs/ptc-cli/ptc_cli下agents的核心能力，把最重要的能力的代码路径做一下分析并将分析结果写入markdown保存在docs目录
```