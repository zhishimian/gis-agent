from llm import chat
import json
from sessions import load_session,save_session
from tools import registry

session_id=input("Session: ")
messages=load_session(session_id)

while True:
    user_input=input("You: ")
    if user_input=="exit":
        break
    messages.append(
        {
            "role":"user",
            "content":user_input,
        }
    )
    while True:
        message=chat(messages)
        assistant_message={
            "role":"assistant",
            "content":message.content,
        }

        if message.tool_calls:
            assistant_message["tool_calls"]=[
                tool_call.model_dump()
                for tool_call in message.tool_calls
            ]
        
        messages.append(assistant_message)
        if not message.tool_calls:
            print("Agent:",message.content)
            break

        for tool_call in message.tool_calls:
            name=tool_call.function.name
            print("Tool called:", name)
            arguments=json.loads(
                tool_call.function.arguments
            )
            print("Tool arguments:", arguments)
            result=registry.execute(
                name,
                arguments,
            )
            print("Tool result:", result)
            messages.append(
                {
                    "role":"tool",
                    "tool_call_id":tool_call.id,
                    "content":str(result),
                }
            )
    save_session(session_id,messages)