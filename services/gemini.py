import os
import json
import logging
import httpx
from typing import Tuple

logger = logging.getLogger("report-server-gemini")

GEMINI_QA_REPORT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "scenario_practiced": {
            "type": "STRING",
            "description": "Brief summary of customer profile and situation"
        },
        "overall_score": {
            "type": "INTEGER",
            "description": "Overall score from 1 to 100"
        },
        "rapport": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER", "description": "Score from 1 to 10"},
                "reason": {"type": "STRING", "description": "Short explanation or evidence for the score"}
            },
            "required": ["score", "reason"]
        },
        "discovery": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER", "description": "Score from 1 to 10"},
                "reason": {"type": "STRING", "description": "Short explanation or evidence for the score"}
            },
            "required": ["score", "reason"]
        },
        "product_knowledge": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER", "description": "Score from 1 to 10"},
                "reason": {"type": "STRING", "description": "Short explanation or evidence for the score"}
            },
            "required": ["score", "reason"]
        },
        "communication": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER", "description": "Score from 1 to 10"},
                "reason": {"type": "STRING", "description": "Short explanation or evidence for the score"}
            },
            "required": ["score", "reason"]
        },
        "objection_handling": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER", "description": "Score from 1 to 10"},
                "reason": {"type": "STRING", "description": "Short explanation or evidence for the score"}
            },
            "required": ["score", "reason"]
        },
        "recommendation_quality": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER", "description": "Score from 1 to 10"},
                "reason": {"type": "STRING", "description": "Short explanation or evidence for the score"}
            },
            "required": ["score", "reason"]
        },
        "compliance": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER", "description": "Score from 1 to 10"},
                "reason": {"type": "STRING", "description": "Short explanation or evidence for the score"}
            },
            "required": ["score", "reason"]
        },
        "closing": {
            "type": "OBJECT",
            "properties": {
                "score": {"type": "INTEGER", "description": "Score from 1 to 10"},
                "reason": {"type": "STRING", "description": "Short explanation or evidence for the score"}
            },
            "required": ["score", "reason"]
        },
        "positives": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "List of strongest behaviors observed (empty list if none)"
        },
        "improvement_areas": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "List of the most important weaknesses/improvements"
        },
        "missed_opportunities": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "List of important questions that should have been asked"
        },
        "compliance_issues": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "List of compliance concerns/violations (empty list if none)"
        },
        "coaching_recommendations": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "3 specific coaching recommendations"
        },
        "readiness_assessment": {
            "type": "STRING",
            "description": "Readiness assessment (must be one of: 'Not Ready', 'Needs Significant Coaching', 'Developing', 'Ready With Supervision', 'Production Ready')"
        },
        "readiness_reasoning": {
            "type": "STRING",
            "description": "Detailed reasoning for the readiness assessment"
        }
    },
    "required": [
        "scenario_practiced",
        "overall_score",
        "rapport",
        "discovery",
        "product_knowledge",
        "communication",
        "objection_handling",
        "recommendation_quality",
        "compliance",
        "closing",
        "positives",
        "improvement_areas",
        "missed_opportunities",
        "compliance_issues",
        "coaching_recommendations",
        "readiness_assessment",
        "readiness_reasoning"
    ]
}

SYSTEM_PROMPT = """You are an expert SBI Mutual Fund sales trainer and quality analyst.
Your task is to evaluate the conversation between a sales representative and a prospective customer.
Evaluate the sales representative only. Do not evaluate the customer.
Use the entire conversation transcript as evidence. Be objective and specific.
Do not invent information that was not present in the conversation.

Evaluate based on the following criteria:
1. Rapport & Professionalism
2. Discovery & Needs Analysis
3. Product Knowledge
4. Communication Skills
5. Objection Handling
6. Recommendation Quality
7. Compliance & Ethical Conduct
8. Closing Effectiveness"""

def format_transcript_for_llm(chat_history_str: str | None) -> str:
    if not chat_history_str:
        return "No transcript available."
    try:
        data = json.loads(chat_history_str)
        items = data.get("items", [])
        lines = []
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
            
            speaker = "Ira Representative" if role == "user" else "AI Customer"
            lines.append(f"{speaker}: {text.strip()}")
            
        return "\n".join(lines)
    except Exception as e:
        return f"Error parsing transcript: {e}"

async def evaluate_chat_history(chat_history_str: str | None) -> Tuple[dict | None, int | None]:
    """
    Calls Gemini API to evaluate the chat history.
    Returns a tuple: (report_card_dict, overall_score) or (None, None) on failure.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("Gemini API key not found in environment variables.")
        return None, None

    transcript = format_transcript_for_llm(chat_history_str)
    
    prompt = f"{SYSTEM_PROMPT}\n\nHere is the conversation transcript:\n{transcript}"
    
    # Model URL Options:
    # Gemini 2.5 Flash:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    
    # Gemini 3 Flash:
    # url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash:generateContent?key={api_key}"
    
    # Gemini 3.5 Flash:
    # url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": GEMINI_QA_REPORT_SCHEMA
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"Gemini API returned error status {response.status_code}: {response.text}")
                return None, None
            
            response_json = response.json()
            candidates = response_json.get("candidates", [])
            if not candidates:
                logger.error(f"No candidates returned from Gemini: {response_json}")
                return None, None
            
            content_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not content_text:
                logger.error("Empty text in Gemini response candidate.")
                return None, None
            
            report_card = json.loads(content_text.strip())
            overall_score = report_card.get("overall_score", 0)
            return report_card, overall_score
            
    except Exception as e:
        logger.exception(f"Exception during Gemini evaluation: {e}")
        return None, None
