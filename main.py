import os
import re
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import markdown

from database import init_db, save_report, get_all_reports, get_report_by_job_id, update_report_summary
from schemas import ReportPayload
from services.gemini import evaluate_chat_history

# Initialize Database on startup
init_db()

app = FastAPI(title="Ira.ai Voice Agent Report Portal")

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Mount Static Files
os.makedirs(os.path.join(BASE_DIR, "static", "css"), exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

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

# Helper Jinja filter/function to format ISO datetimes to IST (UTC+5:30)
def format_datetime(iso_str: str | None) -> str:
    if not iso_str:
        return "N/A"
    try:
        # Normalize timezone suffix Z to +00:00
        dt_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # Convert to IST (UTC+5:30)
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        dt_ist = dt.astimezone(ist_tz)
        return dt_ist.strftime("%b %d, %Y %I:%M %p")
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

def parse_room_details(room: str) -> dict:
    customer_name = "N/A"
    agent_type = "Voice Agent"
    sales_rep = "N/A"
    
    if not room:
        return {
            "customer_name": customer_name,
            "agent_type": agent_type,
            "sales_rep": sales_rep
        }
        
    # Check for "MF-[CustomerName]-[Sales]-Call" pattern (e.g. MF-RahulNair-SBI-Call)
    if room.startswith("MF-") and room.endswith("-Call"):
        parts = room.split("-")
        if len(parts) >= 4:
            cust = parts[1]
            # Convert CamelCase or raw name into space-separated
            import re
            cust_split = re.findall(r'[A-Z][a-z]*', cust)
            if cust_split:
                customer_name = " ".join(cust_split)
            else:
                customer_name = cust
    elif "mutual fund discussion" in room.lower():
        parts = room.split(" ")
        if len(parts) > 0:
            customer_name = parts[0].capitalize()
    elif room == "console-room":
        customer_name = "Console User"
        agent_type = "Voice Agent"
        
    return {
        "customer_name": customer_name,
        "agent_type": agent_type,
        "sales_rep": sales_rep
    }

# Helper to evaluate and summarize in background
async def evaluate_and_summarize(job_id: str, chat_history_str: str | None) -> None:
    try:
        report_card, overall_score = await evaluate_chat_history(chat_history_str)
        if report_card:
            summary_json_str = json.dumps(report_card)
            update_report_summary(job_id, summary_json_str, overall_score, "completed")
        else:
            update_report_summary(job_id, None, 0, "failed")
    except Exception as e:
        print(f"Error in background evaluation: {e}")
        update_report_summary(job_id, None, 0, "failed")

@app.post("/api/reports")
async def receive_report(payload: ReportPayload, background_tasks: BackgroundTasks):
    try:
        chat_history_str = None
        if payload.chat_history:
            chat_history_str = json.dumps(payload.chat_history)
            
        parsed = parse_room_details(payload.room)
        cust_name = payload.customer_name or parsed["customer_name"]
        ag_type = payload.agent_type or parsed["agent_type"]
        s_rep = payload.sales_rep or parsed["sales_rep"]
            
        save_report(
            job_id=payload.job_id,
            room_id=payload.room_id,
            room=payload.room,
            started_at=payload.started_at,
            ended_at=payload.ended_at,
            summary=None,
            overall_score=0,
            chat_history=chat_history_str,
            status="ongoing",
            customer_name=cust_name,
            agent_type=ag_type,
            sales_rep=s_rep
        )
        
        # Start background evaluation task
        background_tasks.add_task(evaluate_and_summarize, payload.job_id, chat_history_str)
        return {"status": "success", "message": f"Report for job {payload.job_id} received. Evaluation started in background."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reports/{job_id}/status")
async def get_report_status(job_id: str):
    report = get_report_by_job_id(job_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"status": report.get("status", "completed")}

@app.post("/api/reports/{job_id}/retry")
async def retry_report_evaluation(job_id: str, background_tasks: BackgroundTasks):
    report = get_report_by_job_id(job_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
        
    update_report_summary(job_id, None, 0, "ongoing")
    background_tasks.add_task(evaluate_and_summarize, job_id, report.get("chat_history"))
    return {"status": "success", "message": f"Retry evaluation started for job {job_id}."}

@app.get("/api/reports")
async def get_reports_api():
    try:
        reports = get_all_reports()
        
        # Calculate stats using completed evaluations only
        completed_reports = [r for r in reports if r.get("status") == "completed"]
        total_calls = len(completed_reports)
        avg_score = 0
        readiness_counts = {
            "Production Ready": 0,
            "Ready With Supervision": 0,
            "Developing": 0,
            "Needs Significant Coaching": 0,
            "Not Ready": 0
        }
        
        cleaned_reports = []
        for r in reports:
            scores = parse_summary_scores(r.get("summary"))
            if r.get("status") == "completed":
                avg_score += r.get("overall_score", 0)
                r_type = scores.get("readiness")
                if r_type in readiness_counts:
                    readiness_counts[r_type] += 1
            
            parsed = parse_room_details(r.get("room"))
            cust_name = r.get("customer_name") or parsed["customer_name"]
            ag_type = r.get("agent_type") or parsed["agent_type"]
            s_rep = r.get("sales_rep") or parsed["sales_rep"]
            
            cleaned_reports.append({
                "job_id": r.get("job_id"),
                "room": r.get("room"),
                "started_at": r.get("started_at"),
                "ended_at": r.get("ended_at"),
                "duration_seconds": r.get("duration_seconds"),
                "overall_score": r.get("overall_score"),
                "status": r.get("status"),
                "scores": scores,
                "customer_name": cust_name,
                "agent_type": ag_type,
                "sales_rep": s_rep
            })
            
        if total_calls > 0:
            avg_score = int(avg_score / total_calls)
        else:
            avg_score = 0
            
        return {
            "reports": cleaned_reports,
            "stats": {
                "total_calls": total_calls,
                "avg_score": avg_score,
                "readiness": readiness_counts
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    reports = get_all_reports()
    
    # Calculate stats using completed evaluations only
    completed_reports = [r for r in reports if r.get("status") == "completed"]
    total_calls = len(completed_reports)
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
        
        if r.get("status") == "completed":
            avg_score += r["overall_score"]
            r_type = scores["readiness"]
            if r_type in readiness_counts:
                readiness_counts[r_type] += 1
                
        parsed = parse_room_details(r.get("room"))
        r["customer_name"] = r.get("customer_name") or parsed["customer_name"]
        r["agent_type"] = r.get("agent_type") or parsed["agent_type"]
        r["sales_rep"] = r.get("sales_rep") or parsed["sales_rep"]
            
    if total_calls > 0:
        avg_score = int(avg_score / total_calls)
    else:
        avg_score = 0

    # Retrieve agent persona from cookie
    import urllib.parse
    import html
    persona_cookie = request.cookies.get("lk_agent_persona")
    persona_json = '{"persona": "default"}'
    if persona_cookie:
        try:
            decoded_cookie = urllib.parse.unquote(persona_cookie)
            # Verify it's valid JSON
            json.loads(decoded_cookie)
            persona_json = decoded_cookie
        except Exception:
            pass
            
    lk_agent_persona_json_escaped = html.escape(persona_json)
    
    # Retrieve agent type from cookie
    agent_type = request.cookies.get("lk_agent_type", "agent1")
    # Determine agent ID: Agent 1 (CA_5iixpgAFZLCw), STS Agent (CA_5LcV5zBscUja)
    agent_id = "CA_5iixpgAFZLCw" if agent_type == "agent1" else "CA_5LcV5zBscUja"
        
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "reports": reports,
            "stats": {
                "total_calls": total_calls,
                "avg_score": avg_score,
                "readiness": readiness_counts
            },
            "lk_agent_persona_json": lk_agent_persona_json_escaped,
            "lk_agent_id": agent_id,
            "lk_agent_type": agent_type
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
