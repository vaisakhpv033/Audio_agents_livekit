import os
import re
import json
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import markdown

from database import init_db, save_report, get_all_reports, get_report_by_job_id

# Initialize Database on startup
init_db()

app = FastAPI(title="SBI Mutual Fund Voice Agent Report Portal")

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Mount Static Files
os.makedirs(os.path.join(BASE_DIR, "static", "css"), exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

class ReportPayload(BaseModel):
    job_id: str
    room_id: str
    room: str
    started_at: str | None = None
    ended_at: str
    summary: dict | str | None = None
    chat_history: dict | None = None

def parse_summary_scores(summary_data: dict | str | None) -> dict:
    if not summary_data:
        return {
            "overall": 0,
            "rapport": 0,
            "discovery": 0,
            "product_knowledge": 0,
            "communication": 0,
            "objection_handling": 0,
            "recommendation_quality": 0,
            "compliance": 0,
            "closing": 0,
            "readiness": "N/A",
            "is_structured": False
        }
    
    # If summary is a dict (conforming to QAReportCard schema)
    if isinstance(summary_data, dict):
        return {
            "overall": summary_data.get("overall_score", 0),
            "rapport": summary_data.get("rapport", {}).get("score", 0),
            "discovery": summary_data.get("discovery", {}).get("score", 0),
            "product_knowledge": summary_data.get("product_knowledge", {}).get("score", 0),
            "communication": summary_data.get("communication", {}).get("score", 0),
            "objection_handling": summary_data.get("objection_handling", {}).get("score", 0),
            "recommendation_quality": summary_data.get("recommendation_quality", {}).get("score", 0),
            "compliance": summary_data.get("compliance", {}).get("score", 0),
            "closing": summary_data.get("closing", {}).get("score", 0),
            "readiness": summary_data.get("readiness_assessment", "Developing"),
            "is_structured": True
        }
    
    # If summary is a string, check if it is serialised JSON
    if isinstance(summary_data, str) and summary_data.strip().startswith("{"):
        try:
            parsed = json.loads(summary_data)
            return parse_summary_scores(parsed)
        except Exception:
            pass
            
    # Otherwise parse as markdown text (backward compatibility)
    scores = {}
    
    # Overall score
    overall_match = re.search(r"Overall Score:\s*(\d+)", summary_data, re.IGNORECASE)
    scores["overall"] = int(overall_match.group(1)) if overall_match else 0
    
    # Category scores
    categories = {
        "rapport": r"Rapport & Professionalism:\s*(\d+)",
        "discovery": r"Discovery & Needs Analysis:\s*(\d+)",
        "product_knowledge": r"Product Knowledge:\s*(\d+)",
        "communication": r"Communication Skills:\s*(\d+)",
        "objection_handling": r"Objection Handling:\s*(\d+)",
        "recommendation_quality": r"Recommendation Quality:\s*(\d+)",
        "compliance": r"Compliance & Ethical Conduct:\s*(\d+)",
        "closing": r"Closing Effectiveness:\s*(\d+)"
    }
    
    for name, pattern in categories.items():
        m = re.search(pattern, summary_data, re.IGNORECASE)
        scores[name] = int(m.group(1)) if m else 0
        
    # Readiness Assessment
    readiness_options = [
        "Production Ready",
        "Ready With Supervision",
        "Developing",
        "Needs Significant Coaching",
        "Not Ready"
    ]
    readiness = "Developing"
    
    readiness_section = re.search(r"### Readiness Assessment(.*?)(?:---|$$)", summary_data, re.DOTALL | re.IGNORECASE)
    if readiness_section:
        section_text = readiness_section.group(1)
        for option in readiness_options:
            if option.lower() in section_text.lower():
                readiness = option
                break
    else:
        for option in readiness_options:
            if option.lower() in summary_data.lower():
                readiness = option
                break
                
    scores["readiness"] = readiness
    scores["is_structured"] = False
    return scores

# Helper to deserialize and parse chat_history for UI rendering
def clean_chat_history(chat_history_str: str | None) -> list:
    if not chat_history_str:
        return []
    try:
        data = json.loads(chat_history_str)
        items = data.get("items", [])
        cleaned = []
        for item in items:
            if item.get("type") != "message":
                continue
            
            role = item.get("role")
            if role == "system":
                continue
                
            content_list = item.get("content", [])
            text = ""
            if isinstance(content_list, list):
                text = " ".join([str(c) for c in content_list if isinstance(c, str)])
            elif isinstance(content_list, str):
                text = content_list
                
            if not text.strip():
                continue
                
            cleaned.append({
                "role": role,
                "text": text,
                "interrupted": item.get("interrupted", False)
            })
        return cleaned
    except Exception as e:
        print("Error parsing chat history:", e)
        return []

# Helper Jinja filter/function to format ISO datetimes
def format_datetime(iso_str: str | None) -> str:
    if not iso_str:
        return "N/A"
    try:
        # e.g. "2026-06-25T14:41:21.123Z" -> "June 25, 2026 14:41:21"
        clean_str = iso_str.rstrip("Z").split(".")[0]
        dt = datetime.fromisoformat(clean_str)
        return dt.strftime("%b %d, %Y %I:%M %p")
    except Exception:
        return iso_str

# Helper Jinja filter to format duration
def format_duration(seconds: int | None) -> str:
    if seconds is None or seconds == 0:
        return "Unknown"
    minutes = seconds // 60
    secs = seconds % 60
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"

# Register helper functions
templates.env.globals.update(format_datetime=format_datetime, format_duration=format_duration)

@app.post("/api/reports")
async def receive_report(payload: ReportPayload):
    try:
        # Parse scores to store the overall score in DB
        scores = parse_summary_scores(payload.summary)
        
        summary_str = None
        if payload.summary:
            if isinstance(payload.summary, dict):
                summary_str = json.dumps(payload.summary)
            else:
                summary_str = payload.summary
                
        chat_history_str = None
        if payload.chat_history:
            chat_history_str = json.dumps(payload.chat_history)
            
        save_report(
            job_id=payload.job_id,
            room_id=payload.room_id,
            room=payload.room,
            started_at=payload.started_at,
            ended_at=payload.ended_at,
            summary=summary_str,
            overall_score=scores["overall"],
            chat_history=chat_history_str
        )
        return {"status": "success", "message": f"Report for job {payload.job_id} saved successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    reports = get_all_reports()
    
    # Calculate stats
    total_calls = len(reports)
    avg_score = 0
    readiness_counts = {
        "Production Ready": 0,
        "Ready With Supervision": 0,
        "Developing": 0,
        "Needs Significant Coaching": 0,
        "Not Ready": 0
    }
    
    for r in reports:
        # parse each report's score details
        scores = parse_summary_scores(r["summary"])
        r["scores"] = scores
        avg_score += r["overall_score"]
        
        r_type = scores["readiness"]
        if r_type in readiness_counts:
            readiness_counts[r_type] += 1
            
    if total_calls > 0:
        avg_score = int(avg_score / total_calls)
    else:
        avg_score = 0
        
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "reports": reports,
            "stats": {
                "total_calls": total_calls,
                "avg_score": avg_score,
                "readiness": readiness_counts
            }
        }
    )

@app.get("/reports/{job_id}", response_class=HTMLResponse)
async def report_detail(request: Request, job_id: str):
    report = get_report_by_job_id(job_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
        
    report_card = None
    summary_html = ""
    summary_raw = report.get("summary")
    
    if summary_raw:
        if summary_raw.strip().startswith("{"):
            try:
                report_card = json.loads(summary_raw)
            except Exception:
                pass
        
        if not report_card:
            # Fallback to old markdown rendering
            summary_html = markdown.markdown(summary_raw)
            
    scores = parse_summary_scores(report_card or summary_raw)
    chat_history_list = clean_chat_history(report.get("chat_history"))
    
    return templates.TemplateResponse(
        request=request,
        name="report_detail.html",
        context={
            "report": report,
            "scores": scores,
            "summary_html": summary_html,
            "report_card": report_card,
            "chat_history": chat_history_list
        }
    )
