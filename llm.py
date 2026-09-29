import os
from dotenv import load_dotenv
from openai import OpenAI
from tools import tools
load_dotenv()

client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com")

def chat(messages):
    response=client.chat.completions.create(
        model="deepseek-flash",
        messages=messages,
        tools=tools,
    )
    return response.choices[0].message