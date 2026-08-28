# ASTRA 🚀 | Space Situational Intelligence

ASTRA is an intelligent web assistant designed to query space weather and monitor nearby astronomical objects in real time. It uses an agent with **Function / Tool Calling** support via **IBM watsonx.ai** to interpret natural language, request structured parameters from the backend, query public astronomical APIs (such as NASA DONKI or NeoWs), and respond to the user with accurate, contextualised information.

---

## 🌌 Features

* **Space Weather Monitoring:** Detection and analysis of solar flares, coronal mass ejections (CMEs), and potential impacts on telecommunications or power grids.
* **Near-Earth Objects (NEOs):** Query of potentially hazardous asteroids, close-approach dates, estimated velocity, and size.
* **Events and Celestial Bodies:** Tracking of visible comets and upcoming meteors.
* **Agent Architecture with Tool Calling:** The IBM watsonx model dynamically decides when and which tool to invoke on the FastAPI server via asynchronous calls using `httpx`.

---

## 🛠️ Technology Stack

* **Backend:** FastAPI, Uvicorn, Pydantic, HTTPX.
* **AI / Orchestration:** `ibm-watsonx-ai` (function/tool calling support).
* **Frontend:** HTML5, Tailwind CSS, JavaScript.

---

## 📁 Project Structure

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
```
