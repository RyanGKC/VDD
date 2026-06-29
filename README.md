# Vendor Due Diligence (VDD) Prototype

An AI-powered multi-agent system that automates deep-dive due diligence and supply chain mapping for corporate vendors. The system investigates companies across multiple risk vectors (KYB, Sanctions, Financials, ESG, Adverse Media, etc.) and recursively maps out supply chains, evaluating risks at every tier using a Neo4j graph database.

## Features
- **Multi-Agent Architecture**: Specialised AI agents (Sanctions, ESG, Media, Finances, Resilience, etc.) autonomously research different risk vectors.
- **Adaptive Execution**: A Supervisor Agent monitors the pipeline for anomalies and adjusts the investigation flow dynamically.
- **Recursive Supply Chain Mapping**: Discovers suppliers of suppliers, creating a complete supply chain graph mapped into a Neo4j database.
- **Detailed Audit Trails**: Every conclusion is backed by chronological execution logs and raw source data.
- **Mock Data Support**: Capable of running in a safe mock mode to demonstrate functionality without spending API quotas.
- **React Frontend**: A modern, interactive dashboard for submitting reports and visualising the analysis.

## Prerequisites
- **Python 3.12+**
- **Node.js 18+**
- **Neo4j Database** (Running locally or on AuraDB)

## Setup

### 1. Backend Configuration
Create a virtual environment and install the dependencies:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the root directory and configure your API keys:
```env
# Core AI Models
OPENAI_API_KEY=your_openai_key
GOOGLE_API_KEY=your_gemini_key

# Research Data Providers
OPENSANCTIONS_API_KEY=your_opensanctions_key
COMPANIES_HOUSE_API_KEY=your_companies_house_key
FMP_API_KEY=your_fmp_key
NEWSAPI_KEY=your_news_key
TAVILY_API_KEY=your_tavily_key

# Graph Database (Optional: falls back to localhost if omitted)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

### 2. Frontend Configuration
Install the dependencies for the React dashboard:
```bash
cd frontend
npm install
```

## Running the Application

You need to start both the backend server and the frontend application.

**Start the Backend (FastAPI):**
In the root directory, with your virtual environment activated:
```bash
python server.py
```
*The API will be available at `http://localhost:8000`.*

**Start the Frontend (React/Vite):**
In a separate terminal:
```bash
cd frontend
npm run dev
```
*The web dashboard will be available at `http://localhost:5173` (or the port specified by Vite).*

## Architecture Overview
- **`agents/`**: Contains the logic for the individual research sub-agents (e.g., `ESGAgent`, `SanctionsAgent`, `SummaryAgent`, `SupervisorAgent`).
- **`core/`**: Houses the central `FlowEngine` (DAG orchestrator), data models (`models.py`), API clients (`openai_client.py`, `neo4j_client.py`), and real/mock tool functions.
- **`main.py`**: Constructs the agent network and orchestrates the recursive supply chain pipelines.
- **`server.py`**: FastAPI endpoints that expose the pipeline to the React frontend.
