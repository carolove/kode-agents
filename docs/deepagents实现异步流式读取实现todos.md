使用异步流式处理来实时获取 todos：

关键修改：
agent.py - 新增 astream_with_events 方法：
使用 astream 配合 stream_mode=["messages", "updates"] 和 subgraphs=True
监听 updates stream 中的 todos 变化
通过回调函数 on_todos、on_text、on_tool_call 实时通知
main.py - 改为异步流式：
使用 asyncio.run() 运行异步会话
print_todos() - 实时渲染 todo 列表
print_text() - 流式输出文本
print_tool_call() - 显示工具调用
这个实现参考了 open-ptc-agent 的 executor.py（第 299-308 行），使用相同的流式事件处理模式来捕获 todos 更新。