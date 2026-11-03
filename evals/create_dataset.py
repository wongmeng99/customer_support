"""Create the golden dataset in LangSmith (safe to re-run: skips if it exists)."""
from dotenv import load_dotenv
from langsmith import Client

load_dotenv()
DATASET = "support-routing-golden"

# (query, expected primary category)
EXAMPLES = [
    # billing
    ("I was charged twice for my subscription this month.", "billing"),
    ("How do I download my invoice for March?", "billing"),
    ("I want a refund for my last payment.", "billing"),
    ("Can I switch from monthly to annual billing?", "billing"),
    ("Why did my price go up?", "billing"),
    ("My credit card was declined but I have funds.", "billing"),
    # technical
    ("The app crashes every time I open the dashboard.", "technical"),
    ("I get a 500 error when uploading files.", "technical"),
    ("Notifications stopped working on my phone.", "technical"),
    ("The API returns timeouts since this morning.", "technical"),
    ("Export to CSV gives me an empty file.", "technical"),
    ("The page won't load in Safari.", "technical"),
    # account
    ("How do I reset my password?", "account"),
    ("I want to change the email on my account.", "account"),
    ("Please delete my account and data.", "account"),
    ("How do I add a teammate to my workspace?", "account"),
    ("I never got the verification email.", "account"),
    ("Can I change my username?", "account"),
    # unclear / off-topic
    ("hello", "unclear"),
    ("Help!!", "unclear"),
    ("What's the weather like today?", "unclear"),
    # ambiguous / multi-intent: we decided the PRIMARY (first-blocking) issue wins
    ("I was charged twice and can't log in.", "billing"),
    ("I can't log in, and the reset email never arrives.", "account"),
    ("The app keeps crashing, I want my money back.", "technical"),
]

client = Client()
if client.has_dataset(dataset_name=DATASET):
    print(f"Dataset '{DATASET}' already exists; nothing to do.")
else:
    ds = client.create_dataset(DATASET, description="Golden set for support query routing")
    client.create_examples(
        dataset_id=ds.id,
        inputs=[{"query": q} for q, _ in EXAMPLES],
        outputs=[{"category": c} for _, c in EXAMPLES],
    )
    print(f"Created '{DATASET}' with {len(EXAMPLES)} examples.")
