import os
import json
import uvicorn
from datetime import datetime, timedelta
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import anthropic

app = FastAPI()

def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else []

# Load data
projects = load_json("data/projects.json", [])
subcontractors = load_json("data/subcontractors.json", [])
historical_quotes = load_json("data/historical_quotes.json", [])
rfp_responses = load_json("data/rfp_responses.json", [])

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    with open("index.html") as f:
        return f.read()

@app.post("/create-project")
async def create_project(data: dict):
    new_project = {
        "id": len(projects) + 1,
        "name": data.get("name"),
        "address": data.get("address"),
        "trades_needed": data.get("trades", []),
        "budget": data.get("budget"),
        "status": "planning",
        "created_date": datetime.now().isoformat()
    }
    projects.append(new_project)
    return {"success": True, "project": new_project}

@app.post("/generate-rfp")
async def generate_rfp(data: dict):
    project_id = data.get("project_id")
    trade = data.get("trade")
    
    if not project_id or not trade:
        return {"error": "Missing project_id or trade"}
    
    project = next((p for p in projects if p["id"] == project_id), None)
    if not project:
        return {"error": "Project not found"}
    
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    
    system_prompt = """You are an expert construction project manager. Generate a professional RFP email for subcontractors. 
    The email should be clear, detailed, and include all necessary project information. 
    Format it as a complete email with subject line and body."""
    
    user_prompt = f"""Generate an RFP email for:
    Project: {project['name']}
    Address: {project.get('address', 'TBD')}
    Trade: {trade}
    Budget Range: ${project.get('budget', 'TBD')}
    
    Include timeline expectations (quotes needed within 2 weeks) and mention that detailed project drawings are available upon request."""
    
    msg = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-3-haiku-20240307"),
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    return {"rfp_content": msg.content[0].text}

@app.post("/send-rfps")
async def send_rfps(data: dict):
    project_id = data.get("project_id")
    trade = data.get("trade")
    contractor_ids = data.get("contractor_ids", [])
    
    # Mock email sending
    sent_count = len(contractor_ids)
    
    # Create RFP response entries for tracking
    for contractor_id in contractor_ids:
        rfp_responses.append({
            "rfp_id": f"{project_id}_{trade}_{contractor_id}",
            "contractor_id": contractor_id,
            "status": "sent",
            "quote_amount": None,
            "response_date": None,
            "notes": "RFP sent, awaiting response"
        })
    
    return {"success": True, "sent_count": sent_count, "message": f"RFPs sent to {sent_count} contractors"}

@app.post("/analyze-pricing")
async def analyze_pricing(data: dict):
    project_id = data.get("project_id")
    trade = data.get("trade")
    new_quote = data.get("quote_amount")
    
    if not all([project_id, trade, new_quote]):
        return {"error": "Missing required parameters"}
    
    # Get historical data for this trade
    historical = [q for q in historical_quotes if q["trade"].lower() == trade.lower()]
    
    if not historical:
        return {"analysis": "No historical data available for comparison", "anomaly_score": 0}
    
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    
    avg_price = sum(q["price"] for q in historical[-10:]) / min(len(historical), 10)
    price_range = f"${min(q['price'] for q in historical[-10:]):,.0f} - ${max(q['price'] for q in historical[-10:]):,.0f}"
    
    system_prompt = """You are a construction pricing analyst. Analyze the provided quote against historical data and provide insights on whether the pricing is reasonable, high, or low. Flag any significant anomalies."""
    
    user_prompt = f"""Analyze this quote:
    Trade: {trade}
    New Quote: ${new_quote:,.0f}
    Recent Average: ${avg_price:,.0f}
    Historical Range: {price_range}
    
    Provide analysis of whether this quote is reasonable and explain any pricing anomalies."""
    
    msg = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-3-haiku-20240307"),
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    # Calculate anomaly score
    deviation = abs(new_quote - avg_price) / avg_price
    anomaly_score = min(100, deviation * 100)
    
    return {
        "analysis": msg.content[0].text,
        "anomaly_score": round(anomaly_score, 1),
        "avg_price": avg_price,
        "is_anomaly": anomaly_score > 25
    }

@app.get("/project/{project_id}")
async def get_project(project_id: int):
    project = next((p for p in projects if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get relevant subcontractors for this project's trades
    relevant_subs = []
    for trade in project.get("trades_needed", []):
        trade_subs = [s for s in subcontractors if trade.lower() in [t.lower() for t in s.get("trades", [])]]
        relevant_subs.extend(trade_subs[:5])  # Top 5 per trade
    
    # Get RFP responses for this project
    project_responses = [r for r in rfp_responses if r["rfp_id"].startswith(str(project_id))]
    
    return {
        "project": project,
        "subcontractors": relevant_subs,
        "rfp_responses": project_responses
    }

@app.get("/api/projects")
async def get_projects():
    return {"projects": projects}

@app.get("/api/subcontractors/{trade}")
async def get_subcontractors_by_trade(trade: str):
    trade_subs = [s for s in subcontractors if trade.lower() in [t.lower() for t in s.get("trades", [])]]
    return {"subcontractors": trade_subs[:10]}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)