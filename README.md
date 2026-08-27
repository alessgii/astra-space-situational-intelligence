# ASTRA 🚀 | Space Situational Intelligence

ASTRA es un asistente web inteligente diseñado para consultar el clima espacial y el monitoreo de objetos astronómicos cercanos en tiempo real. Utiliza un agente con soporte de **Function / Tool Calling** a través de **IBM watsonx.ai** para interpretar el lenguaje natural, solicitar parámetros estructurados al backend, consultar APIs públicas astronómicas (como NASA DONKI o NeoWs) y responder al usuario con información precisa y contextualizada.

---

## 🌌 Características

* **Monitoreo de Clima Espacial:** Detección y análisis de llamaradas solares (solar flares), eyecciones de masa coronal (CME) y posibles impactos en telecomunicaciones o redes eléctricas.
* **Objetos Cercanos a la Tierra (NEOs):** Consulta de asteroides potencialmente peligrosos, fechas de aproximación cercana, velocidad y tamaño estimado.
* **Eventos y Cuerpos Celestes:** Registro de cometas visibles y meteoros próximos.
* **Arquitectura de Agente con Tool Calling:** El modelo de IBM watsonx decide dinámicamente cuándo y qué herramienta ejecutar en el servidor FastAPI mediante llamadas asíncronas con `httpx`.

---

## 🛠️ Stack Tecnológico

* **Backend:** FastAPI, Uvicorn, Pydantic, HTTPX.
* **IA / Orquestación:** `ibm-watsonx-ai` (soporte de llamadas a funciones/tools).
* **Frontend:** HTML5, TailwindsCSS, JavaScript.

---

## 📁 Estructura del Proyecto

```text
ASTRA/
├── static/
│   ├── css/
│   ├── js/
│   └── index.html
├── .env.example
├── .gitignore
├── astra_server.py
├── README.md
└── requirements.txt