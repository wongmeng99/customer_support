"""Run the agent over the golden dataset and score it."""
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langsmith import Client
from pydantic import BaseModel

from support_agent.graph import graph

load_dotenv()
DATASET = "support-routing-golden"


# 1) TARGET: the thing under test. Takes an example's inputs, returns outputs.
def target(inputs: dict) -> dict:
    out = graph.invoke({"query": inputs["query"]})
    return {"category": out["category"], "response": out["response"]}


# 2) EVALUATOR (code): exact match between prediction and the golden label.
def routing_correct(outputs: dict, reference_outputs: dict) -> bool:
    return outputs["category"] == reference_outputs["category"]


# 3) EVALUATOR (LLM-as-judge): grade the drafted reply.
class Grade(BaseModel):
    reasoning: str
    good: bool


judge = init_chat_model("openai:gpt-4o-mini", temperature=0).with_structured_output(Grade)


def response_quality(inputs: dict, outputs: dict) -> dict:
    g = judge.invoke(
        "Grade this support reply. good=true only if it is relevant to the query, polite, "
        "and does not invent specific policies, prices, or promises.\n\n"
        f"Query: {inputs['query']}\nReply: {outputs['response']}"
    )
    return {"key": "response_quality", "score": g.good, "comment": g.reasoning}


if __name__ == "__main__":
    results = Client().evaluate(
        target,
        data=DATASET,
        evaluators=[routing_correct, response_quality],
        experiment_prefix="routing-v1",
        max_concurrency=4,
    )
    print(results)
