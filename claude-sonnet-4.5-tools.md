# Claude Sonnet 4.5 — Complete Tools Reference

> Based on the official Anthropic API documentation at [platform.claude.com](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)

Claude Sonnet 4.5 supports two categories of tools: **Client Tools** (executed on your systems) and **Server Tools** (executed on Anthropic's servers). Additionally, developers can define their own **Custom Tools** and connect **MCP Tools** via the Model Context Protocol.

---

## 1. Bash Tool

- **Type:** Client tool (Anthropic-defined)
- **Version:** `bash_20250124`
- **Description:** Enables Claude to execute shell commands in a persistent bash session, allowing system operations, script execution, and command-line automation. The session persists across tool calls, maintaining state like environment variables and working directory.
- **Key capabilities:**
  - Run shell commands and scripts
  - System operations and automation
  - Package management
  - Process management
- **Best used with:** Text Editor tool and Computer Use tool for comprehensive automation workflows.

---

## 2. Code Execution Tool

- **Type:** Server tool
- **Version:** `code_execution_20250825` (current) / `code_execution_20250522` (legacy, Python-only)
- **Beta header:** `code-execution-2025-08-25`
- **Description:** Allows Claude to run Bash commands and manipulate files (including writing code in multiple languages) in a secure, sandboxed environment. Claude can analyze data, create visualizations, perform complex calculations, run system commands, create and edit files, and process uploaded files directly within the API conversation.
- **Key capabilities:**
  - Bash command execution for system operations and package management
  - File operations: create, view, and edit files directly
  - Multi-language code execution
  - Data analysis and visualization
  - Chart and image generation
- **Powers:** Programmatic Tool Calling and Agent Skills.

---

## 3. Computer Use Tool

- **Type:** Client tool (Anthropic-defined)
- **Version:** `computer_20250124`
- **Beta header:** `computer-use-2025-01-24`
- **Description:** Enables Claude to interact with desktop environments through screenshot capture and mouse/keyboard control for autonomous desktop interaction. Claude Sonnet 4.5 is Anthropic's most accurate model for computer use.
- **Key capabilities:**
  - Screenshot capture (see what's on screen)
  - Mouse control (click, drag, scroll, double-click, triple-click)
  - Keyboard control (type text, key combinations, hold keys)
  - Wait for actions to complete
- **Commands include:** `key`, `type`, `cursor_position`, `mouse_move`, `left_click`, `right_click`, `double_click`, `triple_click`, `scroll`, `hold_key`, `left_mouse_down`, `left_mouse_up`, `wait`, `screenshot`.
- **Note:** Computer use is a beta feature. Claude doesn't connect directly to the environment — your application mediates the interaction.

---

## 4. Text Editor Tool

- **Type:** Client tool (Anthropic-defined)
- **Version:** `text_editor_20250124`
- **Description:** Allows Claude to view and modify text files, helping debug, fix, and improve code or other text documents. Claude can directly interact with files, providing hands-on assistance rather than just suggesting changes.
- **Commands:**
  - `view` — Read file contents or list directory contents
  - `str_replace` — Replace specific text in a file
  - `create` — Create a new file with specified content
  - `insert` — Insert text at a specific line
- **Use cases:** Code debugging, code refactoring, documentation generation, test creation.

---

## 5. Web Search Tool

- **Type:** Server tool
- **Version:** `web_search_20250305`
- **Description:** Gives Claude direct access to real-time web content, allowing it to answer questions with up-to-date information beyond its knowledge cutoff. Claude automatically cites sources from search results as part of its answer.
- **Key features:**
  - Real-time web search
  - Automatic source citations
  - Domain filtering (allowed/blocked domains)
  - Configurable `max_uses` to limit number of searches
  - Works with prompt caching
- **Pricing:** Additional usage-based charges per search performed.

---

## 6. Web Fetch Tool

- **Type:** Server tool
- **Version:** `web_fetch_20250910`
- **Beta header:** `web-fetch-2025-09-10`
- **Description:** Allows Claude to retrieve full content from specified web pages and PDF documents. Unlike web search which returns snippets, web fetch retrieves the complete text content of a page.
- **Key features:**
  - Full page content retrieval
  - PDF text extraction
  - Optional citations
  - Domain filtering (allowed/blocked domains)
  - Configurable `max_uses` and `max_content_tokens`
  - Works with prompt caching
- **Security note:** Claude can only fetch URLs explicitly provided by the user or returned from previous web search/web fetch results — it cannot dynamically construct URLs.

---

## 7. Memory Tool

- **Type:** Client tool (Anthropic-defined)
- **Version:** Uses beta header `context-management-2025-06-27`
- **Description:** Enables Claude to store and retrieve information across conversations through a memory file directory. Claude can create, read, update, and delete files that persist between sessions, allowing it to build knowledge over time without keeping everything in the context window.
- **Key capabilities:**
  - Create, read, update, and delete memory files
  - Persistent storage across conversations
  - Automatic memory check before starting tasks
  - Works with context editing for long-running workflows
- **Use cases:** Maintaining project context, learning from past interactions, building knowledge bases.
- **Note:** Operates client-side — you control where and how data is stored.

---

## 8. Tool Search Tool

- **Type:** Server tool
- **Versions:** `tool_search_tool_regex_20251119` / `tool_search_tool_bm25_20251119`
- **Beta header required**
- **Description:** Enables Claude to work with hundreds or thousands of tools by dynamically discovering and loading them on-demand. Instead of loading all tool definitions into the context window upfront, Claude searches your tool catalog and loads only what's needed.
- **Search modes:**
  - **Regex** (`tool_search_tool_regex_20251119`) — Uses Python `re.search()` patterns to find tools
  - **BM25** (`tool_search_tool_bm25_20251119`) — Uses natural language queries to search
- **Key features:**
  - Searches tool names, descriptions, argument names, and argument descriptions
  - Deferred tool loading with `defer_loading: true`
  - Works with MCP servers
  - Supports custom client-side implementations

---

## 9. Programmatic Tool Calling

- **Type:** Capability (built on Code Execution Tool)
- **Beta header:** `code-execution-2025-08-25`
- **Description:** Allows Claude to write code that calls your custom tools programmatically within the execution container. This enables efficient multi-tool workflows, data filtering before reaching Claude's context, and complex conditional logic — all while reducing latency and token usage.
- **Key benefits:**
  - Reduced latency by batching multiple tool calls in code
  - Data filtering/transformation before results reach Claude's context
  - Complex conditional logic within tool workflows

---

## 10. Custom Tools (User-Defined)

- **Type:** Client tool
- **Description:** Developers can define their own tools with custom names, descriptions, and input schemas. Claude will determine when to use these tools based on the conversation context and call them with properly formatted parameters.
- **Definition includes:**
  - `name` — Tool identifier
  - `description` — What the tool does (guides Claude's decision-making)
  - `input_schema` — JSON Schema defining expected parameters
- **Supports:** Structured outputs with `strict: true` for guaranteed schema conformance.

---

## 11. MCP Tools (Model Context Protocol)

- **Type:** External tools via MCP servers
- **Beta header:** `mcp-client-2025-11-20`
- **Description:** Claude can use tools from MCP servers directly via the Messages API. MCP tool definitions use a schema format similar to Claude's native tool format (rename `inputSchema` to `input_schema`).
- **Integration options:**
  - Build your own MCP client and convert tools
  - Use the MCP connector to connect directly to remote MCP servers without implementing a client

---

## Tool Compatibility Summary

| Tool | Type | Sonnet 4.5 Support | Beta Required |
|------|------|:---:|:---:|
| Bash | Client | ✅ | No |
| Code Execution | Server | ✅ | Yes |
| Computer Use | Client | ✅ | Yes |
| Text Editor | Client | ✅ | No |
| Web Search | Server | ✅ | No |
| Web Fetch | Server | ✅ | Yes |
| Memory | Client | ✅ | Yes |
| Tool Search | Server | ✅ | Yes |
| Programmatic Tool Calling | Server | ✅ | Yes |
| Custom Tools | Client | ✅ | No |
| MCP Tools | External | ✅ | Yes |

---

## Additional Capabilities

Beyond tools, Claude Sonnet 4.5 also supports these complementary features:

- **Extended Thinking** — Enhanced reasoning for complex tasks
- **Vision** — Image and document understanding
- **PDF Support** — Native PDF processing
- **Citations** — Automatic source attribution
- **Structured Outputs** — Guaranteed JSON schema conformance
- **Prompt Caching** — Reuse cached content across turns
- **Batch Processing** — Process multiple requests efficiently
- **Streaming** — Real-time response streaming
- **Context Editing & Compaction** — Manage long conversations
- **Agent Skills** — Modular capabilities extending Claude's functionality (requires Code Execution)

---

*Source: [Anthropic Claude API Documentation](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)*
*Last updated: February 2026*
