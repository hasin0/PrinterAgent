"""Quick test to verify your Groq API key and LangChain setup works."""

from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq

# Initialize the model (same as yours but corrected)
model = ChatGroq(
    model="llama-3.3-70b-versatile",  # Upgraded — free & much smarter
    temperature=0.0,
    max_retries=2,
)

# Simple test
response = model.invoke("Say 'Hello Hassan, your printer agent is ready!' and nothing else.")
print(f"\n✅ Groq is working!\n")
print(f"Response: {response.content}")
print(f"Model: {response.response_metadata.get('model_name', 'unknown')}")
print(f"Tokens used: {response.response_metadata.get('token_usage', {})}")