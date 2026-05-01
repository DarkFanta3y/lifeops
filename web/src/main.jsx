import React from "react";
import { createRoot } from "react-dom/client";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#2563eb",
          colorText: "#111827",
          colorBgLayout: "#f6f7f9",
          borderRadius: 6,
          fontFamily:
            '"Noto Sans SC", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
        },
        components: {
          Layout: {
            siderBg: "#f3f4f6",
            bodyBg: "#f6f7f9",
          },
          Menu: {
            itemBg: "#f3f4f6",
            itemSelectedBg: "#e5e7eb",
            itemSelectedColor: "#111827",
            itemColor: "#4b5563",
            itemHoverBg: "#e9ecef",
            itemHoverColor: "#111827",
          },
          Card: {
            borderRadiusLG: 6,
          },
        },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
