from app.services.services import get_openai_client, answer_question_from_bylaws

def chat_with_context(question, planning_data=None):

    client = get_openai_client()

    # 🔥 STEP 1: Get bylaws context from FAISS
    bylaw_response = answer_question_from_bylaws(question)

    bylaw_context = bylaw_response.get("answer", "")

    # 🔥 STEP 2: Add planning context (if exists)
    planning_context = ""

    if planning_data:
        planning_context = f"""
Planning Context:
Zone: {planning_data.get('zone')}
Plot Area: {planning_data.get('plot_area')}
FAR: {planning_data.get('far')}
Max Built Area: {planning_data.get('max_built_area')}
Setbacks: {planning_data.get('setbacks')}
Fire Rules: {planning_data.get('fire_rules')}
"""

    # 🔥 STEP 3: Final Prompt
    prompt = f"""
You are an expert Bangalore building regulations assistant.

Use BOTH:
1. Bylaws knowledge
2. Planning project context (if provided)

Answer clearly and practically.

Bylaw Context:
{bylaw_context}

{planning_context}

User Question:
{question}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a precise regulatory assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    return response.choices[0].message.content.strip()