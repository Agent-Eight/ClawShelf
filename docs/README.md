# ClawShelf 设计文档

这组文档解释 ClawShelf 的产品设计，而不是重复安装说明或命令手册。建议按以下顺序阅读：

1. [产品定位：ClawShelf 想解决什么问题](product-positioning.md)
   - 为什么“把资料存起来并能搜索”还不够；
   - ClawShelf 与普通 knowledge base 的区别；
   - 产品的核心价值、边界和设计原则。
2. [神经元模型：资料之间如何建立连接](neuron-model.md)
   - 资料、轴突、树突和突触分别代表什么；
   - 候选连接如何生成、验证和升级为 P1；
   - 这个类比能解释什么，不能解释什么。
3. [用户工作流：从选择文件夹到采取行动](user-workflow.md)
   - 首次启用、后台处理、主动通知和按需研究；
   - P1、P2、`intake_deferred` 的用户含义；
   - 用户可见产物及不同命令在旅程中的位置。

相关的实现级文档：

- [ClawShelf Skill Design](skill-design.md)
- [Idea Generation Method](idea-generation-method.md)
- [命令参考](../references/commands.md)
- [组件契约](../references/component-contracts.md)
- [Watcher 与通知](../references/watch-hooks.md)

