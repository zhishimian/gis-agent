import os
from dotenv import load_dotenv
from openai import OpenAI
from tools import registry
load_dotenv()

client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com")

def chat(messages,available_tools=None,):
    tools=registry.schemas(available_tools)
    kwargs={
        "model":"deepseek-flash",
        "messages":messages,
    }
    if tools:
        kwargs["tools"]=tools
    response=client.chat.completions.create(
        **kwargs
    )
    return response.choices[0].message