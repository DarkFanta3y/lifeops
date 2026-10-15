# 第三方代码声明

`web/src/context/` 下的样式表与组件改编自 [dsh-context](https://github.com/bowenliang123/dsh-context)（作者 bowenliang123），按 Apache License 2.0 授权使用。

- `styles/` 中除 `tokens.css`、`lifeops.css`、`index.js` 外的样式表照搬自 dsh-context `src/client/styles/`，仅删除了 DeepSeek Harness 宿主专用的选择器。
- `components/` 中的 Vue 组件由 dsh-context `src/client/components/` 的 React 组件翻译而来，`kit.js`、`trend.js`、`treemap.js`、`fileActivity.js`、`agentTree.js`、`i18n.js` 由对应的 TypeScript 模块改写。
- 主要改动：React 改为 Vue 3，数据源由 DeepSeek Harness 会话投影改为 LifeOps 的 `/api/.../context` 接口，删除 DNA 模式、附件、通讯面板与系统提示前后缀，文案只保留简体中文。

Apache License 2.0 全文：https://www.apache.org/licenses/LICENSE-2.0
