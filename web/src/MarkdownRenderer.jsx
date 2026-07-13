import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { API_BASE } from "./api.js";

function MarkdownImage({ src = "", alt = "", ...props }) {
  const resolvedSrc = src.startsWith("/api/") ? `${API_BASE}${src}` : src;
  return <img src={resolvedSrc} alt={alt} {...props} />;
}

export default function MarkdownRenderer({ content, emptyText = "" }) {
  const markdown = content?.trim() ? content : emptyText;
  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ img: MarkdownImage }} skipHtml>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
