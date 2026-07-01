# Vendor Due Diligence (VDD) Prototype

An AI-powered multi-agent system designed to automate deep-dive due diligence and supply chain mapping for corporate vendors. The system investigates companies across multiple risk vectors and recursively maps out supply chains, evaluating risks at every tier.

## What It Does

The VDD Prototype streamlines the traditionally manual process of vendor risk assessment by employing specialized AI agents. 

- **Comprehensive Risk Analysis:** Specialized agents autonomously research different vectors including KYB (Know Your Business), Sanctions, Financials, ESG (Environmental, Social, and Governance), Resilience, and Adverse Media.
- **Deterministic Risk Scoring:** Enforces programmatic risk aggregation to prevent AI hallucinations and ensure perfectly consistent executive summaries.
- **Hierarchical Supply Chain Mapping:** Recursively discovers and visually maps the relationships between target companies, their parent companies, and their downstream suppliers using a Neo4j graph database.
- **Real-Time Execution Monitoring:** A WebSocket-based live terminal and dynamic graph allow users to watch the AI agents actively research and construct the supply chain in real-time.
- **Interactive Reporting:** Generates comprehensive risk reports with color-coded severity indicators, detailed historical audit logs, and interactive supply chain maps.

## Architecture

The system is built on a decoupled client-server architecture:
- **Frontend (React/Vite):** A modern, responsive dashboard featuring interactive Dagre/ReactFlow graphs for visualizing complex supply chains, alongside historical report management.
- **Backend (FastAPI & Python):** A DAG-based execution orchestrator (`FlowEngine`) that manages a network of specialized AI sub-agents running concurrently in parallel to maximize analysis speed. Powered by Gemini 3.5 Flash.
- **Graph Database (Neo4j):** Stores the relational data between entities, allowing for complex queries and relationship mapping across the supply chain.

## Prerequisites

Before running the system, ensure you have the following installed:
- **Python 3.12+**
- **Node.js 18+**
- **Neo4j Database** (Running locally via Desktop/Docker, or hosted on AuraDB)

## Setup & Configuration

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
GOOGLE_API_KEY=your_gemini_key

# Research Data Providers
OPENSANCTIONS_API_KEY=your_opensanctions_key
COMPANIES_HOUSE_API_KEY=your_companies_house_key
FMP_API_KEY=your_fmp_key
NEWSAPI_KEY=your_news_key
TAVILY_API_KEY=your_tavily_key

# Graph Database Configuration
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password

# Testing / Demo
USE_MOCK=False
```

### 2. Frontend Configuration
Install the dependencies for the React dashboard:
```bash
cd frontend
npm install
```

## Running the System

You will need two separate terminal windows to run both the backend API and the frontend dashboard simultaneously.

**1. Start the Backend API:**
In the root directory, with your virtual environment activated:
```bash
python server.py
```
*The API will be available at `http://localhost:8000`.*

**2. Start the Frontend Dashboard:**
In a separate terminal, navigate to the frontend directory:
```bash
cd frontend
npm run dev
```
*The web dashboard will be accessible at `http://localhost:5173`.*
