# Exemplos de Uso (Dual Mode)

O gateway agora suporta os seguintes modos principais via endpoint OpenAI-compatible:
1. **Qwen (Default):** `model: "qwen-plus"`
2. **Somar (Dual):** `model: "dual-sum"`

### 1. cURL
```bash
curl http://localhost:7860/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer SEU_TOKEN" \
  -d '{
    "model": "dual-sum",
    "messages": [{"role": "user", "content": "Explique o que é fissão nuclear"}],
    "stream": true
  }'
```

### 2. JavaScript (Fetch)
```javascript
const response = await fetch("http://localhost:7860/v1/chat/completions", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": "Bearer SEU_TOKEN"
  },
  body: JSON.stringify({
    model: "dual-sum",
    messages: [{role: "user", content: "Olá!"}],
    stream: true
  })
});

const reader = response.body.getReader();
while (true) {
  const {done, value} = await reader.read();
  if (done) break;
  console.log(new TextDecoder().decode(value));
}
```

### 3. Python (OpenAI SDK)
```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:7860/v1", api_key="SEU_TOKEN")

stream = client.chat.completions.create(
    model="dual-sum",
    messages=[{"role": "user", "content": "Diga oi"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### 4. C# (HttpClient)
```csharp
using var client = new HttpClient();
client.DefaultRequestHeaders.Add("Authorization", "Bearer SEU_TOKEN");

var requestData = new {
    model = "dual-sum",
    messages = new[] { new { role = "user", content = "Teste" } },
    stream = true
};

var response = await client.PostAsJsonAsync("http://localhost:7860/v1/chat/completions", requestData);
// Processar stream aqui...
```

### 5. PHP
```php
<?php
$ch = curl_init("http://localhost:7860/v1/chat/completions");
curl_setopt($ch, CURLOPT_HTTPHEADER, [
    "Content-Type: application/json",
    "Authorization: Bearer SEU_TOKEN"
]);
curl_setopt($ch, CURLOPT_POST, 1);
curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode([
    "model" => "dual-sum",
    "messages" => [["role" => "user", "content" => "Oi"]]
]));
curl_exec($ch);
curl_close($ch);
?>
```

### 6. Listar Modelos Disponíveis (Dynamic Discovery)
Este endpoint retorna os modelos reais detectados no provedor original, sem aliases.

**cURL:**
```bash
curl http://localhost:7860/v1/models \
  -H "Authorization: Bearer SEU_TOKEN"
```

**Python (OpenAI SDK):**
```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:7860/v1", api_key="SEU_TOKEN")

models = client.models.list()
for model in models.data:
    print(f"Model ID: {model.id}")
```
