import { useState } from "react"
import { Copy, Check } from "lucide-react"

// ─── VSCode-style token colours ────────────────────────────────────────────
//  We do lightweight regex-based highlighting – no external deps needed.

type Token = { type: string; value: string }

function tokenize(code: string, lang: string): Token[] {
  const tokens: Token[] = []
  let remaining = code

  const rules: { type: string; re: RegExp }[] =
    lang === "json"
      ? [
          { type: "string",  re: /^"(?:[^"\\]|\\.)*"/ },
          { type: "number",  re: /^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/ },
          { type: "keyword", re: /^(?:true|false|null)/ },
          { type: "punct",   re: /^[{}[\]:,]/ },
          { type: "space",   re: /^\s+/ },
        ]
      : lang === "bash" || lang === "curl"
      ? [
          { type: "comment", re: /^#[^\n]*/ },
          { type: "string",  re: /^'(?:[^'\\]|\\.)*'|^"(?:[^"\\]|\\.)*"/ },
          { type: "flag",    re: /^-{1,2}[\w-]+/ },
          { type: "cmd",     re: /^(?:curl|export|echo|python3?|php|dotnet|node)\b/ },
          { type: "var",     re: /^\$\w+/ },
          { type: "space",   re: /^\s+/ },
          { type: "other",   re: /^[^\s#"'$-]+/ },
        ]
      : lang === "python"
      ? [
          { type: "comment",  re: /^#[^\n]*/ },
          { type: "string",   re: /^"""[\s\S]*?"""|^'''[\s\S]*?'''|^"(?:[^"\\]|\\.)*"|^'(?:[^'\\]|\\.)*'/ },
          { type: "keyword",  re: /^(?:import|from|def|class|return|if|else|elif|for|while|with|as|in|not|and|or|True|False|None|async|await|raise|try|except|finally|pass|break|continue)\b/ },
          { type: "builtin",  re: /^(?:print|len|range|str|int|float|list|dict|open|super|self)\b/ },
          { type: "number",   re: /^-?\d+(?:\.\d+)?/ },
          { type: "func",     re: /^[a-zA-Z_]\w*(?=\s*\()/ },
          { type: "space",    re: /^\s+/ },
          { type: "other",    re: /^\S+/ },
        ]
      : lang === "javascript" || lang === "typescript"
      ? [
          { type: "comment",  re: /^\/\/[^\n]*|^\/\*[\s\S]*?\*\// },
          { type: "string",   re: /^`[\s\S]*?`|^"(?:[^"\\]|\\.)*"|^'(?:[^'\\]|\\.)*'/ },
          { type: "keyword",  re: /^(?:const|let|var|function|return|async|await|import|export|from|default|new|this|class|extends|if|else|for|while|try|catch|finally|throw|typeof|instanceof|of|in|true|false|null|undefined)\b/ },
          { type: "builtin",  re: /^(?:console|fetch|JSON|Promise|Array|Object|Error|process|require|module)\b/ },
          { type: "number",   re: /^-?\d+(?:\.\d+)?/ },
          { type: "func",     re: /^[a-zA-Z_$][\w$]*(?=\s*\()/ },
          { type: "space",    re: /^\s+/ },
          { type: "other",    re: /^\S+/ },
        ]
      : lang === "csharp"
      ? [
          { type: "comment",  re: /^\/\/[^\n]*|^\/\*[\s\S]*?\*\// },
          { type: "string",   re: /^@?"(?:[^"\\]|\\.)*"|^'(?:[^'\\]|\\.)*'/ },
          { type: "keyword",  re: /^(?:using|namespace|class|public|private|static|void|string|int|bool|var|new|return|async|await|if|else|for|foreach|while|try|catch|finally|throw|null|true|false|base|this|override|virtual|abstract|interface|enum|Task|List|Dictionary)\b/ },
          { type: "builtin",  re: /^(?:Console|HttpClient|StringContent|JsonSerializer|JsonSerializerOptions|Thread|Task|Environment)\b/ },
          { type: "number",   re: /^-?\d+(?:\.\d+)?/ },
          { type: "func",     re: /^[A-Z][a-zA-Z0-9]*(?=\s*[(<])/ },
          { type: "space",    re: /^\s+/ },
          { type: "other",    re: /^\S+/ },
        ]
      : lang === "php"
      ? [
          { type: "comment",  re: /^\/\/[^\n]*|^#[^\n]*|^\/\*[\s\S]*?\*\// },
          { type: "string",   re: /^"(?:[^"\\]|\\.)*"|^'(?:[^'\\]|\\.)*'/ },
          { type: "keyword",  re: /^(?:require|use|function|return|echo|new|class|extends|if|else|foreach|for|while|try|catch|finally|throw|null|true|false|namespace|public|private|static|protected|abstract|interface|array)\b/ },
          { type: "var",      re: /^\$[a-zA-Z_]\w*/ },
          { type: "func",     re: /^[a-zA-Z_]\w*(?=\s*\()/ },
          { type: "number",   re: /^-?\d+(?:\.\d+)?/ },
          { type: "space",    re: /^\s+/ },
          { type: "other",    re: /^\S+/ },
        ]
      : [
          { type: "space", re: /^\s+/ },
          { type: "other", re: /^\S+/ },
        ]

  while (remaining.length > 0) {
    let matched = false
    for (const rule of rules) {
      const m = remaining.match(rule.re)
      if (m) {
        tokens.push({ type: rule.type, value: m[0] })
        remaining = remaining.slice(m[0].length)
        matched = true
        break
      }
    }
    if (!matched) {
      tokens.push({ type: "other", value: remaining[0] })
      remaining = remaining.slice(1)
    }
  }
  return tokens
}

const TOKEN_COLORS: Record<string, string> = {
  comment:  "#6a9955",
  string:   "#ce9178",
  keyword:  "#569cd6",
  builtin:  "#4ec9b0",
  func:     "#dcdcaa",
  number:   "#b5cea8",
  var:      "#9cdcfe",
  flag:     "#9cdcfe",
  cmd:      "#569cd6",
  punct:    "#d4d4d4",
  space:    "transparent",
  other:    "#d4d4d4",
}

function SyntaxCode({ code, lang }: { code: string; lang: string }) {
  const tokens = tokenize(code, lang)
  return (
    <code style={{ fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace", fontSize: "0.8rem", lineHeight: 1.7 }}>
      {tokens.map((t, i) => (
        <span key={i} style={{ color: TOKEN_COLORS[t.type] ?? "#d4d4d4" }}>
          {t.value}
        </span>
      ))}
    </code>
  )
}

// ─── Tab definitions ─────────────────────────────────────────────────────────

interface TabDef {
  id: string
  label: string
  lang: string
  icon: string
}

const TABS: TabDef[] = [
  { id: "curl",   label: "cURL",       lang: "bash",       icon: "🐚" },
  { id: "python", label: "Python",     lang: "python",     icon: "🐍" },
  { id: "js",     label: "JavaScript", lang: "javascript", icon: "⚡" },
  { id: "php",    label: "PHP",        lang: "php",        icon: "🐘" },
  { id: "csharp", label: "C#",         lang: "csharp",     icon: "🔷" },
  { id: "images", label: "Images (T2I)", lang: "python",     icon: "🖼️" },
  { id: "env",    label: ".env Config", lang: "bash",      icon: "⚙️" },
  { id: "json",   label: "JSON",       lang: "json",       icon: "{ }" },
  { id: "mcp",    label: "MCP Config", lang: "json",       icon: "🔌" },
]

// ─── Code templates (base_url is injected at render time) ─────────────────

function getExamples(base: string, models: string[]): Record<string, string> {
  const modelList = models.length > 0 ? models.join(", ") : "qwen-max, gpt-4o, claude-3-5-sonnet";
  
  return {
    env: `# 📄 .env configuration for Agents (Hermes, AutoGPT, OpenWebUI)
# ────────────────────────────────────────────────────────────

# OpenAI-Compatible Base URL (Important: include /v1)
OPENAI_API_BASE=${base}/v1

# Authorization Key (Master Admin or API Key)
OPENAI_API_KEY=YOUR_API_KEY

# Available Models (Real & Aliases)
# ${modelList}
MODEL_NAME=qwen-max

# Image Generation (T2I)
IMAGE_MODEL=dall-e-3
# Note: This gateway routes dall-e-3 to Qwen Wanx-V2

# Tools / Search enabling (Specific for some agents)
ENABLE_SEARCH=true
ENABLE_THINKING=true`,

    images: `# 🖼️ Text-to-Image (T2I) Generation
# ────────────────────────────────────────────────────────────
# Generate professional images using Qwen (Stable/Wanx).

# ── Python (OpenAI SDK) ──
from openai import OpenAI
client = OpenAI(api_key="YOUR_API_KEY", base_url="${base}/v1")

response = client.images.generate(
    model="dall-e-3",
    prompt="A magical forest with floating crystals, cinematic lighting, 8k",
    n=1,
    size="1024x1024"
)
print(response.data[0].url)

# ── cURL (Direct API) ──
curl ${base}/v1/images/generations \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "model": "dall-e-3",
    "prompt": "An astronaut riding a horse on Mars",
    "n": 1
  }'`,
    curl: `# ── Chat Completion (OpenAI-compatible) ──────────────────
curl ${base}/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "model": "qwen-max",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'

# ── Image Generation ──────────────────────────────────────
curl ${base}/v1/images/generations \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "model": "dall-e-3",
    "prompt": "A futuristic city at sunset",
    "n": 1, "size": "1024x1024"
  }'

# ── Anthropic-compatible ──────────────────────────────────
curl ${base}/anthropic/v1/messages \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: YOUR_API_KEY" \\
  -H "anthropic-version: 2023-06-01" \\
  -d '{
    "model": "claude-3-5-sonnet",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'`,

    python: `# pip install openai
from openai import OpenAI

client = OpenAI(
    api_key="YOUR_API_KEY",
    base_url="${base}/v1"
)

# ── Streaming Chat ────────────────────────────────────────
stream = client.chat.completions.create(
    model="qwen-max",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True
)
for chunk in stream:
    delta = chunk.choices[0].delta
    if delta.content:
        print(delta.content, end="", flush=True)

# ── Image Generation ──────────────────────────────────────
image = client.images.generate(
    model="dall-e-3",
    prompt="A futuristic city at sunset",
    n=1,
    size="1024x1024"
)
print(image.data[0].url)

# ── Tool Use (Function Calling) ───────────────────────────
response = client.chat.completions.create(
    model="qwen-max",
    messages=[{"role": "user", "content": "What is the weather?"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"]
            }
        }
    }]
)
print(response.choices[0].message)`,

    js: `// npm install openai
import OpenAI from "openai";

const client = new OpenAI({
  apiKey: "YOUR_API_KEY",
  baseURL: "${base}/v1",
  dangerouslyAllowBrowser: true, // for browser usage
});

// ── Streaming Chat ────────────────────────────────────────
async function chat() {
  const stream = await client.chat.completions.create({
    model: "qwen-max",
    messages: [{ role: "user", content: "Hello!" }],
    stream: true,
  });

  for await (const chunk of stream) {
    const content = chunk.choices[0]?.delta?.content ?? "";
    process.stdout.write(content);
  }
}

// ── Non-streaming (async/await) ───────────────────────────
async function ask(question) {
  const response = await client.chat.completions.create({
    model: "qwen-max",
    messages: [{ role: "user", content: question }],
  });
  return response.choices[0].message.content;
}

// ── Image Generation ──────────────────────────────────────
async function generateImage(prompt) {
  const image = await client.images.generate({
    model: "dall-e-3",
    prompt,
    n: 1,
    size: "1024x1024",
  });
  return image.data[0].url;
}

chat();`,

    php: `<?php
// composer require guzzlehttp/guzzle

require 'vendor/autoload.php';

use GuzzleHttp\\Client;

$client = new Client([
    'base_uri' => '${base}',
    'headers'  => [
        'Authorization' => 'Bearer YOUR_API_KEY',
        'Content-Type'  => 'application/json',
    ],
]);

// ── Chat Completion ────────────────────────────────────────
$response = $client->post('/v1/chat/completions', [
    'json' => [
        'model'    => 'qwen-max',
        'messages' => [
            ['role' => 'user', 'content' => 'Hello!']
        ],
        'stream' => false,
    ],
]);

$body = json_decode($response->getBody(), true);
echo $body['choices'][0]['message']['content'];

// ── Streaming with callback ────────────────────────────────
$response = $client->post('/v1/chat/completions', [
    'json' => [
        'model'    => 'qwen-max',
        'messages' => [['role' => 'user', 'content' => 'Hello!']],
        'stream'   => true,
    ],
    'stream' => true,
]);

$body = $response->getBody();
while (!$body->eof()) {
    $line = trim($body->read(1024));
    if (str_starts_with($line, 'data: ') && $line !== 'data: [DONE]') {
        $data = json_decode(substr($line, 6), true);
        $content = $data['choices'][0]['delta']['content'] ?? '';
        echo $content;
        flush();
    }
}`,

    csharp: `// dotnet add package OpenAI --version 2.*
using OpenAI;
using OpenAI.Chat;

// ── Client Setup ───────────────────────────────────────────
var clientOptions = new OpenAIClientOptions {
    Endpoint = new Uri("${base}/v1")
};
var client = new ChatClient(
    "qwen-max",
    new System.ClientModel.ApiKeyCredential("YOUR_API_KEY"),
    clientOptions
);

// ── Non-streaming Chat ─────────────────────────────────────
var completion = await client.CompleteChatAsync(
    [new UserChatMessage("Hello!")]
);
Console.WriteLine(completion.Value.Content[0].Text);

// ── Streaming Chat ─────────────────────────────────────────
await foreach (var update in client.CompleteChatStreamingAsync(
    [new UserChatMessage("Tell me a story.")]))
{
    foreach (var part in update.ContentUpdate)
    {
        Console.Write(part.Text);
    }
}

// ── Raw HTTP (no SDK) ──────────────────────────────────────
using var http = new HttpClient();
http.DefaultRequestHeaders.Add("Authorization", "Bearer YOUR_API_KEY");

var payload = new {
    model    = "qwen-max",
    messages = new[] { new { role = "user", content = "Hello!" } },
    stream   = false
};

var response = await http.PostAsJsonAsync(
    "${base}/v1/chat/completions", payload
);
var result = await response.Content.ReadAsStringAsync();
Console.WriteLine(result);`,

    json: `{
  "model": "qwen-max",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "Hello! What can you do?"
    }
  ],
  "stream": true,
  "temperature": 0.7,
  "max_tokens": 2048,
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {
              "type": "string",
              "description": "City name"
            },
            "unit": {
              "type": "string",
              "enum": ["celsius", "fahrenheit"]
            }
          },
          "required": ["city"]
        }
      }
    }
  ]
}`,

    mcp: `// MCP (Model Context Protocol) Configuration
// Add to your claude_desktop_config.json or Cursor / VS Code MCP config:

{
  "mcpServers": {
    "qwen2api": {
      "type": "openai",
      "url": "${base}/v1",
      "apiKey": "YOUR_API_KEY",
      "model": "qwen-max"
    }
  }
}

// ── For Cursor IDE (settings.json) ────────────────────────
{
  "cursor.ai.mcpServers": [
    {
      "name": "qwen2api",
      "url": "${base}/v1",
      "apiKey": "YOUR_API_KEY"
    }
  ]
}

// ── For OpenAI-compatible MCP clients ────────────────────
{
  "servers": {
    "qwen2api-gateway": {
      "command": "npx",
      "args": ["-y", "@openai/mcp-server"],
      "env": {
        "OPENAI_API_KEY": "YOUR_API_KEY",
        "OPENAI_BASE_URL": "${base}/v1",
        "OPENAI_MODEL": "qwen-max"
      }
    }
  }
}`,
  }
}

// ─── Main Component ──────────────────────────────────────────────────────────

interface CodeExamplesProps {
  baseUrl: string
  availableModels?: string[]
}

export default function CodeExamples({ baseUrl, availableModels = [] }: CodeExamplesProps) {
  const [activeTab, setActiveTab] = useState("curl")
  const [copied, setCopied] = useState(false)

  const examples = getExamples(baseUrl, availableModels)
  const currentCode = examples[activeTab] ?? ""
  const currentTab  = TABS.find(t => t.id === activeTab)!

  const handleCopy = () => {
    navigator.clipboard.writeText(currentCode).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div style={{
      borderRadius: "0.75rem",
      border: "1px solid #1e1e2e",
      overflow: "hidden",
      background: "#1e1e2e",
      boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
    }}>
      {/* ── Window chrome ── */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: "0.5rem",
        padding: "0.6rem 1rem",
        background: "#2d2d3f",
        borderBottom: "1px solid #3e3e5e",
      }}>
        <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff5f57", display: "inline-block" }} />
        <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#febc2e", display: "inline-block" }} />
        <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#28c840", display: "inline-block" }} />
        <span style={{ marginLeft: "0.5rem", color: "#888", fontSize: "0.75rem", fontFamily: "monospace" }}>
          qwen2api — {currentTab.label}
        </span>
      </div>

      {/* ── Tabs ── */}
      <div style={{
        display: "flex",
        overflowX: "auto",
        background: "#252537",
        borderBottom: "1px solid #3e3e5e",
        scrollbarWidth: "none",
      }}>
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: "0.55rem 1.1rem",
              fontSize: "0.78rem",
              fontFamily: "monospace",
              cursor: "pointer",
              border: "none",
              borderBottom: activeTab === tab.id ? "2px solid #569cd6" : "2px solid transparent",
              background: activeTab === tab.id ? "#1e1e2e" : "transparent",
              color: activeTab === tab.id ? "#d4d4d4" : "#888",
              whiteSpace: "nowrap",
              display: "flex",
              alignItems: "center",
              gap: "0.35rem",
              transition: "all 0.15s",
            }}
          >
            <span style={{ fontSize: "0.85rem" }}>{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Code area ── */}
      <div style={{ position: "relative" }}>
        {/* Copy button */}
        <button
          onClick={handleCopy}
          title="Copy code"
          style={{
            position: "absolute",
            top: "0.75rem",
            right: "0.75rem",
            zIndex: 10,
            display: "flex",
            alignItems: "center",
            gap: "0.3rem",
            padding: "0.3rem 0.65rem",
            borderRadius: "0.375rem",
            border: "1px solid #3e3e5e",
            background: copied ? "#1a3a1a" : "#2d2d3f",
            color: copied ? "#28c840" : "#888",
            fontSize: "0.72rem",
            cursor: "pointer",
            fontFamily: "monospace",
            transition: "all 0.2s",
          }}
        >
          {copied
            ? <><Check size={12} /> Copied!</>
            : <><Copy size={12} /> Copy</>
          }
        </button>

        {/* Line numbers + code */}
        <div style={{
          display: "flex",
          overflowX: "auto",
          overflowY: "auto",
          maxHeight: "480px",
          padding: "1rem 0",
        }}>
          {/* Line numbers */}
          <div style={{
            flexShrink: 0,
            paddingLeft: "1rem",
            paddingRight: "0.75rem",
            textAlign: "right",
            color: "#4e4e6e",
            fontFamily: "monospace",
            fontSize: "0.8rem",
            lineHeight: 1.7,
            userSelect: "none",
            borderRight: "1px solid #2d2d3f",
          }}>
            {currentCode.split("\n").map((_, i) => (
              <div key={i}>{i + 1}</div>
            ))}
          </div>

          {/* Code */}
          <pre style={{
            margin: 0,
            padding: "0 1.25rem",
            flex: 1,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            overflowX: "hidden",
          }}>
            <SyntaxCode code={currentCode} lang={currentTab.lang} />
          </pre>
        </div>
      </div>
    </div>
  )
}
